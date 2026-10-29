"""Exercise the installed transport against real, controlled loopback peers.

These peers are test fixtures, not production echo methods or a Paper substitute.
"""

from contextlib import contextmanager
import errno
import json
import select
import socket
import subprocess
import sys
import threading
import time
import traceback
import unittest
from unittest import mock

from minebridge import errors
from minebridge._protocol import MAX_FRAME_BYTES, MAX_ID
from minebridge._transport import TcpTransport


BLOCK_PARAMS = {
    "world": "world", "position": [0, 80, 0],
    "block": {"key": "minecraft:stone", "states": {}},
}


def read_request(connection):
    data = bytearray()
    while len(data) <= MAX_FRAME_BYTES:
        byte = connection.recv(1)
        if not byte:
            return None
        if byte == b"\n":
            return json.loads(data.decode("utf-8"))
        data.extend(byte)
    raise AssertionError("Test peer received an oversized frame")


def result(request_id, **extra):
    return json.dumps({
        "jsonrpc": "2.0", "id": request_id,
        "result": {"applied": True, **extra},
    }, ensure_ascii=False).encode("utf-8") + b"\n"


def saturate_send_buffer(transport):
    """Establish real TCP backpressure without depending on OS buffer defaults."""
    sock = transport._socket
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024)
    until = time.monotonic() + 2
    filled = 0
    while time.monotonic() < until and filled < 8 * 1024 * 1024:
        try:
            filled += sock.send(b"x" * 16384)
        except BlockingIOError:
            _, writable, _ = select.select([], [sock], [], 0.05)
            if not writable:
                return
    raise AssertionError("Could not establish test TCP backpressure")


class LoopbackPeer:
    def __init__(self, handler, *, receive_buffer=None):
        self._handler = handler
        self._stopping = threading.Event()
        self._connections = []
        self._workers = []
        self.errors = []
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if receive_buffer is not None:
            self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, receive_buffer)
        self.listener.bind(("127.0.0.1", 0))
        self.port = self.listener.getsockname()[1]
        self.listener.listen(8)
        self.listener.settimeout(0.1)
        self.thread = threading.Thread(target=self._accept, name="t04-test-accept")
        self.thread.start()

    def _accept(self):
        while not self._stopping.is_set():
            try:
                connection, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            connection.settimeout(3)
            self._connections.append(connection)
            worker = threading.Thread(
                target=self._serve, args=(connection,), name="t04-test-peer",
            )
            self._workers.append(worker)
            worker.start()

    def _serve(self, connection):
        try:
            self._handler(connection, self._stopping)
        except Exception as error:
            if not self._stopping.is_set():
                self.errors.append(error)
        finally:
            connection.close()

    def close(self):
        self._stopping.set()
        self.listener.close()
        self.thread.join(2)
        for connection in self._connections:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()
        for worker in self._workers:
            worker.join(2)
        if self.thread.is_alive() or any(worker.is_alive() for worker in self._workers):
            raise AssertionError("Test peer did not stop")
        if self.errors:
            raise AssertionError(f"Test peer failed: {type(self.errors[0]).__name__}") from self.errors[0]


@contextmanager
def peer(handler, *, receive_buffer=None):
    server = LoopbackPeer(handler, receive_buffer=receive_buffer)
    try:
        yield server
    finally:
        server.close()


def echo_results(connection, stopping):
    while not stopping.is_set():
        request = read_request(connection)
        if request is None:
            return
        connection.sendall(result(request["id"]))


class TransportTests(unittest.TestCase):
    def connect(self, server, timeout=1.0):
        transport = TcpTransport.connect("127.0.0.1", server.port, timeout)
        self.addCleanup(transport.close)
        return transport

    def exchange(self, transport, *, mutation=True):
        return transport.exchange("blocks.set", BLOCK_PARAMS, mutation=mutation)

    def assert_failure(self, frame, exception=errors.ProtocolError, *, outcome="unknown"):
        requests = []

        def handler(connection, stopping):
            requests.append(read_request(connection))
            if frame:
                connection.sendall(frame)

        with peer(handler) as server:
            transport = self.connect(server)
            with self.assertRaises(exception) as caught:
                self.exchange(transport)
            self.assertEqual(caught.exception.outcome, outcome)
            self.assertTrue(transport.closed)
            self.assertEqual(len(requests), 1)
            with self.assertRaises(errors.ConnectionError) as closed:
                self.exchange(transport)
            self.assertEqual(closed.exception.outcome, "not-applied")
        return caught.exception

    def test_fragmented_unicode_crlf_response(self):
        expected = "Камень 🧱"

        def handler(connection, stopping):
            request = read_request(connection)
            frame = result(request["id"], note=expected)[:-1] + b"\r\n"
            # Every UTF-8 codepoint and CRLF boundary is split by real sends.
            for byte in frame:
                connection.sendall(bytes([byte]))

        with peer(handler) as server:
            transport = self.connect(server)
            response = self.exchange(transport)
            self.assertEqual(response.request_id, 1)
            self.assertEqual(response.result["note"], expected)

    def test_two_instances_have_independent_ids_and_sockets(self):
        requests = []
        both_connected = threading.Barrier(2)

        def handler(connection, stopping):
            request = read_request(connection)
            requests.append(request)
            both_connected.wait(2)
            connection.sendall(result(request["id"]))
            # Keep B genuinely live while the test closes A. The receiver now
            # detects an idle peer's EOF proactively instead of on the next RPC.
            self.assertIsNone(read_request(connection))

        with peer(handler) as server:
            first, second = self.connect(server), self.connect(server)
            responses, failures = [], []

            def run(transport):
                try:
                    responses.append(self.exchange(transport))
                except Exception as error:
                    failures.append(error)

            threads = [threading.Thread(target=run, args=(transport,))
                       for transport in (first, second)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(2)
            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(failures, [])
            self.assertEqual([request["id"] for request in requests], [1, 1])
            self.assertEqual([response.request_id for response in responses], [1, 1])
            first.close()
            self.assertFalse(second.closed)

    def test_concurrent_calls_are_serialized_and_ids_ascend(self):
        request_ids = []

        def handler(connection, stopping):
            for _ in range(12):
                request = read_request(connection)
                request_ids.append(request["id"])
                # A second request may not be transmitted before this reply.
                readable, _, _ = select.select([connection], [], [], 0.01)
                if readable:
                    raise AssertionError("Pipelined request on single-RPC connection")
                connection.sendall(result(request["id"]))

        with peer(handler) as server:
            transport = self.connect(server)
            responses, failures = [], []
            barrier = threading.Barrier(12)

            def run():
                try:
                    barrier.wait(2)
                    responses.append(self.exchange(transport).request_id)
                except Exception as error:
                    failures.append(error)

            threads = [threading.Thread(target=run) for _ in range(12)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(3)
            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(failures, [])
            self.assertEqual(request_ids, list(range(1, 13)))
            self.assertEqual(sorted(responses), list(range(1, 13)))

    def test_wrong_id_closes_without_retry(self):
        self.assert_failure(result(2))

    def test_invalid_json_closes_without_retry(self):
        self.assert_failure(b'{"id": 1,\n')

    def test_invalid_utf8_closes_without_retry(self):
        self.assert_failure(b'\xff\n')

    def test_malformed_result_closes_without_retry(self):
        self.assert_failure(b'{"jsonrpc":"2.0","id":1,"result":{"applied":false}}\n')

    def test_oversized_frame_closes_without_retry(self):
        self.assert_failure(b" " * (MAX_FRAME_BYTES + 1) + b"\n")

    def test_partial_eof_is_protocol_error(self):
        self.assert_failure(result(1)[:-1])

    def test_clean_eof_is_connection_error(self):
        error = self.assert_failure(b"", errors.ConnectionError)
        self.assertEqual(error.code, "CONNECTION_LOST")

    def test_complete_extra_response_is_rejected(self):
        self.assert_failure(result(1) + result(2))

    def test_partial_extra_response_is_rejected(self):
        self.assert_failure(result(1) + b'{"jsonrpc":')

    def test_failure_after_nonmutation_is_not_applied(self):
        def handler(connection, stopping):
            read_request(connection)
            connection.sendall(result(99))

        with peer(handler) as server:
            transport = self.connect(server)
            with self.assertRaises(errors.ProtocolError) as caught:
                self.exchange(transport, mutation=False)
            self.assertEqual(caught.exception.outcome, "not-applied")

    def test_unknown_server_error_is_safe_and_keeps_connection(self):
        secret = "EXAMPLE-PEER-MESSAGE-MUST-NOT-LEAK"

        def handler(connection, stopping):
            request = read_request(connection)
            connection.sendall(json.dumps({
                "jsonrpc": "2.0", "id": request["id"], "error": {
                    "code": -32199, "message": secret,
                    "data": {"code": "FUTURE_ERROR", "outcome": "unknown"},
                },
            }).encode() + b"\n")
            request = read_request(connection)
            connection.sendall(result(request["id"]))

        with peer(handler) as server:
            transport = self.connect(server)
            try:
                self.exchange(transport)
            except errors.MinecraftError as error:
                self.assertIs(type(error), errors.MinecraftError)
                self.assertEqual(error.code, "FUTURE_ERROR")
                self.assertEqual(error.outcome, "unknown")
                rendered = "".join(traceback.format_exception(error))
                self.assertNotIn(secret, rendered + repr(error) + repr(transport))
            else:
                self.fail("Expected server error")
            self.assertFalse(transport.closed)
            self.assertEqual(self.exchange(transport).request_id, 2)

    def test_known_server_error_is_typed_and_keeps_connection(self):
        def handler(connection, stopping):
            request = read_request(connection)
            connection.sendall(json.dumps({
                "jsonrpc": "2.0", "id": request["id"], "error": {
                    "code": -32023, "message": "Chunk unavailable",
                    "data": {"code": "CHUNK_NOT_LOADED", "outcome": "not-applied"},
                },
            }).encode() + b"\n")
            request = read_request(connection)
            connection.sendall(result(request["id"]))

        with peer(handler) as server:
            transport = self.connect(server)
            with self.assertRaises(errors.ChunkNotLoadedError) as caught:
                self.exchange(transport)
            self.assertEqual(caught.exception.outcome, "not-applied")
            self.assertFalse(transport.closed)
            self.assertEqual(self.exchange(transport).request_id, 2)

    def test_fatal_server_error_closes_connection(self):
        frame = json.dumps({
            "jsonrpc": "2.0", "id": 1, "error": {
                "code": -32003, "message": "Hello required",
                "data": {"code": "NOT_READY", "outcome": "not-applied"},
            },
        }).encode() + b"\n"
        self.assert_failure(frame, errors.ProtocolError, outcome="not-applied")

    def test_peer_content_does_not_leak_from_parse_failure(self):
        secret = "EXAMPLE-TOKEN-NOT-IN-TRACEBACK"
        error = self.assert_failure(('{"token":"' + secret + '"}\n').encode())
        self.assertNotIn(secret, "".join(traceback.format_exception(error)))
        self.assertNotIn(secret, repr(error))
        self.assertTrue(error.__suppress_context__)

    def test_encoding_error_sends_nothing_and_preserves_next_id(self):
        seen = []

        def handler(connection, stopping):
            request = read_request(connection)
            seen.append(request)
            connection.sendall(result(request["id"]))

        with peer(handler) as server:
            transport = self.connect(server)
            for invalid in ({"token": object()}, {"token": "x" * MAX_FRAME_BYTES}):
                with self.assertRaises(errors.ProtocolError) as caught:
                    transport.exchange("blocks.set", invalid, mutation=True)
                self.assertEqual(caught.exception.outcome, "not-applied")
                self.assertFalse(transport.closed)
            self.assertEqual(self.exchange(transport).request_id, 1)
            self.assertEqual([request["id"] for request in seen], [1])

    def test_id_exhaustion_sends_no_request_and_closes(self):
        def handler(connection, stopping):
            self.assertIsNone(read_request(connection))

        with peer(handler) as server:
            transport = self.connect(server)
            transport._next_id = MAX_ID + 1
            with self.assertRaises(errors.ProtocolError) as caught:
                self.exchange(transport)
            self.assertEqual(caught.exception.outcome, "not-applied")
            self.assertTrue(transport.closed)

    def test_close_is_idempotent_and_exchange_after_close_is_not_applied(self):
        with peer(echo_results) as server:
            transport = self.connect(server)
            transport.close()
            transport.close()
            self.assertTrue(transport.closed)
            with self.assertRaises(errors.ConnectionError) as caught:
                self.exchange(transport)
            self.assertEqual(caught.exception.outcome, "not-applied")
            self.assertEqual(repr(transport), "TcpTransport(closed=True)")

    def test_close_interrupts_blocked_read_without_waiting_for_rpc_lock(self):
        received = threading.Event()

        def handler(connection, stopping):
            read_request(connection)
            received.set()
            stopping.wait(3)

        with peer(handler) as server:
            transport = self.connect(server, timeout=30)
            failures = []

            def run():
                try:
                    self.exchange(transport)
                except Exception as error:
                    failures.append(error)

            worker = threading.Thread(target=run)
            worker.start()
            self.assertTrue(received.wait(2))
            start = time.monotonic()
            transport.close()
            worker.join(1)
            self.assertFalse(worker.is_alive())
            self.assertLess(time.monotonic() - start, 1)
            self.assertEqual(len(failures), 1)
            self.assertIsInstance(failures[0], errors.ConnectionError)
            self.assertEqual(failures[0].outcome, "unknown")

    def test_close_interrupts_blocked_write_without_waiting_for_rpc_lock(self):
        accepted = threading.Event()

        def handler(connection, stopping):
            accepted.set()
            stopping.wait(3)

        with peer(handler, receive_buffer=1024) as server:
            transport = self.connect(server, timeout=30)
            self.assertTrue(accepted.wait(2))
            # Fault setup fills real TCP buffers while the peer does not read.
            # This does not rely on a 64-KiB request exceeding OS buffer sizes.
            saturate_send_buffer(transport)
            waiting = threading.Event()
            original_wait = transport._wait

            def observe_wait(sock, *, read, deadline):
                if not read:
                    waiting.set()
                return original_wait(sock, read=read, deadline=deadline)

            transport._wait = observe_wait
            failures = []

            def run():
                try:
                    self.exchange(transport)
                except Exception as error:
                    failures.append(error)

            worker = threading.Thread(target=run)
            worker.start()
            self.assertTrue(waiting.wait(2))
            start = time.monotonic()
            transport.close()
            worker.join(1)
            self.assertFalse(worker.is_alive())
            self.assertLess(time.monotonic() - start, 1)
            self.assertEqual(len(failures), 1)
            self.assertIsInstance(failures[0], errors.ConnectionError)

    def test_saturated_write_has_an_absolute_timeout(self):
        accepted = threading.Event()

        def handler(connection, stopping):
            accepted.set()
            stopping.wait(3)

        with peer(handler, receive_buffer=1024) as server:
            transport = self.connect(server, timeout=0.18)
            self.assertTrue(accepted.wait(2))
            saturate_send_buffer(transport)
            wait_phases = []
            original_wait = transport._wait

            def observe_wait(sock, *, read, deadline):
                wait_phases.append(read)
                return original_wait(sock, read=read, deadline=deadline)

            transport._wait = observe_wait
            start = time.monotonic()
            with self.assertRaises(errors.OperationTimeoutError) as caught:
                self.exchange(transport)
            duration = time.monotonic() - start
            self.assertEqual(caught.exception.code, "TIMEOUT")
            # The prefilled socket never became writable: no byte of this RPC
            # was attempted, so its world mutation is known not to be applied.
            self.assertEqual(caught.exception.outcome, "not-applied")
            self.assertTrue(transport.closed)
            self.assertGreaterEqual(duration, 0.13)
            self.assertLess(duration, 1)
            self.assertTrue(wait_phases)
            self.assertFalse(any(wait_phases), "Test must expire sending, not reading")

    def test_slow_drip_does_not_renew_whole_response_deadline(self):
        requests = []

        def handler(connection, stopping):
            requests.append(read_request(connection))
            for byte in result(1):
                try:
                    connection.sendall(bytes([byte]))
                except OSError:
                    return
                if stopping.wait(0.04):
                    return

        with peer(handler) as server:
            transport = self.connect(server, timeout=0.18)
            start = time.monotonic()
            with self.assertRaises(errors.OperationTimeoutError) as caught:
                self.exchange(transport)
            duration = time.monotonic() - start
            self.assertEqual(caught.exception.code, "TIMEOUT")
            self.assertEqual(caught.exception.outcome, "unknown")
            self.assertGreaterEqual(duration, 0.13)
            self.assertLess(duration, 1)
            self.assertTrue(transport.closed)
            self.assertEqual(len(requests), 1)

    def test_timeout_closes_and_never_resends_or_consumes_a_late_reply(self):
        requests = []

        def handler(connection, stopping):
            requests.append(read_request(connection))
            if not stopping.wait(0.3):
                try:
                    connection.sendall(result(1))
                except OSError:
                    pass

        with peer(handler) as server:
            transport = self.connect(server, timeout=0.1)
            with self.assertRaises(errors.OperationTimeoutError):
                self.exchange(transport)
            with self.assertRaises(errors.ConnectionError):
                self.exchange(transport)
            self.assertEqual(len(requests), 1)

    def test_invalid_connection_arguments_do_not_resolve_or_open_sockets(self):
        invalid = [
            ({"timeout": True}, TypeError), ({"timeout": "1"}, TypeError),
            ({"timeout": None}, TypeError), ({"timeout": 0}, ValueError),
            ({"timeout": -1}, ValueError), ({"timeout": float("nan")}, ValueError),
            ({"timeout": float("inf")}, ValueError), ({"timeout": 10 ** 1000}, ValueError),
            ({"ip": 42}, TypeError), ({"ip": ""}, ValueError),
            ({"ip": "x\x00y"}, ValueError), ({"port": True}, TypeError),
            ({"port": 1.0}, TypeError), ({"port": 0}, ValueError),
            ({"port": 65536}, ValueError),
        ]
        with mock.patch("socket.getaddrinfo") as resolver, mock.patch("socket.socket") as factory:
            for arguments, exception in invalid:
                with self.subTest(arguments=arguments), self.assertRaises(exception):
                    TcpTransport.connect(**arguments)
            resolver.assert_not_called()
            factory.assert_not_called()

    def test_invalid_exchange_arguments_leave_connection_usable(self):
        with peer(echo_results) as server:
            transport = self.connect(server)
            invalid = [
                (("", {}), {}, TypeError), ((None, {}), {}, TypeError),
                (("blocks.set", []), {}, TypeError),
                (("blocks.set", {}), {"mutation": 1}, TypeError),
            ]
            for arguments, options, exception in invalid:
                with self.subTest(arguments=arguments), self.assertRaises(exception):
                    transport.exchange(*arguments, **options)
            self.assertEqual(self.exchange(transport).request_id, 1)

    def test_connection_refusal_is_safe_and_not_applied(self):
        with socket.socket() as reserved:
            reserved.bind(("127.0.0.1", 0))
            port = reserved.getsockname()[1]
            # Bound but not listening: no port allocation race with another peer.
            with self.assertRaises(errors.ConnectionError) as caught:
                # On Windows a refused nonblocking connect can remain pending
                # for about two seconds before select reports WSAECONNREFUSED.
                TcpTransport.connect("127.0.0.1", port, 4)
        self.assertEqual(caught.exception.code, "CONNECTION_LOST")
        self.assertEqual(caught.exception.outcome, "not-applied")
        self.assertNotIn(str(port), repr(caught.exception))
        self.assertTrue(caught.exception.__suppress_context__)

    def test_resolution_failure_is_safe_and_not_applied(self):
        secret = "EXAMPLE-RESOLVER-DETAIL-NOT-IN-TRACEBACK"
        with mock.patch("socket.getaddrinfo", side_effect=socket.gaierror(secret)):
            with self.assertRaises(errors.ConnectionError) as caught:
                TcpTransport.connect()
        self.assertEqual(caught.exception.outcome, "not-applied")
        self.assertNotIn(secret, "".join(traceback.format_exception(caught.exception)))

    def test_hostname_uses_real_loopback_resolution(self):
        with peer(echo_results) as server:
            # Exercise the public default timeout. A resolver may return ::1
            # first while this controlled peer listens only on IPv4; Windows
            # can spend about two seconds rejecting that first candidate.
            transport = TcpTransport.connect("localhost", server.port)
            self.addCleanup(transport.close)
            self.assertEqual(self.exchange(transport).request_id, 1)

    def test_connect_candidates_share_one_absolute_deadline(self):
        # External network schedule: each candidate finishes after 0.6 seconds.
        # The first refuses, the second would succeed at 1.2 seconds. With a
        # single 1-second connect budget, the second must expire at 1.0 seconds.
        # Simulating readiness and time avoids OS-specific refusal delays.
        now = [0.0]
        created = []

        class CandidateSocket:
            def __init__(self, status):
                self.status = status
                self.ready_at = None
                self.closed = False

            def setblocking(self, blocking):
                pass

            def setsockopt(self, level, option, value):
                pass

            def connect_ex(self, address):
                self.ready_at = now[0] + 0.6
                return errno.EINPROGRESS

            def getsockopt(self, level, option):
                return self.status

            def close(self):
                self.closed = True

        def create_socket(*args):
            candidate = CandidateSocket(errno.ECONNREFUSED if not created else 0)
            created.append(candidate)
            return candidate

        def wait(readers, writers, exceptional, timeout):
            candidate = writers[0]
            if candidate.ready_at <= now[0] + timeout:
                now[0] = candidate.ready_at
                return [], [candidate], []
            now[0] += timeout
            return [], [], []

        addresses = [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (host, 4711))
            for host in ("192.0.2.1", "192.0.2.2")
        ]
        with (
            mock.patch("minebridge._transport.socket.getaddrinfo", return_value=addresses),
            mock.patch("minebridge._transport.socket.socket", side_effect=create_socket),
            mock.patch("minebridge._transport.select.select", side_effect=wait),
            mock.patch("minebridge._transport.time.monotonic", side_effect=lambda: now[0]),
        ):
            with self.assertRaises(errors.OperationTimeoutError) as caught:
                TcpTransport.connect("example.invalid", 4711, 1)
        self.assertEqual(caught.exception.code, "TIMEOUT")
        self.assertEqual(caught.exception.outcome, "not-applied")
        self.assertEqual(len(created), 2)
        self.assertTrue(all(candidate.closed for candidate in created))
        self.assertAlmostEqual(now[0], 1.0)

    def test_repeated_connections_leave_no_transport_threads(self):
        before = {thread.ident for thread in threading.enumerate()}
        with peer(echo_results) as server:
            for _ in range(20):
                transport = self.connect(server)
                self.assertEqual(self.exchange(transport).request_id, 1)
                transport.close()
        after = {thread.ident for thread in threading.enumerate()}
        self.assertEqual(after, before)

    def test_import_opens_no_socket_and_does_not_resolve(self):
        probe = """
import socket
def forbidden(*args, **kwargs):
    raise AssertionError('Networking during import')
socket.socket = forbidden
socket.getaddrinfo = forbidden
import minebridge._transport
"""
        completed = subprocess.run(
            [sys.executable, "-I", "-c", probe], capture_output=True,
            text=True, timeout=5,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
