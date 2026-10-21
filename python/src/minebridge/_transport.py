"""Private bounded TCP transport with an explicit optional hello entry point.

There is one synchronous RPC owner per connection. No reader thread, request
backlog, automatic reconnect or retry is created. DNS is resolved synchronously
by the operating system *before* the absolute TCP-connect deadline starts; this
deadline is not a bound on DNS resolution. All connect candidates then share
one deadline. Sending a frame and receiving its entire response have separate
absolute deadlines, so partial progress never renews either deadline.
"""

from __future__ import annotations

from collections.abc import Mapping
import errno
import math
import select
import socket
import threading
import time

from . import errors
from ._handshake import SessionContext, context_from_result, prepare_hello
from ._protocol import (
    CodecError,
    FrameDecoder,
    MAX_ID,
    Response,
    decode_response,
    encode_frame,
    server_error_exception,
)


_POLL_SECONDS = 0.05
_CONNECTING = frozenset(
    value for value in (
        errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY,
        getattr(errno, "WSAEWOULDBLOCK", None),
        getattr(errno, "WSAEINPROGRESS", None),
        getattr(errno, "WSAEALREADY", None),
    ) if value is not None
)
_CLOSE_ERROR_NUMBERS = frozenset({
    "-32700", "-32600", "-32001", "-32002", "-32003", "-32004",
})


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
    """Nonblocking sockets keep cross-thread close independent of RPC locks.

    Short select intervals also bound cancellation on platforms where closing a
    socket in another thread does not wake select. They do not renew deadlines.
    """
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


class TcpTransport:
    """Internal TCP connection with ascending IDs and one pending response.

    ``connect`` establishes TCP only. ``exchange`` does not imply READY state or
    perform hello. Domain services must mark potentially mutating operations
    with ``mutation=True`` to preserve their outcome after a connection failure.
    """

    def __init__(self, sock: socket.socket, timeout: float) -> None:
        self._socket: socket.socket | None = sock
        self._timeout = timeout
        self._rpc_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._next_id = 1
        self._context: SessionContext | None = None

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
            # No resolver thread: the OS resolver's duration is outside TCP's
            # deadline, including when ip is a host name rather than a literal.
            addresses = socket.getaddrinfo(
                ip, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP,
            )
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
                # There has not been an RPC, so no operation can be applied.
                raise errors.OperationTimeoutError(
                    "TCP connection timed out", outcome="not-applied",
                ) from None
            except (OSError, _ConnectionClosed):
                if sock is not None:
                    sock.close()
        raise errors.ConnectionError("Cannot establish TCP connection") from None

    @classmethod
    def connect_and_handshake(
        cls, ip: str = "localhost", port: int = 4711, *, token: str | None = None,
        world: str | None = None, timeout: float = 5.0,
        coordinates: str | None = None,
    ) -> TcpTransport:
        """Connect and negotiate protocol 1.0; not the public Minecraft facade.

        Missing credentials and unsupported local options fail before DNS/TCP.
        Failed negotiation always closes the new connection, without retries.
        """
        params = prepare_hello(token=token, world=world, coordinates=coordinates)
        transport = cls.connect(ip, port, timeout)
        try:
            response = transport.exchange("system.hello", params)
            # exchange's strict codec verifies the complete hello result.
            assert response.result is not None
            context = context_from_result(response.result)
            if world is not None and context.world.name != world:
                raise errors.ProtocolError("Unexpected handshake world") from None
            transport._context = context
            return transport
        except BaseException:
            transport.close()
            raise

    @property
    def context(self) -> SessionContext | None:
        """Negotiated immutable snapshot, retained as metadata after close.

        A TCP-only connection has no context. Its presence does not imply that
        the socket is still open; callers must handle normal transport failures.
        """
        return self._context

    @property
    def closed(self) -> bool:
        with self._state_lock:
            return self._socket is None

    def __repr__(self) -> str:
        return f"TcpTransport(closed={self.closed})"

    def close(self) -> None:
        """Idempotently close without acquiring the RPC lock or doing an RPC."""
        with self._state_lock:
            sock, self._socket = self._socket, None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            finally:
                sock.close()

    def _open_socket(self) -> socket.socket:
        with self._state_lock:
            sock = self._socket
        if sock is None:
            raise errors.ConnectionError("TCP connection is closed") from None
        return sock

    def _wait(self, sock: socket.socket, *, read: bool, deadline: float) -> None:
        while True:
            with self._state_lock:
                if self._socket is not sock:
                    raise _ConnectionClosed
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _DeadlineExpired
            # Checking ownership every short interval makes close bounded even
            # when the platform leaves select asleep after shutdown/close.
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

    @staticmethod
    def _check_idle(sock: socket.socket) -> None:
        """Refuse an already buffered unsolicited response before another RPC."""
        readers, _, _ = select.select([sock], [], [], 0)
        if readers:
            try:
                pending = sock.recv(1, socket.MSG_PEEK)
            except BlockingIOError:
                return
            if pending:
                raise CodecError("UNSOLICITED_RESPONSE")
            raise _ConnectionClosed

    def exchange(self, method: str, params: Mapping[str, object], *,
                 mutation: bool = False) -> Response:
        if not isinstance(method, str) or not method:
            raise TypeError("method must be a nonempty string")
        if not isinstance(params, Mapping):
            raise TypeError("params must be a mapping")
        if type(mutation) is not bool:
            raise TypeError("mutation must be a boolean")
        with self._rpc_lock:
            sock = self._open_socket()
            if self._next_id > MAX_ID:
                self.close()
                raise errors.ProtocolError("Request ID range exhausted") from None
            request_id = self._next_id
            # Encoding is complete before any request byte can be transmitted.
            # A local encoding failure leaves both the ID and connection usable.
            try:
                frame = encode_frame({
                    "jsonrpc": "2.0", "id": request_id,
                    "method": method, "params": params,
                })
            except CodecError:
                raise errors.ProtocolError("Cannot encode protocol request") from None
            possibly_sent = False
            try:
                self._check_idle(sock)
                deadline = time.monotonic() + self._timeout
                offset = 0
                while offset < len(frame):
                    self._wait(sock, read=False, deadline=deadline)
                    try:
                        # After a send is attempted, conservatively retain the
                        # possibility that some bytes reached the remote peer.
                        possibly_sent = True
                        sent = sock.send(frame[offset:])
                    except BlockingIOError:
                        continue
                    if sent <= 0:
                        raise _ConnectionClosed
                    offset += sent
                self._next_id += 1
                deadline = time.monotonic() + self._timeout
                decoder = FrameDecoder()
                while True:
                    self._wait(sock, read=True, deadline=deadline)
                    try:
                        chunk = sock.recv(4096)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        decoder.finish()
                        raise _ConnectionClosed
                    frames = decoder.feed(chunk)
                    if not frames:
                        continue
                    # No event-reader or inbound backlog exists. Trailing bytes
                    # are a second, unsolicited response, even without its LF.
                    if len(frames) != 1 or not chunk.endswith(b"\n"):
                        raise CodecError("UNSOLICITED_RESPONSE")
                    response = decode_response(frames[0], request_id, method)
                    break
            except _DeadlineExpired:
                self.close()
                raise errors.OperationTimeoutError(
                    "TCP operation timed out", outcome="unknown",
                ) from None
            except CodecError:
                self.close()
                raise errors.ProtocolError(
                    "Invalid protocol response",
                    outcome="unknown" if mutation and possibly_sent else "not-applied",
                ) from None
            except (OSError, ValueError, _ConnectionClosed):
                self.close()
                raise errors.ConnectionError(
                    "TCP connection lost",
                    outcome="unknown" if mutation and possibly_sent else "not-applied",
                ) from None
            if response.error is not None:
                if (method == "system.hello"
                        or response.error.numeric_code.text in _CLOSE_ERROR_NUMBERS):
                    self.close()
                raise server_error_exception(response.error) from None
            return response
