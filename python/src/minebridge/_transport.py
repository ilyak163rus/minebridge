"""Bounded TCP request window with one independent response reader.

Writes may be pipelined; every request still has a server acknowledgement.
There are no automatic retries/reconnections and no unbounded outgoing queue.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
import atexit
import errno
import math
import select
import socket
import threading
import time
import sys
import weakref

from . import errors
from ._handshake import SessionContext, context_from_result, prepare_hello
from ._event_state import EventState
from ._protocol import (
    CodecError, FrameDecoder, MAX_ID, Response, decode_event, decode_progress, decode_response, encode_frame,
    server_error_exception,
)

_POLL_SECONDS = 0.05
_MAX_WINDOW = 128
_EXIT_TRANSPORTS: weakref.WeakSet[TcpTransport] = weakref.WeakSet()
_EXIT_LOCK = threading.Lock()


def _finish_at_exit() -> None:
    # The daemon receiver deliberately does not keep Python alive. Drain on the
    # normal interpreter exit path while the receiver and sockets still work.
    with _EXIT_LOCK:
        transports = tuple(_EXIT_TRANSPORTS)
    for transport in transports:
        try:
            transport.finish()
        except Exception as failure:
            print(f"Minebridge: {type(failure).__name__}: {failure}. "
                  "Call mc.flush() or mc.close() explicitly to handle this error in your program.",
                  file=sys.stderr)


atexit.register(_finish_at_exit)
_CONNECTING = frozenset(value for value in (
    errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY,
    getattr(errno, "WSAEWOULDBLOCK", None),
    getattr(errno, "WSAEINPROGRESS", None),
    getattr(errno, "WSAEALREADY", None),
) if value is not None)
_CLOSE_ERROR_NUMBERS = frozenset({"-32700", "-32600", "-32001", "-32002", "-32003", "-32004"})


class _DeadlineExpired(Exception):
    pass


class _ConnectionClosed(Exception):
    pass


def _positive_timeout(value: object) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TypeError("timeout must be a finite positive number")
    try:
        timeout = float(value)
    except OverflowError:
        raise ValueError("timeout must be a finite positive number") from None
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be a finite positive number")
    return timeout


def _wait_ready(sock: socket.socket, *, read: bool, deadline: float) -> None:
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _DeadlineExpired
        try:
            readers, writers, exceptional = select.select(
                [sock] if read else [], [] if read else [sock], [sock],
                min(remaining, _POLL_SECONDS),
            )
        except ValueError:
            raise _ConnectionClosed from None
        if readers or writers or exceptional:
            if time.monotonic() >= deadline:
                raise _DeadlineExpired
            return


@dataclass
class _Pending:
    request_id: int
    method: str
    mutation: bool
    deferred: bool
    possibly_sent: bool = False
    deadline: float | None = None
    done: bool = False
    response: Response | None = None
    failure: errors.MinecraftError | None = None
    subscription_id: str | None = None


class TcpTransport:
    """One writer owner and one receiver; at most 128 unacknowledged RPCs."""

    def __init__(self, sock: socket.socket, timeout: float) -> None:
        self._socket: socket.socket | None = sock
        self._timeout = timeout
        self._rpc_lock = threading.RLock()
        self._condition = threading.Condition()
        self._next_id = 1
        self._context: SessionContext | None = None
        self._event_state: EventState | None = None
        self._pending: dict[int, _Pending] = {}
        self._failures: deque[errors.MinecraftError] = deque()
        self._window = _MAX_WINDOW
        self._last_completed = 0
        self._reader = threading.Thread(
            target=self._receive, name=f"minebridge-receiver-{id(self):x}", daemon=True,
        )
        self._reader.start()

    @classmethod
    def connect(cls, ip: str = "localhost", port: int = 4711,
                timeout: float = 5.0) -> TcpTransport:
        timeout = _positive_timeout(timeout)
        if not isinstance(ip, str):
            raise TypeError("ip must be a nonempty host name or address")
        if not ip or "\x00" in ip:
            raise ValueError("ip must be a nonempty host name or address")
        if type(port) is not int:
            raise TypeError("port must be an integer")
        if not 1 <= port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        try:
            # OS DNS resolution is synchronous, outside the TCP-connect deadline.
            addresses = socket.getaddrinfo(ip, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
        except (OSError, UnicodeError):
            raise errors.ConnectionError("Cannot resolve TCP endpoint") from None
        deadline = time.monotonic() + timeout
        for family, kind, protocol, _, address in addresses:
            sock: socket.socket | None = None
            try:
                if time.monotonic() >= deadline:
                    raise _DeadlineExpired
                sock = socket.socket(family, kind, protocol)
                sock.setblocking(False)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                status = sock.connect_ex(address)
                if status not in (0, errno.EISCONN):
                    if status not in _CONNECTING:
                        raise OSError
                    _wait_ready(sock, read=False, deadline=deadline)
                    if sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR) != 0:
                        raise OSError
                return cls(sock, timeout)
            except _DeadlineExpired:
                if sock is not None:
                    sock.close()
                raise errors.OperationTimeoutError("TCP connection timed out") from None
            except (OSError, _ConnectionClosed):
                if sock is not None:
                    sock.close()
        raise errors.ConnectionError("Cannot establish TCP connection") from None

    @classmethod
    def connect_and_handshake(
        cls, ip: str = "localhost", port: int = 4711, *, token: str | None = None,
        world: str | None = None, timeout: float = 5.0, coordinates: str | None = None,
        logging: bool = False,
    ) -> TcpTransport:
        params = prepare_hello(token=token, world=world, coordinates=coordinates, logging=logging)
        transport = cls.connect(ip, port, timeout)
        try:
            response = transport.exchange("system.hello", params)
            assert response.result is not None
            context = context_from_result(response.result)
            if logging and "session.logging" not in context.capabilities:
                raise errors.UnsupportedFeatureError("Server does not support logging=True; update the Minebridge plugin")
            if world is not None and world not in (context.world.name, context.world.key):
                raise errors.ProtocolError("Unexpected handshake world")
            transport._context = context
            transport._event_state = EventState(context)
            # Remote metadata may be huge integers; it cannot enlarge local bounds.
            for limit in (context.limits.max_queued_requests, context.limits.max_output_frames):
                text = limit.text
                value = _MAX_WINDOW if len(text) > 3 else int(text)
                transport._window = min(transport._window, max(1, value))
            with _EXIT_LOCK:
                _EXIT_TRANSPORTS.add(transport)
            return transport
        except BaseException:
            transport.close()
            raise

    @property
    def context(self) -> SessionContext | None:
        return self._context

    @property
    def closed(self) -> bool:
        with self._condition:
            return self._socket is None

    def __repr__(self) -> str:
        return f"TcpTransport(closed={self.closed})"

    @staticmethod
    def _annotate(failure: errors.MinecraftError, pending: _Pending) -> errors.MinecraftError:
        failure.request_id = pending.request_id
        failure.method = pending.method
        failure.args = (f"{failure} [method={pending.method}, request_id={pending.request_id}, "
                        f"outcome={failure.outcome}]",)
        return failure

    def _terminate(self, exception_type: type[errors.MinecraftError], message: str) -> None:
        with self._condition:
            sock, self._socket = self._socket, None
            for pending in self._pending.values():
                outcome = "unknown" if pending.mutation and pending.possibly_sent else "not-applied"
                pending.failure = self._annotate(exception_type(message, outcome=outcome), pending)
                pending.done = True
                if pending.deferred:
                    self._failures.append(pending.failure)
                self._last_completed = pending.request_id
            self._pending.clear()
            self._condition.notify_all()
        if self._event_state is not None:
            self._event_state.fail(exception_type(message))
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            finally:
                sock.close()

    def close(self) -> None:
        """Abort immediately. The public facade uses finish() for graceful close."""
        with _EXIT_LOCK:
            _EXIT_TRANSPORTS.discard(self)
        if self._event_state is not None:
            self._event_state.local_close()
        self._terminate(errors.ConnectionError, "TCP connection is closed")
        if self._reader is not threading.current_thread():
            self._reader.join(0.5)

    def finish(self) -> None:
        """Drain then close, even if an operation failed. Serialize with submission."""
        with self._rpc_lock:
            try:
                self._flush_locked()
            finally:
                self.close()

    def _wait(self, sock: socket.socket, *, read: bool, deadline: float) -> None:
        while True:
            with self._condition:
                if self._socket is not sock:
                    raise _ConnectionClosed
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _DeadlineExpired
            try:
                readers, writers, exceptional = select.select(
                    [sock] if read else [], [] if read else [sock], [sock],
                    min(remaining, _POLL_SECONDS),
                )
            except ValueError:
                raise _ConnectionClosed from None
            if readers or writers or exceptional:
                if time.monotonic() >= deadline:
                    raise _DeadlineExpired
                return

    def _receive(self) -> None:
        decoder = FrameDecoder()
        try:
            while True:
                with self._condition:
                    sock = self._socket
                    if sock is None:
                        return
                    deadlines = [p.deadline for p in self._pending.values() if p.deadline is not None]
                now = time.monotonic()
                if deadlines and min(deadlines) <= now:
                    raise _DeadlineExpired
                delay = min(_POLL_SECONDS, min(deadlines) - now) if deadlines else _POLL_SECONDS
                readers, _, exceptional = select.select([sock], [], [sock], max(0, delay))
                if not readers and not exceptional:
                    continue
                try:
                    chunk = sock.recv(16384)
                except BlockingIOError:
                    continue
                if not chunk:
                    decoder.finish()
                    raise _ConnectionClosed
                frames = decoder.feed(chunk)
                with self._condition:
                    # Validate the entire received group before publishing any ACK.
                    waiting = list(self._pending.values())
                    state = self._event_state
                    streaming = state is not None and state.has_stream
                    if not waiting and not frames and not streaming:
                        raise CodecError("UNSOLICITED_RESPONSE")
                    replies = []
                    event_actions = []
                    progressed = False
                    for frame in frames:
                        notification = decode_event(frame)
                        if notification is not None:
                            if state is None:
                                raise CodecError("UNSOLICITED_RESPONSE")
                            event_actions.append(("notification", notification))
                            continue
                        index = len(replies)
                        if index >= len(waiting):
                            raise CodecError("UNSOLICITED_RESPONSE")
                        pending = waiting[index]
                        progress_id = decode_progress(frame)
                        if progress_id is not None:
                            if progress_id != pending.request_id or pending.method == "system.hello":
                                raise CodecError("INVALID_PROGRESS")
                            progressed = True
                        else:
                            response = decode_response(frame, pending.request_id, pending.method)
                            replies.append((pending, response))
                            if pending.method == "events.subscribe" and response.result is not None:
                                event_actions.append(("ack", (pending.subscription_id, response.result)))
                    if len(replies) == len(waiting) and not chunk.endswith(b"\n") and not streaming:
                        raise CodecError("UNSOLICITED_RESPONSE")
                    for action, value in event_actions:
                        assert state is not None
                        if action == "ack":
                            state.acknowledge(*value)
                        else:
                            state.receive(value)
                    if progressed:
                        # All queued RPCs wait behind the same live long-running head.
                        # Refresh inactivity, never claim the operation has completed.
                        refreshed = time.monotonic() + self._timeout
                        for pending in waiting:
                            if pending.deadline is not None:
                                pending.deadline = refreshed
                    fatal = False
                    for pending, response in replies:
                        pending.response = response
                        pending.done = True
                        if response.error is not None:
                            pending.failure = self._annotate(server_error_exception(response.error), pending)
                            if pending.deferred:
                                self._failures.append(pending.failure)
                            fatal = fatal or (pending.method == "system.hello"
                                              or response.error.numeric_code.text in _CLOSE_ERROR_NUMBERS)
                        del self._pending[pending.request_id]
                        self._last_completed = pending.request_id
                    self._condition.notify_all()
                if fatal:
                    self._terminate(errors.ConnectionError, "Server closed the session")
                    return
        except _DeadlineExpired:
            self._terminate(errors.OperationTimeoutError, "TCP operation timed out")
        except CodecError:
            self._terminate(errors.ProtocolError, "Invalid protocol response")
        except (OSError, ValueError, _ConnectionClosed):
            self._terminate(errors.ConnectionError, "TCP connection lost")

    def _raise_failures(self, through: int) -> None:
        # Caller holds the condition. Consume every error covered by this barrier.
        failures = []
        while self._failures and (self._failures[0].request_id or 0) <= through:
            failures.append(self._failures.popleft())
        if failures:
            first = failures[0]
            first.failures = tuple(failures)
            raise first from None

    def _flush_locked(self) -> None:
        with self._condition:
            target = self._next_id - 1
            while self._pending and self._last_completed < target:
                self._condition.wait(_POLL_SECONDS)
            self._raise_failures(target)

    def flush(self) -> None:
        """Wait for all preceding requests and surface deferred server failures."""
        with self._rpc_lock:
            self._flush_locked()

    def _send(self, method: str, params: Mapping[str, object], *,
              mutation: bool, deferred: bool) -> _Pending:
        if not isinstance(method, str) or not method:
            raise TypeError("method must be a nonempty string")
        if not isinstance(params, Mapping):
            raise TypeError("params must be a mapping")
        if type(mutation) is not bool:
            raise TypeError("mutation must be a boolean")
        if self._next_id > MAX_ID:
            self.close()
            raise errors.ProtocolError("Request ID range exhausted") from None
        with self._condition:
            if self._socket is None:
                raise errors.ConnectionError("TCP connection is closed") from None
            self._raise_failures(self._next_id - 1)
            request_id = self._next_id
            try:
                frame = encode_frame({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
            except CodecError:
                raise errors.ProtocolError("Cannot encode protocol request") from None
            while len(self._pending) >= self._window:
                self._condition.wait(_POLL_SECONDS)
                self._raise_failures(self._next_id - 1)
                if self._socket is None:
                    raise errors.ConnectionError("TCP connection is closed") from None
            pending = _Pending(request_id, method, mutation, deferred)
            if method == "events.subscribe":
                pending.subscription_id = params.get("subscriptionId")
            self._pending[request_id] = pending
            self._next_id += 1
            sock = self._socket
        deadline = time.monotonic() + self._timeout
        offset = 0
        try:
            while offset < len(frame):
                self._wait(sock, read=False, deadline=deadline)
                try:
                    with self._condition:
                        pending.possibly_sent = True
                    sent = sock.send(frame[offset:])
                except BlockingIOError:
                    continue
                if sent <= 0:
                    raise _ConnectionClosed
                offset += sent
            with self._condition:
                pending.deadline = time.monotonic() + self._timeout
                self._condition.notify_all()
        except _DeadlineExpired:
            self._terminate(errors.OperationTimeoutError, "TCP operation timed out")
        except (OSError, ValueError, _ConnectionClosed):
            self._terminate(errors.ConnectionError, "TCP connection lost")
        return pending

    def submit(self, method: str, params: Mapping[str, object], *, mutation: bool = True) -> None:
        """Send without a per-call ACK wait; the bounded window provides backpressure."""
        with self._rpc_lock:
            pending = self._send(method, params, mutation=mutation, deferred=True)
            if pending.done and pending.failure is not None:
                with self._condition:
                    self._raise_failures(pending.request_id)

    def exchange(self, method: str, params: Mapping[str, object], *, mutation: bool = False) -> Response:
        """A synchronous result/barrier; shares the same receiver as buffered writes."""
        with self._rpc_lock:
            self._flush_locked()
            pending = self._send(method, params, mutation=mutation, deferred=False)
            with self._condition:
                while not pending.done:
                    self._condition.wait(_POLL_SECONDS)
                if pending.failure is not None:
                    raise pending.failure from None
                assert pending.response is not None
                return pending.response
