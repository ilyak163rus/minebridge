"""Public teaching API against controlled real TCP peers.

These tests verify what the caller can observe at the facade boundary. They
exercise the installed wheel and actual sockets, without replacing Paper's
world-state checks or claiming that a peer has applied a Minecraft mutation.
"""

import inspect
import threading
import time
import traceback
import unittest
from unittest import mock

from minebridge import block, errors
from minebridge._protocol import encode_frame
from minebridge.minecraft import Minecraft
from minebridge.models.blocks import BlockSpec, LegacyBlock
from test_handshake import EXAMPLE_TOKEN, hello_result
from test_transport import peer, read_request, result


def send_hello(connection, request, *, world="lesson-world"):
    connection.sendall(encode_frame({
        "jsonrpc": "2.0", "id": request["id"],
        "result": hello_result(world=world),
    }))


def acknowledge_operations(requests, *, world="lesson-world"):
    def handle(connection, stopping):
        hello = read_request(connection)
        requests.append(hello)
        send_hello(connection, hello, world=world)
        while not stopping.is_set():
            request = read_request(connection)
            if request is None:
                return
            requests.append(request)
            connection.sendall(result(request["id"]))
    return handle


class ClientTests(unittest.TestCase):
    def connect(self, server, **options):
        options.setdefault("token", EXAMPLE_TOKEN)
        options.setdefault("timeout", 1.0)
        client = Minecraft.create("127.0.0.1", server.port, **options)
        self.addCleanup(client.close)
        return client

    @staticmethod
    def start_call(call):
        completed = threading.Event()
        values, failures = [], []

        def run():
            try:
                values.append(call())
            except Exception as error:
                failures.append(error)
            finally:
                completed.set()

        thread = threading.Thread(target=run, name="t07-facade-call")
        thread.start()
        return thread, completed, values, failures

    def test_create_returns_only_after_successful_hello(self):
        hello_received, release = threading.Event(), threading.Event()
        requests = []

        def handle(connection, stopping):
            request = read_request(connection)
            requests.append(request)
            hello_received.set()
            if not release.wait(2):
                raise AssertionError("Test did not release hello")
            send_hello(connection, request)
            self.assertIsNone(read_request(connection))

        with peer(handle) as server:
            thread, completed, values, failures = self.start_call(
                lambda: self.connect(server),
            )
            try:
                self.assertTrue(hello_received.wait(1))
                self.assertFalse(completed.wait(0.05))
            finally:
                release.set()
                thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(failures, [])
            self.assertEqual(len(values), 1)
            self.assertIsInstance(values[0], Minecraft)
            self.assertEqual(requests, [{
                "jsonrpc": "2.0", "id": 1, "method": "system.hello",
                "params": {"protocol": {"major": 1, "minor": 0},
                           "token": EXAMPLE_TOKEN, "world": None,
                           "coordinates": "absolute"},
            }])
            values[0].close()

    def test_create_forwards_explicit_world_and_environment_token(self):
        requests = []
        with mock.patch.dict("os.environ", {"MINEBRIDGE_TOKEN": EXAMPLE_TOKEN}), \
                peer(acknowledge_operations(requests, world="my-world")) as server:
            client = self.connect(server, token=None, world="my-world",
                                  coordinates="absolute")
            self.assertIsNone(client.setBlock(0, 80, 0, 4))
            self.assertEqual(requests[0]["params"]["world"], "my-world")
            self.assertEqual(requests[0]["params"]["token"], EXAMPLE_TOKEN)
            self.assertEqual(requests[1]["params"]["world"], "my-world")
            client.close()

    def test_root_and_namespace_normalize_all_supported_block_inputs(self):
        requests = []
        inputs = (4, block.COBBLESTONE, "minecraft:cobblestone",
                  BlockSpec("minecraft:cobblestone"), LegacyBlock(4, 0))
        with peer(acknowledge_operations(requests)) as server:
            client = self.connect(server)
            for value in inputs:
                self.assertIsNone(client.setBlock(1.9, 80.8, -0.1, value))
                self.assertIsNone(client.blocks.setBlock(1.9, 80.8, -0.1, value))
            expected = {
                "world": "lesson-world", "position": [1, 80, -1],
                "block": {"key": "minecraft:cobblestone", "states": {}},
            }
            self.assertEqual(len(requests), 11)
            self.assertEqual([request["id"] for request in requests], list(range(1, 12)))
            for request in requests[1:]:
                self.assertEqual(request["method"], "blocks.set")
                self.assertEqual(request["params"], expected)
            client.close()

    def test_both_entry_points_wait_for_ack_and_return_none(self):
        # The transport remains synchronous through both public entry points.
        for use_namespace in (False, True):
            with self.subTest(namespace=use_namespace):
                received, release = threading.Event(), threading.Event()

                def handle(connection, stopping):
                    send_hello(connection, read_request(connection))
                    request = read_request(connection)
                    received.set()
                    if not release.wait(2):
                        raise AssertionError("Test did not release operation ACK")
                    connection.sendall(result(request["id"]))
                    self.assertIsNone(read_request(connection))

                with peer(handle) as server:
                    client = self.connect(server)
                    operation = client.blocks.setBlock if use_namespace else client.setBlock
                    thread, completed, values, failures = self.start_call(
                        lambda: operation(0, 80, 0, 4),
                    )
                    try:
                        self.assertTrue(received.wait(1))
                        self.assertFalse(completed.wait(0.05))
                    finally:
                        release.set()
                        thread.join(2)
                    self.assertFalse(thread.is_alive())
                    self.assertEqual(failures, [])
                    self.assertEqual(values, [None])
                    client.close()

    def test_local_invalid_arguments_do_not_send_or_consume_request_ids(self):
        requests = []
        invalid = (
            ((True, 80, 0, 4), {}, TypeError),
            ((0, float("nan"), 0, 4), {}, ValueError),
            ((0, float("inf"), 0, 4), {}, ValueError),
            ((2**31, 80, 0, 4), {}, ValueError),
            ((0, 80, 0, True), {}, TypeError),
            ((0, 80, 0, 4), {"data": True}, TypeError),
            ((0, 80, 0, 4), {"data": 1}, errors.UnsupportedLegacyBlockError),
            ((0, 80, 0, LegacyBlock(4, 1)), {}, errors.UnsupportedLegacyBlockError),
            ((0, 80, 0, block.COBBLESTONE), {"data": 1}, ValueError),
            ((0, 80, 0, "minecraft:stone"), {"data": 1}, ValueError),
            ((0, 80, 0, "stone"), {}, errors.InvalidBlockError),
            ((0, 80, 0, "minecraft:stone[axis=y]"), {}, errors.UnsupportedFeatureError),
            ((0, 80, 0, 4), {"player": "nobody"}, TypeError),
        )
        with peer(acknowledge_operations(requests)) as server:
            client = self.connect(server)
            for index, (args, kwargs, exception) in enumerate(invalid):
                operation = client.setBlock if index % 2 else client.blocks.setBlock
                with self.subTest(index=index), self.assertRaises(exception):
                    operation(*args, **kwargs)
            self.assertIsNone(client.setBlock(0, 80, 0, 1, data=0))
            self.assertEqual([request["id"] for request in requests], [1, 2])
            self.assertEqual(requests[1]["params"]["block"]["key"], "minecraft:stone")
            client.close()

    def test_signature_rejects_unknown_create_kwargs_before_connection(self):
        parameters = inspect.signature(Minecraft.create).parameters
        self.assertEqual(tuple(parameters),
                         ("ip", "port", "token", "world", "timeout", "coordinates"))
        for name in ("token", "world", "timeout", "coordinates"):
            self.assertEqual(parameters[name].kind, inspect.Parameter.KEYWORD_ONLY)
        with mock.patch("socket.getaddrinfo") as resolve:
            for option in ("player", "pairingCode", "project", "withContext"):
                with self.subTest(option=option), self.assertRaises(TypeError):
                    Minecraft.create(**{option: "unsupported"})
            with self.assertRaises(TypeError):
                Minecraft.create("127.0.0.1", 4711, EXAMPLE_TOKEN)
            resolve.assert_not_called()

    def test_create_missing_credentials_and_unsupported_profile_fail_before_dns(self):
        with mock.patch.dict("os.environ", {}, clear=True), \
                mock.patch("socket.getaddrinfo") as resolve:
            with self.assertRaises(errors.AuthenticationError) as missing:
                Minecraft.create()
            self.assertEqual(missing.exception.outcome, "not-applied")
            with self.assertRaises(errors.UnsupportedFeatureError):
                Minecraft.create(token=EXAMPLE_TOKEN, coordinates="relative")
            resolve.assert_not_called()

    def test_failed_hello_never_returns_a_facade_or_sends_a_game_request(self):
        requests, closed = [], threading.Event()

        def handle(connection, stopping):
            request = read_request(connection)
            requests.append(request)
            connection.sendall(encode_frame({
                "jsonrpc": "2.0", "id": request["id"],
                "error": {"code": -32001, "message": EXAMPLE_TOKEN,
                          "data": {"code": "AUTH_FAILED", "outcome": "not-applied"}},
            }))
            if read_request(connection) is None:
                closed.set()

        with peer(handle) as server:
            with self.assertRaises(errors.AuthenticationError) as caught:
                self.connect(server)
            self.assertEqual(caught.exception.code, "AUTH_FAILED")
            self.assertEqual(caught.exception.outcome, "not-applied")
            self.assertNotIn(EXAMPLE_TOKEN, "".join(traceback.format_exception(caught.exception)))
            self.assertTrue(closed.wait(1))
            self.assertEqual(len(requests), 1)

    def test_domain_error_is_typed_without_retry_and_next_operation_is_usable(self):
        requests = []

        def handle(connection, stopping):
            send_hello(connection, read_request(connection))
            request = read_request(connection)
            requests.append(request)
            connection.sendall(encode_frame({
                "jsonrpc": "2.0", "id": request["id"],
                "error": {"code": -32024, "message": EXAMPLE_TOKEN,
                          "data": {"code": "INVALID_BLOCK", "outcome": "not-applied"}},
            }))
            request = read_request(connection)
            requests.append(request)
            connection.sendall(result(request["id"]))
            self.assertIsNone(read_request(connection))

        with peer(handle) as server:
            client = self.connect(server)
            with self.assertRaises(errors.InvalidBlockError) as caught:
                client.setBlock(0, 80, 0, "minecraft:missing_material")
            self.assertEqual(caught.exception.code, "INVALID_BLOCK")
            self.assertEqual(caught.exception.outcome, "not-applied")
            self.assertNotIn(EXAMPLE_TOKEN, str(caught.exception))
            self.assertIsNone(client.blocks.setBlock(0, 80, 0, 4))
            self.assertEqual([request["id"] for request in requests], [2, 3])
            client.close()

    def assert_mutation_failure(self, reply, expected):
        requests = []

        def handle(connection, stopping):
            send_hello(connection, read_request(connection))
            request = read_request(connection)
            requests.append(request)
            if reply is not None:
                connection.sendall(reply(request))

        with peer(handle) as server:
            client = self.connect(server)
            with self.assertRaises(expected) as caught:
                client.setBlock(0, 80, 0, 4)
            self.assertEqual(caught.exception.outcome, "unknown")
            with self.assertRaises(errors.ConnectionError) as closed:
                client.blocks.setBlock(0, 80, 0, 4)
            self.assertEqual(closed.exception.outcome, "not-applied")
            self.assertEqual(len(requests), 1)
        return caught.exception

    def test_wrong_response_id_closes_and_preserves_unknown_mutation_outcome(self):
        self.assert_mutation_failure(lambda request: result(request["id"] + 1),
                                     errors.ProtocolError)

    def test_eof_after_request_closes_and_preserves_unknown_mutation_outcome(self):
        self.assert_mutation_failure(None, errors.ConnectionError)

    def test_false_applied_ack_is_not_reported_as_success(self):
        self.assert_mutation_failure(lambda request: result(request["id"], applied=False),
                                     errors.ProtocolError)

    def test_response_timeout_discards_late_ack_without_retry(self):
        requests, release, closed = [], threading.Event(), threading.Event()

        def handle(connection, stopping):
            send_hello(connection, read_request(connection))
            request = read_request(connection)
            requests.append(request)
            if not release.wait(2):
                raise AssertionError("Test did not release late ACK")
            try:
                connection.sendall(result(request["id"]))
                if read_request(connection) is None:
                    closed.set()
            except OSError:
                closed.set()

        with peer(handle) as server:
            client = self.connect(server, timeout=0.15)
            try:
                with self.assertRaises(errors.OperationTimeoutError) as caught:
                    client.setBlock(0, 80, 0, 4)
                self.assertEqual(caught.exception.code, "TIMEOUT")
                self.assertEqual(caught.exception.outcome, "unknown")
                with self.assertRaises(errors.ConnectionError) as later:
                    client.setBlock(0, 80, 0, 4)
                self.assertEqual(later.exception.outcome, "not-applied")
            finally:
                release.set()
            self.assertTrue(closed.wait(1))
            self.assertEqual(len(requests), 1)

    def test_close_interrupts_pending_operation_without_waiting_for_rpc_lock(self):
        received, closed = threading.Event(), threading.Event()

        def handle(connection, stopping):
            send_hello(connection, read_request(connection))
            self.assertEqual(read_request(connection)["method"], "blocks.set")
            received.set()
            if read_request(connection) is None:
                closed.set()

        with peer(handle) as server:
            client = self.connect(server, timeout=5)
            thread, completed, values, failures = self.start_call(
                lambda: client.setBlock(0, 80, 0, 4),
            )
            try:
                self.assertTrue(received.wait(1))
                before = time.monotonic()
                self.assertIsNone(client.close())
                self.assertLess(time.monotonic() - before, 0.5)
                self.assertTrue(completed.wait(1))
            finally:
                client.close()
                thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(values, [])
            self.assertEqual(len(failures), 1)
            self.assertIsInstance(failures[0], errors.ConnectionError)
            self.assertEqual(failures[0].outcome, "unknown")
            self.assertTrue(closed.wait(1))

    def test_close_is_idempotent_and_sends_no_close_rpc(self):
        requests, closed = [], threading.Event()

        def handle(connection, stopping):
            request = read_request(connection)
            requests.append(request)
            send_hello(connection, request)
            if read_request(connection) is None:
                closed.set()

        with peer(handle) as server:
            client = self.connect(server)
            for _ in range(3):
                self.assertIsNone(client.close())
            self.assertTrue(closed.wait(1))
            with self.assertRaises(errors.ConnectionError) as caught:
                client.setBlock(0, 80, 0, 4)
            self.assertEqual(caught.exception.outcome, "not-applied")
            self.assertEqual(len(requests), 1)

    def test_two_facades_have_independent_connections_ids_and_close(self):
        requests, lock = {}, threading.Lock()
        both_operations = threading.Barrier(2)

        def handle(connection, stopping):
            hello = read_request(connection)
            world = hello["params"]["world"]
            with lock:
                requests[world] = [hello]
            send_hello(connection, hello, world=world)
            request = read_request(connection)
            requests[world].append(request)
            both_operations.wait(2)
            connection.sendall(result(request["id"]))
            while not stopping.is_set():
                request = read_request(connection)
                if request is None:
                    return
                requests[world].append(request)
                connection.sendall(result(request["id"]))

        with peer(handle) as server:
            first = self.connect(server, world="first-world")
            second = self.connect(server, world="second-world")
            calls = [self.start_call(lambda: first.setBlock(0, 80, 0, 4)),
                     self.start_call(lambda: second.blocks.setBlock(0, 80, 0, 4))]
            for thread, completed, values, failures in calls:
                thread.join(2)
                self.assertFalse(thread.is_alive())
                self.assertEqual(failures, [])
                self.assertEqual(values, [None])
            first.close()
            self.assertIsNone(second.setBlock(1, 80, 0, 4))
            self.assertEqual([request["id"] for request in requests["first-world"]], [1, 2])
            self.assertEqual([request["id"] for request in requests["second-world"]], [1, 2, 3])
            for world, recorded in requests.items():
                for request in recorded[1:]:
                    self.assertEqual(request["params"]["world"], world)
            second.close()


if __name__ == "__main__":
    unittest.main()
