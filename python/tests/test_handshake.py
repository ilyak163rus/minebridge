"""Private hello entry point against controlled real TCP peers, without Paper."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
import threading
import traceback
import unittest
from unittest import mock
import uuid

from minebridge import errors
from minebridge._protocol import JsonNumber, MAX_FRAME_BYTES, MAX_JSON_DEPTH, encode_frame
from minebridge._transport import TcpTransport
from test_transport import peer, read_request


EXAMPLE_TOKEN = "EXAMPLE-NOT-A-SECRET"


def hello_result(*, world="world", session_id=None):
    return {
        "protocol": {"major": 2, "minor": 0},
        "sessionId": session_id or str(uuid.uuid4()),
        "pluginVersion": "0.2.0-dev", "serverVersion": "26.2",
        "world": {
            "name": world, "key": "minecraft:overworld", "uuid": str(uuid.uuid4()),
            "minY": -64, "maxYExclusive": 320,
        },
        "coordinates": "absolute", "chunkPolicy": "loaded-only",
        "applyPhysics": True, "capabilities": ["blocks.set"],
        "limits": {
            "maxFrameBytes": 65536, "maxJsonDepth": 16, "maxSessions": 8,
            "maxQueuedRequests": 8, "maxOutputFrames": 8,
            "handshakeTimeoutSeconds": 5, "frameAssemblyTimeoutSeconds": 5,
            "writeTimeoutSeconds": 5, "maxOperationsPerTick": 32,
            "maxOperationsPerSessionPerTick": 4, "executorBudgetMillis": 2,
        },
    }


def successful_peer(requests, result=None):
    def handle(connection, stopping):
        request = read_request(connection)
        requests.append(request)
        connection.sendall(encode_frame({
            "jsonrpc": "2.0", "id": request["id"],
            "result": result if result is not None else hello_result(),
        }))
        # Keep the connection open so successful hello represents a usable TCP
        # session. No server-side mutation implementation is provided here.
        while not stopping.is_set() and connection.recv(1):
            pass
    return handle


class HandshakeTests(unittest.TestCase):
    def connect(self, server, **options):
        options.setdefault("token", EXAMPLE_TOKEN)
        transport = TcpTransport.connect_and_handshake(
            "127.0.0.1", server.port, **options,
        )
        self.addCleanup(transport.close)
        return transport

    def test_default_hello_has_exact_wire_options_and_immutable_context(self):
        requests = []
        result = hello_result()
        with peer(successful_peer(requests, result)) as server:
            transport = self.connect(server)
            context = transport.context
            self.assertFalse(transport.closed)
            self.assertEqual(requests, [{
                "jsonrpc": "2.0", "id": 1, "method": "system.hello",
                "params": {"protocol": {"major": 2, "minor": 0},
                           "token": EXAMPLE_TOKEN, "world": None,
                           "coordinates": "absolute"},
            }])
            self.assertEqual((context.protocol.major, context.protocol.minor), (2, 0))
            self.assertEqual(context.session_id, result["sessionId"])
            self.assertEqual(context.world.name, "world")
            self.assertEqual(context.world.key, "minecraft:overworld")
            self.assertEqual((context.world.min_y, context.world.max_y_exclusive), (-64, 320))
            self.assertEqual(context.capabilities, ("blocks.set",))
            self.assertEqual(context.limits.max_sessions, JsonNumber("8"))
            for obj, name, value in (
                (context, "session_id", "changed"),
                (context.protocol, "major", 3),
                (context.world, "name", "changed"),
                (context.limits, "max_sessions", JsonNumber("9")),
                (context.limits.max_sessions, "text", "9"),
            ):
                with self.subTest(field=name), self.assertRaises(FrozenInstanceError):
                    setattr(obj, name, value)
            with self.assertRaises(AttributeError):
                transport.context = None
            transport.close()
            self.assertIs(transport.context, context)

    def test_explicit_world_and_coordinate_profile(self):
        requests = []
        result = hello_result(world="Учебный мир")
        with peer(successful_peer(requests, result)) as server:
            transport = self.connect(server, world="Учебный мир", coordinates="absolute")
            self.assertEqual(transport.context.world.name, "Учебный мир")
            self.assertEqual(requests[0]["params"]["world"], "Учебный мир")

    def test_environment_token_only_when_argument_is_none(self):
        requests = []
        with mock.patch.dict("os.environ", {"MINEBRIDGE_TOKEN": EXAMPLE_TOKEN}), \
                peer(successful_peer(requests)) as server:
            self.connect(server, token=None)
            self.assertEqual(requests[0]["params"]["token"], EXAMPLE_TOKEN)

    def test_explicit_token_preserves_outer_spaces(self):
        requests = []
        with peer(successful_peer(requests)) as server:
            self.connect(server, token="  " + EXAMPLE_TOKEN + " \t")
            self.assertEqual(requests[0]["params"]["token"], "  " + EXAMPLE_TOKEN + " \t")

    def test_missing_or_blank_token_is_sent_for_server_auth_policy(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            for value in (None, "", " ", "\t\n", "\u2003"):
                requests = []
                with self.subTest(value=value), peer(successful_peer(requests)) as server:
                    self.connect(server, token=value)
                    self.assertEqual(requests[0]["params"]["token"], value)
        requests = []
        with mock.patch.dict("os.environ", {"MINEBRIDGE_TOKEN": EXAMPLE_TOKEN}), \
                peer(successful_peer(requests)) as server:
            self.connect(server, token="")
            self.assertEqual(requests[0]["params"]["token"], "")

    def test_invalid_options_fail_before_dns_and_do_not_echo_values(self):
        invalid = (
            ({"token": 123}, TypeError),
            ({"world": 123}, TypeError),
            ({"coordinates": 123}, TypeError),
            ({"coordinates": "relative"}, errors.UnsupportedFeatureError),
            ({"coordinates": EXAMPLE_TOKEN}, errors.UnsupportedFeatureError),
            ({"token": "\ud800"}, errors.ProtocolError),
            ({"token": "x" * MAX_FRAME_BYTES}, errors.ProtocolError),
            ({"world": "\ud800"}, errors.ProtocolError),
            ({"world": "x" * MAX_FRAME_BYTES}, errors.ProtocolError),
        )
        with mock.patch("socket.getaddrinfo") as resolve:
            for options, exception in invalid:
                supplied = {"token": EXAMPLE_TOKEN, **options}
                with self.subTest(option=next(iter(options))):
                    try:
                        TcpTransport.connect_and_handshake(**supplied)
                    except exception as caught:
                        rendered = "".join(traceback.format_exception(caught))
                        self.assertNotIn(EXAMPLE_TOKEN, str(caught))
                        # Traceback source references variable names, never
                        # interpolates peer values into messages or causes.
                        self.assertNotIn("x" * 1000, rendered)
                        self.assertIsNone(caught.__cause__)
                    else:
                        self.fail("Expected local validation failure")
            resolve.assert_not_called()

    def test_tcp_only_connect_does_not_send_hello_or_create_context(self):
        connected = threading.Event()

        def handle(connection, stopping):
            connected.set()
            self.assertEqual(connection.recv(1), b"")

        with peer(handle) as server:
            transport = TcpTransport.connect("127.0.0.1", server.port)
            self.assertTrue(connected.wait(1))
            self.assertIsNone(transport.context)
            transport.close()

    def assert_rejected(self, response, expected=errors.ProtocolError, *, options=None):
        closed = threading.Event()

        def handle(connection, stopping):
            request = read_request(connection)
            frame = response(request) if callable(response) else response
            connection.sendall(frame)
            if connection.recv(1) == b"":
                closed.set()

        with peer(handle) as server:
            try:
                self.connect(server, **(options or {}))
            except expected as caught:
                self.assertTrue(closed.wait(1), "Failed hello did not close TCP")
                return caught
            self.fail("Handshake unexpectedly succeeded")

    def test_malformed_or_incomplete_results_close_the_connection(self):
        complete = hello_result()
        invalid = []
        for key in complete:
            value = deepcopy(complete)
            del value[key]
            invalid.append(value)
        for key, value in (("sessionId", "bad"), ("protocol", {"major": 1, "minor": 0}),
                           ("coordinates", "relative"), ("capabilities", [])):
            value_result = deepcopy(complete)
            value_result[key] = value
            invalid.append(value_result)
        for key, value in (("key", None), ("key", "invalid key")):
            value_result = deepcopy(complete)
            value_result["world"][key] = value
            invalid.append(value_result)
        missing_key = deepcopy(complete)
        del missing_key["world"]["key"]
        invalid.append(missing_key)
        for result in invalid:
            with self.subTest(fields=tuple(result)):
                error = self.assert_rejected(encode_frame({
                    "jsonrpc": "2.0", "id": 1, "result": result,
                }))
                self.assertEqual(error.outcome, "not-applied")

    def test_explicit_world_cannot_silently_select_another_world(self):
        error = self.assert_rejected(encode_frame({
            "jsonrpc": "2.0", "id": 1, "result": hello_result(world="other"),
        }), options={"world": "wanted"})
        self.assertEqual(str(error), "Unexpected handshake world")

    def test_server_errors_are_typed_closed_and_do_not_echo_remote_secret(self):
        cases = (
            (-32001, "AUTH_FAILED", errors.AuthenticationError),
            (-32002, "PROTOCOL_VERSION", errors.ProtocolVersionError),
            (-32020, "WORLD_NOT_FOUND", errors.WorldNotFoundError),
            (-32021, "PERMISSION_DENIED", errors.PermissionDeniedError),
            (-32025, "UNSUPPORTED_FEATURE", errors.UnsupportedFeatureError),
            (-32602, "INVALID_PARAMS", errors.InvalidArgumentError),
            (-32603, "INTERNAL_ERROR", errors.ServerOperationError),
        )
        for code, machine, exception in cases:
            with self.subTest(code=machine):
                error = self.assert_rejected(encode_frame({
                    "jsonrpc": "2.0", "id": 1,
                    "error": {"code": code, "message": EXAMPLE_TOKEN,
                              "data": {"code": machine, "outcome": "not-applied"}},
                }), exception)
                self.assertEqual(error.code, machine)
                self.assertEqual(error.outcome, "not-applied")
                self.assertIsNone(error.__cause__)
                self.assertNotIn(EXAMPLE_TOKEN, "".join(traceback.format_exception(error)))

    def test_hello_timeout_closes_without_retry(self):
        requests = []
        closed = threading.Event()

        def handle(connection, stopping):
            requests.append(read_request(connection))
            if connection.recv(1) == b"":
                closed.set()

        with peer(handle) as server:
            with self.assertRaises(errors.OperationTimeoutError) as caught:
                self.connect(server, timeout=0.15)
            # Hello cannot mutate the Minecraft world, even if its reply is lost.
            self.assertEqual(caught.exception.outcome, "not-applied")
            self.assertTrue(closed.wait(1))
            self.assertEqual(len(requests), 1)

    def test_unknown_response_fields_are_ignored_and_context_copies_capabilities(self):
        result = hello_result()
        result["future"] = {"metadata": "accepted"}
        result["protocol"]["future"] = True
        result["world"]["future"] = True
        result["limits"]["future"] = True
        result["capabilities"].append("future.method")
        with peer(successful_peer([], result)) as server:
            context = self.connect(server).context
            result["capabilities"].append("later.change")
            self.assertEqual(context.capabilities, ("blocks.set", "future.method"))
            self.assertFalse(hasattr(context, "future"))

    def test_remote_limits_remain_exact_and_never_expand_decoder_ceilings(self):
        result = hello_result()
        result["limits"].update({
            "maxFrameBytes": JsonNumber("9" * 5000),
            "maxJsonDepth": JsonNumber("9" * 5000),
            "maxSessions": JsonNumber("9" * 5000),
            "handshakeTimeoutSeconds": JsonNumber("1e99999999999999999999999"),
            "executorBudgetMillis": JsonNumber("0.25"),
        })
        oversized_rejected = threading.Event()

        def handle(connection, stopping):
            request = read_request(connection)
            connection.sendall(encode_frame({
                "jsonrpc": "2.0", "id": request["id"], "result": result,
            }))
            request = read_request(connection)
            connection.sendall(b"x" * (MAX_FRAME_BYTES + 1))
            if connection.recv(1) == b"":
                oversized_rejected.set()

        with peer(handle) as server:
            transport = self.connect(server)
            self.assertEqual(transport.context.limits.max_sessions.text, "9" * 5000)
            self.assertEqual(transport.context.limits.handshake_timeout_seconds.text,
                             "1e99999999999999999999999")
            self.assertEqual(transport.context.limits.executor_budget_millis.text, "0.25")
            with self.assertRaises(errors.ProtocolError):
                transport.exchange("blocks.set", {
                    "world": "world", "position": [0, 80, 0],
                    "block": {"key": "minecraft:stone", "states": {}},
                })
            self.assertTrue(oversized_rejected.wait(1))
            self.assertTrue(transport.closed)
            self.assertEqual(MAX_JSON_DEPTH, 16)

    def test_remote_depth_limit_never_expands_local_decoder_ceiling(self):
        result = hello_result()
        result["limits"]["maxJsonDepth"] = 100
        closed = threading.Event()

        def handle(connection, stopping):
            request = read_request(connection)
            connection.sendall(encode_frame({
                "jsonrpc": "2.0", "id": request["id"], "result": result,
            }))
            request = read_request(connection)
            deep = {}
            for _ in range(MAX_JSON_DEPTH):
                deep = {"nested": deep}
            # Bypass the fixture encoder deliberately: this frame is invalid
            # under the local depth ceiling, despite the advertised value 100.
            frame = json.dumps({
                "jsonrpc": "2.0", "id": request["id"],
                "result": {"applied": True, "future": deep},
            }).encode("utf-8") + b"\n"
            connection.sendall(frame)
            if connection.recv(1) == b"":
                closed.set()

        with peer(handle) as server:
            transport = self.connect(server)
            self.assertEqual(transport.context.limits.max_json_depth.text, "100")
            with self.assertRaises(errors.ProtocolError):
                transport.exchange("blocks.set", {
                    "world": "world", "position": [0, 80, 0],
                    "block": {"key": "minecraft:stone", "states": {}},
                })
            self.assertTrue(closed.wait(1))
            self.assertTrue(transport.closed)

    def test_two_concurrent_hellos_have_independent_ids_contexts_and_failure(self):
        barrier = threading.Barrier(2)
        requests = []

        def handle(connection, stopping):
            request = read_request(connection)
            requests.append(request)
            barrier.wait(2)
            connection.sendall(encode_frame({
                "jsonrpc": "2.0", "id": request["id"],
                "result": hello_result(world=request["params"]["world"]),
            }))
            # A subsequent probe has ID 2 in each connection. One loses its
            # connection; the other receives a domain error and stays usable.
            request = read_request(connection)
            if request is None or request["params"]["world"] == "first":
                return
            connection.sendall(encode_frame({
                "jsonrpc": "2.0", "id": request["id"],
                "error": {"code": -32025, "message": "Unavailable at this stage",
                          "data": {"code": "UNSUPPORTED_FEATURE", "outcome": "not-applied"}},
            }))
            while not stopping.is_set() and connection.recv(1):
                pass

        with peer(handle) as server:
            transports, failures = {}, []

            def connect(world):
                try:
                    transports[world] = TcpTransport.connect_and_handshake(
                        "127.0.0.1", server.port, token=EXAMPLE_TOKEN, world=world,
                    )
                except Exception as error:
                    failures.append(error)

            threads = [threading.Thread(target=connect, args=(world,))
                       for world in ("first", "second")]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(3)
            try:
                self.assertFalse(any(thread.is_alive() for thread in threads))
                self.assertEqual(failures, [])
                self.assertEqual([request["id"] for request in requests], [1, 1])
                first, second = transports["first"], transports["second"]
                self.assertNotEqual(first.context.session_id, second.context.session_id)
                self.assertEqual(first.context.world.name, "first")
                self.assertEqual(second.context.world.name, "second")
                for transport, world, exception in (
                    (first, "first", errors.ConnectionError),
                    (second, "second", errors.UnsupportedFeatureError),
                ):
                    with self.assertRaises(exception):
                        transport.exchange("blocks.set", {
                            "world": world, "position": [0, 80, 0],
                            "block": {"key": "minecraft:stone", "states": {}},
                        })
                self.assertTrue(first.closed)
                self.assertFalse(second.closed)
            finally:
                for transport in transports.values():
                    transport.close()


if __name__ == "__main__":
    unittest.main()
