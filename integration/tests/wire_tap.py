"""Bounded passive loopback relay for real-server integration evidence.

Only complete JSON/LF frames are observed. Their original bytes, including the
terminator, are forwarded unchanged after capture. Credentials exist only in
transient relay buffers and the caller-supplied private redaction value; retained
events and the final immutable evidence contain decoded, sanitised JSON only.
This module neither injects faults nor interprets application success.
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
import select
import socket
import threading
import time
import uuid


MAX_FRAME_BYTES = 65536  # Excludes LF, as in the production framing contract.
MAX_FRAMES = 256
MAX_BYTES = MAX_FRAMES * (MAX_FRAME_BYTES + 1)
MAX_CONNECTIONS = 32
_POLL_SECONDS = 0.05
_IO_TIMEOUT = 5.0


class WireTapError(AssertionError):
    """A capture, bound or finite-shutdown failure without peer-controlled text."""


class _CaptureBoundError(Exception):
    pass


class _IncompleteFrameError(Exception):
    pass


class WireTap:
    """Observe independent client connections without modifying their frames.

    ``port`` is available inside the context. ``snapshot()`` and ``events``
    return independent copies, while ``frames_for_session(uuid)`` resolves the
    connection using its successful ``system.hello`` response. Final evidence is
    written exactly once on exit; an existing destination is never replaced.
    Unexpected relay errors fail the context after cleanup, unless an exception
    is already propagating from its body.
    """

    def __init__(self, upstream_host: str = "127.0.0.1", upstream_port: int = 4711,
                 *, token: str, evidence: Path) -> None:
        if not isinstance(token, str) or not token:
            raise ValueError("A nonempty redaction credential is required")
        if upstream_host != "127.0.0.1":
            raise ValueError("The integration upstream must use IPv4 loopback")
        if type(upstream_port) is not int or not 1 <= upstream_port <= 65535:
            raise ValueError("A valid upstream port is required")
        self._upstream = (upstream_host, upstream_port)
        self._token = token
        self.evidence = Path(evidence)
        self.port: int | None = None
        self._lock = threading.Lock()
        self._connection_changed = threading.Condition(self._lock)
        self._stop = threading.Event()
        self._listener: socket.socket | None = None
        self._accept_thread: threading.Thread | None = None
        self._workers: list[threading.Thread] = []
        self._sockets: set[socket.socket] = set()
        self._sessions: dict[str, dict] = {}
        self._hello_ids: dict[str, object] = {}
        self._events: list[dict] = []
        self._errors: list[dict] = []
        self._byte_count = 0
        self._entered = False
        self._closed = False

    def __enter__(self) -> WireTap:
        if self._entered or self.evidence.exists():
            raise ValueError("A fresh wire tap and evidence destination are required")
        self._entered = True
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind(("127.0.0.1", 0))
            listener.listen(MAX_CONNECTIONS)
            listener.settimeout(_POLL_SECONDS)
            self.port = listener.getsockname()[1]
            self._listener = listener
            self._accept_thread = threading.Thread(
                target=self._accept, name="minebridge-wire-accept", daemon=True)
            self._accept_thread.start()
            return self
        except BaseException:
            listener.close()
            raise

    @property
    def events(self) -> list[dict]:
        return self.snapshot()

    def snapshot(self) -> list[dict]:
        with self._lock:
            return copy.deepcopy(self._events)

    def frames_for_session(self, session_uuid: str) -> list[dict]:
        with self._lock:
            connections = {
                key for key, value in self._sessions.items()
                if value.get("sessionId") == session_uuid
            }
            if len(connections) > 1:
                raise WireTapError("A session ID belongs to multiple captured connections")
            return copy.deepcopy([
                event for event in self._events if event["connectionId"] in connections
            ])

    def wait_closed(self, timeout: float = _IO_TIMEOUT) -> bool:
        """Await actual endpoint closure, without inferring it from a sleep."""
        if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout) or timeout < 0):
            raise ValueError("A nonnegative closure timeout is required")
        deadline = time.monotonic() + timeout
        with self._connection_changed:
            while True:
                if all(item["closed"] for item in self._sessions.values()):
                    return True
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._connection_changed.wait(remaining)

    def _clean(self, value: object) -> object:
        if isinstance(value, str):
            return value.replace(self._token, "[REDACTED]")
        if isinstance(value, dict):
            return {self._clean(key): self._clean(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._clean(item) for item in value]
        return value

    def _capture(self, connection_id: str, direction: str, payload: bytes) -> None:
        # Never include decoder exceptions or raw payloads in retained state.
        decoded = json.loads(payload.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise WireTapError("A captured RPC frame must be a JSON object")
        if decoded.get("method") == "system.hello":
            parameters = decoded.get("params")
            if isinstance(parameters, dict):
                parameters.pop("token", None)
        frame = self._clean(decoded)
        with self._lock:
            if len(self._events) >= MAX_FRAMES:
                raise _CaptureBoundError
            self._byte_count += len(payload) + 1
            if self._byte_count > MAX_BYTES:
                raise _CaptureBoundError
            session = self._sessions[connection_id]
            if direction == "request" and frame.get("method") == "system.hello":
                self._hello_ids[connection_id] = frame.get("id")
            if (direction == "response" and connection_id in self._hello_ids
                    and frame.get("id") == self._hello_ids[connection_id]
                    and isinstance(frame.get("result"), dict)):
                session_id = frame["result"].get("sessionId")
                if isinstance(session_id, str):
                    session["sessionId"] = session_id
            session[direction + "Frames"] += 1
            self._events.append({
                "connectionId": connection_id, "direction": direction,
                "sequence": len(self._events) + 1, "frame": frame,
            })

    def _error(self, stage: str, failure: BaseException,
               connection_id: str | None = None) -> None:
        with self._lock:
            self._errors.append({
                "stage": stage, "type": type(failure).__name__,
                "connectionId": connection_id,
            })

    @staticmethod
    def _close_socket(endpoint: socket.socket) -> None:
        try:
            endpoint.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        endpoint.close()

    def _accept(self) -> None:
        listener = self._listener
        assert listener is not None
        while not self._stop.is_set():
            try:
                downstream, _address = listener.accept()
            except TimeoutError:
                continue
            except OSError as failure:
                if not self._stop.is_set():
                    self._error("accept", failure)
                return
            connection_id = uuid.uuid4().hex
            with self._lock:
                if self._stop.is_set() or len(self._sessions) >= MAX_CONNECTIONS:
                    downstream.close()
                    if not self._stop.is_set():
                        self._errors.append({"stage": "accept", "type": "ConnectionBoundError",
                                             "connectionId": None})
                    self._stop.set()
                    return
                self._sockets.add(downstream)
                self._sessions[connection_id] = {
                    "connectionId": connection_id, "closed": False,
                    "requestFrames": 0, "responseFrames": 0,
                }
                worker = threading.Thread(
                    target=self._relay, args=(connection_id, downstream),
                    name="minebridge-wire-" + connection_id[:8], daemon=True)
                self._workers.append(worker)
                worker.start()

    def _relay(self, connection_id: str, downstream: socket.socket) -> None:
        upstream: socket.socket | None = None
        try:
            if self._stop.is_set():
                return
            upstream = socket.create_connection(self._upstream, timeout=_IO_TIMEOUT)
            with self._lock:
                self._sockets.add(upstream)
            if self._stop.is_set():
                return
            downstream.settimeout(_IO_TIMEOUT)
            upstream.settimeout(_IO_TIMEOUT)
            peers = {downstream: (upstream, "request"), upstream: (downstream, "response")}
            buffers = {downstream: bytearray(), upstream: bytearray()}
            reading = set(peers)
            eof_deadline: float | None = None
            while reading and not self._stop.is_set():
                if eof_deadline is not None and time.monotonic() >= eof_deadline:
                    break
                ready, _, _ = select.select(list(reading), [], [], _POLL_SECONDS)
                for source in ready:
                    destination, direction = peers[source]
                    chunk = source.recv(8192)
                    pending = buffers[source]
                    if not chunk:
                        if pending:
                            raise _IncompleteFrameError
                        reading.remove(source)
                        try:
                            destination.shutdown(socket.SHUT_WR)
                        except OSError:
                            pass
                        if eof_deadline is None:
                            eof_deadline = time.monotonic() + _IO_TIMEOUT
                        continue
                    pending.extend(chunk)
                    while True:
                        newline = pending.find(b"\n")
                        if newline < 0:
                            if len(pending) > MAX_FRAME_BYTES:
                                raise _CaptureBoundError
                            break
                        if newline > MAX_FRAME_BYTES:
                            raise _CaptureBoundError
                        wire_frame = bytes(pending[:newline + 1])
                        del pending[:newline + 1]
                        self._capture(connection_id, direction, wire_frame[:-1])
                        destination.sendall(wire_frame)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass  # An ordinary peer close can race with either relay direction.
        except BaseException as failure:
            if not self._stop.is_set():
                self._error("relay", failure, connection_id)
        finally:
            for endpoint in (downstream, upstream):
                if endpoint is not None:
                    self._close_socket(endpoint)
                    with self._lock:
                        self._sockets.discard(endpoint)
            with self._lock:
                self._sessions[connection_id]["closed"] = True
                self._connection_changed.notify_all()

    def __exit__(self, exception_type: object, exception: object, traceback: object) -> bool:
        self._stop.set()
        if self._listener is not None:
            self._close_socket(self._listener)
        with self._lock:
            endpoints = list(self._sockets)
        for endpoint in endpoints:
            self._close_socket(endpoint)
        deadline = time.monotonic() + _IO_TIMEOUT + 1.0
        if self._accept_thread is not None:
            self._accept_thread.join(max(0.0, deadline - time.monotonic()))
            if self._accept_thread.is_alive():
                self._error("shutdown", TimeoutError())
        # The acceptor has stopped adding workers before this snapshot.
        with self._lock:
            workers = list(self._workers)
        for worker in workers:
            worker.join(max(0.0, deadline - time.monotonic()))
            if worker.is_alive():
                self._error("shutdown", TimeoutError())
        with self._lock:
            self._closed = (not any(worker.is_alive() for worker in workers)
                            and (self._accept_thread is None or not self._accept_thread.is_alive())
                            and all(item["closed"] for item in self._sessions.values()))
            document = {
                "schemaVersion": 1, "closed": self._closed,
                "capturedBytes": self._byte_count,
                "limits": {"frameBytes": MAX_FRAME_BYTES, "frames": MAX_FRAMES,
                           "bytes": MAX_BYTES, "connections": MAX_CONNECTIONS},
                "sessions": copy.deepcopy(list(self._sessions.values())),
                "events": copy.deepcopy(self._events), "errors": copy.deepcopy(self._errors),
            }
        try:
            self.evidence.parent.mkdir(parents=True, exist_ok=True)
            with self.evidence.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(document, stream, indent=2, allow_nan=False)
                stream.write("\n")
        except BaseException:
            if exception_type is None:
                raise WireTapError("Wire tap evidence publication failed") from None
        if exception_type is None and (self._errors or not self._closed):
            raise WireTapError("Wire tap capture or finite shutdown failed") from None
        return False
