"""Bounded deterministic TCP faults for the T10 installed-client acceptance.

FaultProxy relays the real hello unchanged, then withholds one complete
blocks.set response. ControlledPeer is explicitly a client-contract fixture;
its synthetic hello and replies are never used as evidence about Paper state.
Only sanitised decoded frames are retained. All listeners, buffers, workers and
waits have finite bounds; no credential is put in an exception or evidence file.
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


MAX_FRAME_BYTES = 65536
MAX_FRAMES = 64
MAX_CONNECTIONS = 4
IO_TIMEOUT = 5.0
POLL_SECONDS = .02


class FaultFixtureError(AssertionError):
    """A fixture failure containing no untrusted peer text."""


class FaultProxy:
    """Hold a complete real blocks.set reply after an untouched real hello.

    The captured event is set only after the upstream response has arrived in
    full. Neither a predicted tick nor an assumed setter duration is a barrier.
    While holding the reply, the relay still observes downstream EOF. Explicit
    release/drop controls affect only this target response/connection.
    """

    def __init__(self, *, token: str, evidence: Path, upstream_port: int = 4711,
                 mode: str = "hold") -> None:
        if not isinstance(token, str) or not token:
            raise ValueError("A nonempty redaction credential is required")
        if type(upstream_port) is not int or not 1 <= upstream_port <= 65535:
            raise ValueError("A valid loopback upstream port is required")
        if mode != "hold":
            raise ValueError("A supported fault mode is required")
        self._token, self.evidence = token, Path(evidence)
        self._upstream = ("127.0.0.1", upstream_port)
        self.mode = mode
        self.port: int | None = None
        self._lock = threading.Lock()
        self._changed = threading.Condition(self._lock)
        self._stop = threading.Event()
        self._captured = threading.Event()
        self._release = threading.Event()
        self._drop = threading.Event()
        self._released = threading.Event()
        self._listener: socket.socket | None = None
        self._accept_thread: threading.Thread | None = None
        self._workers: list[threading.Thread] = []
        self._sockets: set[socket.socket] = set()
        self._connections: dict[str, dict] = {}
        self._events: list[dict] = []
        self._errors: list[dict] = []
        self._target: dict | None = None
        self._entered = False

    def __enter__(self):
        if self._entered or self.evidence.exists():
            raise ValueError("A fresh fixture and evidence destination are required")
        self._entered = True
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind(("127.0.0.1", 0))
            listener.listen(MAX_CONNECTIONS)
            listener.settimeout(POLL_SECONDS)
            self.port = listener.getsockname()[1]
            self._listener = listener
            self._accept_thread = threading.Thread(target=self._accept, daemon=True,
                                                   name="minebridge-fault-accept")
            self._accept_thread.start()
            return self
        except BaseException:
            listener.close()
            raise

    @staticmethod
    def _timeout(timeout: float) -> float:
        if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout) or timeout < 0):
            raise ValueError("A nonnegative finite wait is required")
        return float(timeout)

    def await_captured(self, timeout: float = IO_TIMEOUT) -> dict:
        if not self._captured.wait(self._timeout(timeout)):
            raise FaultFixtureError("The target response capture deadline elapsed")
        with self._lock:
            return copy.deepcopy(self._target)

    def release(self) -> None:
        self._release.set()

    def drop(self) -> None:
        self._drop.set()

    def await_released(self, timeout: float = IO_TIMEOUT) -> bool:
        return self._released.wait(self._timeout(timeout))

    def wait_closed(self, timeout: float = IO_TIMEOUT) -> bool:
        deadline = time.monotonic() + self._timeout(timeout)
        with self._changed:
            while True:
                if self._connections and all(item["closed"] for item in self._connections.values()):
                    return True
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._changed.wait(remaining)

    def wait_downstream_eof(self, timeout: float = IO_TIMEOUT) -> bool:
        """Await an actual recv()==b'' rather than predicting client closure."""
        deadline = time.monotonic() + self._timeout(timeout)
        with self._changed:
            while True:
                if self._connections and all(item["downstreamEof"] for item in self._connections.values()):
                    return True
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._changed.wait(remaining)

    def snapshot(self) -> dict:
        with self._lock:
            return copy.deepcopy({
                "schemaVersion": 1, "fixture": type(self).__name__, "mode": self.mode,
                "closed": bool(self._connections) and all(item["closed"] for item in self._connections.values()),
                "target": self._target, "connections": list(self._connections.values()),
                "events": self._events, "errors": self._errors,
                "limits": {"connections": MAX_CONNECTIONS, "frames": MAX_FRAMES,
                           "frameBytes": MAX_FRAME_BYTES},
            })

    def _clean(self, value):
        if isinstance(value, str):
            return value.replace(self._token, "[REDACTED]")
        if isinstance(value, dict):
            return {self._clean(key): self._clean(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._clean(item) for item in value]
        return value

    def _event(self, connection: str, direction: str, payload: bytes, delivery: str) -> dict:
        # Invalid peer data is intentionally not copied into error messages.
        frame = json.loads(payload.decode("utf-8"))
        if not isinstance(frame, dict):
            raise FaultFixtureError("A captured frame must be an object")
        if frame.get("method") == "system.hello" and isinstance(frame.get("params"), dict):
            frame["params"].pop("token", None)
        frame = self._clean(frame)
        with self._lock:
            if len(self._events) >= MAX_FRAMES:
                raise FaultFixtureError("The finite frame capture limit was reached")
            event = {"sequence": len(self._events) + 1, "connectionId": connection,
                     "direction": direction, "frame": frame, "delivery": delivery,
                     "monotonicNs": time.monotonic_ns()}
            self._events.append(event)
            self._connections[connection][direction + "Frames"] += 1
            if direction == "request" and frame.get("method") == "blocks.set":
                self._connections[connection]["mutationRequests"] += 1
            return event

    def _mark_target(self, event: dict) -> None:
        with self._lock:
            if self._target is not None:
                raise FaultFixtureError("Only one target response is permitted")
            self._target = event
        self._captured.set()

    def _delivery(self, event: dict, state: str) -> None:
        with self._lock:
            event["delivery"] = state
            event["deliveryMonotonicNs"] = time.monotonic_ns()

    def _error(self, stage: str, failure: BaseException) -> None:
        with self._lock:
            self._errors.append({"stage": stage, "type": type(failure).__name__})

    @staticmethod
    def _close(endpoint: socket.socket) -> None:
        try:
            endpoint.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        endpoint.close()

    def _accept(self) -> None:
        while not self._stop.is_set():
            try:
                downstream, _ = self._listener.accept()
            except TimeoutError:
                continue
            except OSError as failure:
                if not self._stop.is_set():
                    self._error("accept", failure)
                break
            with self._lock:
                if len(self._connections) >= MAX_CONNECTIONS or self._stop.is_set():
                    downstream.close()
                    if not self._stop.is_set():
                        self._errors.append({"stage": "accept", "type": "ConnectionBoundError"})
                    break
                connection = uuid.uuid4().hex
                self._connections[connection] = {
                    "connectionId": connection, "closed": False, "downstreamEof": False,
                    "requestFrames": 0, "responseFrames": 0, "mutationRequests": 0,
                }
                self._sockets.add(downstream)
                worker = threading.Thread(target=self._worker, args=(connection, downstream),
                                          daemon=True, name="minebridge-fault-" + connection[:8])
                self._workers.append(worker)
                worker.start()

    def _worker(self, connection: str, downstream: socket.socket) -> None:
        endpoints = [downstream]
        try:
            downstream.settimeout(IO_TIMEOUT)
            self._serve(connection, downstream, endpoints)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass
        except BaseException as failure:
            if not self._stop.is_set():
                self._error("serve", failure)
        finally:
            for endpoint in endpoints:
                self._close(endpoint)
                with self._lock:
                    self._sockets.discard(endpoint)
            with self._changed:
                self._connections[connection]["closed"] = True
                self._changed.notify_all()

    @staticmethod
    def _frames(buffer: bytearray, chunk: bytes) -> list[bytes]:
        buffer.extend(chunk)
        frames = []
        while True:
            newline = buffer.find(b"\n")
            if newline < 0:
                if len(buffer) > MAX_FRAME_BYTES:
                    raise FaultFixtureError("The finite frame byte limit was reached")
                return frames
            if newline > MAX_FRAME_BYTES:
                raise FaultFixtureError("The finite frame byte limit was reached")
            frames.append(bytes(buffer[:newline + 1]))
            del buffer[:newline + 1]

    def _eof(self, connection: str) -> None:
        with self._changed:
            self._connections[connection]["downstreamEof"] = True
            self._changed.notify_all()

    def _serve(self, connection: str, downstream: socket.socket,
               endpoints: list[socket.socket]) -> None:
        upstream = socket.create_connection(self._upstream, timeout=IO_TIMEOUT)
        upstream.settimeout(IO_TIMEOUT)
        endpoints.append(upstream)
        with self._lock:
            self._sockets.add(upstream)
        peers = {downstream: (upstream, "request"), upstream: (downstream, "response")}
        buffers = {endpoint: bytearray() for endpoint in peers}
        mutation_ids = set()
        held: tuple[bytes, dict] | None = None
        try:
            while not self._stop.is_set():
                if held is not None:
                    if self._drop.is_set():
                        self._delivery(held[1], "dropped")
                        return
                    if self._release.is_set():
                        downstream.sendall(held[0])
                        self._delivery(held[1], "released")
                        held = None
                        self._released.set()
                readable, _, _ = select.select(list(peers), [], [], POLL_SECONDS)
                for source in readable:
                    destination, direction = peers[source]
                    chunk = source.recv(8192)
                    if not chunk:
                        if source is downstream:
                            self._eof(connection)
                        if buffers[source]:
                            raise FaultFixtureError("An incomplete captured frame reached EOF")
                        return
                    for wire in self._frames(buffers[source], chunk):
                        frame = json.loads(wire[:-1].decode("utf-8"))
                        target = direction == "response" and frame.get("id") in mutation_ids
                        event = self._event(connection, direction, wire[:-1], "held" if target else "forwarded")
                        if direction == "request" and frame.get("method") == "blocks.set":
                            mutation_ids.add(frame.get("id"))
                        if target:
                            if held is not None:
                                raise FaultFixtureError("A second target arrived before the first completed")
                            held = (wire, event)
                            self._mark_target(event)
                        else:
                            destination.sendall(wire)
        finally:
            if held is not None and held[1]["delivery"] == "held":
                self._delivery(held[1], "closed-before-release")

    def __exit__(self, exception_type, _exception, _traceback) -> bool:
        self._stop.set()
        if self._listener is not None:
            self._close(self._listener)
        with self._lock:
            endpoints = list(self._sockets)
        for endpoint in endpoints:
            self._close(endpoint)
        deadline = time.monotonic() + IO_TIMEOUT + 1
        if self._accept_thread is not None:
            self._accept_thread.join(max(0, deadline - time.monotonic()))
        for worker in self._workers:
            worker.join(max(0, deadline - time.monotonic()))
        alive = any(worker.is_alive() for worker in self._workers)
        alive |= self._accept_thread is not None and self._accept_thread.is_alive()
        if alive:
            self._error("shutdown", TimeoutError())
        document = self.snapshot()
        self.evidence.parent.mkdir(parents=True, exist_ok=True)
        with self.evidence.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(document, stream, indent=2, allow_nan=False)
            stream.write("\n")
        if exception_type is None and (document["errors"] or alive):
            raise FaultFixtureError("The fault fixture failed capture or finite shutdown")
        return False


class ControlledPeer(FaultProxy):
    """Synthetic valid hello followed by one deliberately invalid/late ACK.

    This peer never connects to Paper. A late ACK is released only by an
    explicit test barrier after the client reports TIMEOUT and EOF is observed.
    """

    def __init__(self, *, token: str, evidence: Path, mode: str) -> None:
        if mode not in ("wrong-id", "malformed-false", "malformed-type", "late"):
            raise ValueError("A supported controlled-peer mode is required")
        super().__init__(token=token, evidence=evidence)
        self.mode = mode

    @staticmethod
    def _hello() -> dict:
        return {
            "protocol": {"major": 1, "minor": 0}, "sessionId": str(uuid.uuid4()),
            "pluginVersion": "controlled-peer-fixture", "serverVersion": "controlled-peer-fixture",
            "world": {"name": "controlled-peer", "uuid": str(uuid.uuid4()),
                      "minY": -64, "maxYExclusive": 320},
            "coordinates": "absolute", "chunkPolicy": "loaded-only", "applyPhysics": True,
            "capabilities": ["blocks.set"],
            "limits": {"maxFrameBytes": 65536, "maxJsonDepth": 16, "maxSessions": 8,
                       "maxQueuedRequests": 8, "maxOutputFrames": 8,
                       "handshakeTimeoutSeconds": 5, "frameAssemblyTimeoutSeconds": 5,
                       "writeTimeoutSeconds": 5, "maxOperationsPerTick": 32,
                       "maxOperationsPerSessionPerTick": 4, "executorBudgetMillis": 2},
        }

    @staticmethod
    def _encode(frame: dict) -> bytes:
        return json.dumps(frame, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"

    def _serve(self, connection: str, downstream: socket.socket,
               endpoints: list[socket.socket]) -> None:
        buffer = bytearray()
        hello_done = False
        held: tuple[bytes, dict] | None = None
        eof = False
        while not self._stop.is_set():
            if held is not None and self._release.is_set():
                self._delivery(held[1], "late-send-attempted")
                try:
                    downstream.sendall(held[0])
                except OSError:
                    self._delivery(held[1], "late-send-rejected-after-client-close")
                else:
                    self._delivery(held[1], "late-send-after-client-close")
                self._released.set()
                return
            if eof:
                self._stop.wait(POLL_SECONDS)
                continue
            ready, _, _ = select.select([downstream], [], [], POLL_SECONDS)
            if not ready:
                continue
            chunk = downstream.recv(8192)
            if not chunk:
                self._eof(connection)
                if buffer:
                    raise FaultFixtureError("An incomplete controlled-peer request reached EOF")
                if held is None:
                    return
                eof = True
                continue
            for wire in self._frames(buffer, chunk):
                request = json.loads(wire[:-1].decode("utf-8"))
                self._event(connection, "request", wire[:-1], "received-by-controlled-peer")
                if not hello_done:
                    if request.get("method") != "system.hello":
                        raise FaultFixtureError("The controlled peer expected hello first")
                    reply = self._encode({"jsonrpc": "2.0", "id": request["id"], "result": self._hello()})
                    self._event(connection, "response", reply[:-1], "delivered")
                    downstream.sendall(reply)
                    hello_done = True
                    continue
                if request.get("method") != "blocks.set":
                    raise FaultFixtureError("The controlled peer expected a block request")
                reply = {"jsonrpc": "2.0", "id": request["id"], "result": {"applied": True}}
                if self.mode == "wrong-id":
                    reply["id"] += 1
                elif self.mode == "malformed-false":
                    reply["result"] = {"applied": False}
                elif self.mode == "malformed-type":
                    reply["result"] = {"applied": "true"}
                encoded = self._encode(reply)
                event = self._event(connection, "response", encoded[:-1],
                                    "held" if self.mode == "late" else "delivered")
                if self.mode == "late":
                    held = (encoded, event)
                else:
                    downstream.sendall(encoded)
                self._mark_target(event)
