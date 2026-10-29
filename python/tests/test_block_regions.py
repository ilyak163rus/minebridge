"""Public region reads, state round-trips and ordering against a controlled peer."""

import select
import unittest

from minebridge import Minecraft, errors
from minebridge._protocol import encode_frame
from minebridge.models import BlockSpec
from test_client import send_hello
from test_transport import peer, read_request, result


def reply(connection, request, value):
    connection.sendall(encode_frame({"jsonrpc": "2.0", "id": request["id"], "result": value}))


class RegionClientTests(unittest.TestCase):
    def test_read_waits_for_buffered_region_and_preserves_states(self):
        requests = []

        def handle(connection, stopping):
            send_hello(connection, read_request(connection))
            write = read_request(connection)
            requests.append(write)
            self.assertEqual(write["method"], "blocks.setRegion")
            self.assertEqual(write["params"]["from"], [-2, 80, -1])
            self.assertEqual(write["params"]["to"], [2, 81, 6])
            # A result read must not overtake the unacknowledged buffered fill.
            self.assertFalse(select.select([connection], [], [], .06)[0])
            connection.sendall(result(write["id"]))
            read = read_request(connection)
            requests.append(read)
            self.assertEqual(read["method"], "blocks.get")
            reply(connection, read, {"block": {"key": "minecraft:oak_log", "states": {"axis": "x"}}})
            self.assertIsNone(read_request(connection))

        with peer(handle) as server:
            mc = Minecraft.create("127.0.0.1", server.port)
            try:
                mc.setBlocks(2, 81, 6, -2, 80, -1, "minecraft:oak_log[axis=x]")
                actual = mc.blocks.getBlock(-2, 80, -1)
                self.assertEqual(actual, BlockSpec("minecraft:oak_log", {"axis": "x"}))
                self.assertEqual([request["id"] for request in requests], [2, 3])
            finally:
                mc.close()

    def test_pages_return_absolute_coordinates_with_both_corners_included(self):
        positions = [(x, y, z) for y in (80, 81) for z in range(-1, 7) for x in range(-2, 3)]
        requests = []

        def handle(connection, stopping):
            send_hello(connection, read_request(connection))
            for offset in (0, 64):
                request = read_request(connection)
                requests.append(request)
                self.assertEqual(request["method"], "blocks.getRegion")
                self.assertEqual(request["params"]["offset"], offset)
                self.assertEqual(request["params"]["limit"], 64)
                chosen = positions[offset:offset + 64]
                reply(connection, request, {
                    "total": len(positions), "nextOffset": 64 if offset == 0 else None,
                    "blocks": [{"position": list(position),
                                "block": {"key": "minecraft:stone", "states": {}}} for position in chosen],
                })
            self.assertIsNone(read_request(connection))

        with peer(handle) as server:
            mc = Minecraft.create("127.0.0.1", server.port)
            try:
                actual = mc.blocks.getBlocks(2, 81, 6, -2, 80, -1)
                self.assertEqual(actual, {position: BlockSpec("minecraft:stone") for position in positions})
                self.assertEqual(len(requests), 2)
            finally:
                mc.close()

    def test_duplicate_or_incomplete_page_is_not_a_successful_region(self):
        def handle(connection, stopping):
            send_hello(connection, read_request(connection))
            request = read_request(connection)
            reply(connection, request, {
                "total": 2, "nextOffset": None,
                "blocks": [{"position": [0, 80, 0], "block": {"key": "minecraft:stone", "states": {}}}] * 2,
            })
            self.assertIsNone(read_request(connection))

        with peer(handle) as server:
            mc = Minecraft.create("127.0.0.1", server.port)
            try:
                with self.assertRaises(errors.ProtocolError):
                    mc.blocks.getBlocks(0, 80, 0, 1, 80, 0)
                self.assertTrue(mc._transport.closed)
            finally:
                mc.close()

    def test_oversized_regions_fail_before_game_requests(self):
        def handle(connection, stopping):
            send_hello(connection, read_request(connection))
            self.assertIsNone(read_request(connection))

        with peer(handle) as server:
            mc = Minecraft.create("127.0.0.1", server.port)
            try:
                with self.assertRaises(errors.LimitExceededError):
                    mc.setBlocks(-2**31, 0, 0, 2**31 - 1, 0, 0, "minecraft:stone")
                with self.assertRaises(errors.LimitExceededError):
                    mc.getBlocks(0, 0, 0, 100, 100, 100)
            finally:
                mc.close()


if __name__ == "__main__":
    unittest.main()
