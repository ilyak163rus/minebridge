"""Named player selection remains a local value accepted by existing target APIs."""

from dataclasses import FrozenInstanceError
import unittest
from unittest import mock
from uuid import UUID

from minebridge import Minecraft, effects, gamemode, items, selector
from minebridge._protocol import encode_frame
from minebridge.models import InventoryRef
from test_handshake import hello_result
from test_transport import peer, read_request


PLAYER = "00000000-0000-4000-8000-000000000001"
TARGET_RESULT = {"matched": 1, "applied": 1, "targets": [
    {"uuid": PLAYER, "applied": True, "code": None},
]}


class NamedSelectorTests(unittest.TestCase):
    def test_construction_is_offline_typed_immutable_and_preserves_current_name(self):
        with mock.patch("socket.getaddrinfo") as dns, mock.patch("socket.socket") as socket:
            selected = selector.playerByName("YourNick_123")
            self.assertIsInstance(selected, selector.Selector)
            self.assertEqual(str(selected), "@a[name=YourNick_123,limit=1]")
            self.assertNotEqual(selected, selector.SELF)
            self.assertIn("playerByName", selector.__all__)
            for name in ("a", "0", "_", "A" * 16):
                with self.subTest(name=name):
                    self.assertEqual(str(selector.playerByName(name)), f"@a[name={name},limit=1]")
            dns.assert_not_called()
            socket.assert_not_called()
        with self.assertRaises(FrozenInstanceError):
            selected.expression = "@a"

    def test_invalid_names_cannot_add_selector_arguments_or_hidden_whitespace(self):
        for name in ("", "A" * 17, " hasSpace", "has Space", "trailing ", "Alice\n",
                     "Алиса", "Ａlice", "@s", "Alice,limit=20", "Alice]", 'Alice"',
                     "!Alice", "Alice\x00", "Alice\\", PLAYER):
            with self.subTest(name=name), self.assertRaises(ValueError):
                selector.playerByName(name)
        for value in (None, True, 12, b"Alice", UUID(PLAYER)):
            with self.subTest(value=value), self.assertRaises(TypeError):
                selector.playerByName(value)

    def test_existing_public_target_apis_send_named_selector_without_self_binding(self):
        requests = []

        def answer(request):
            if request["method"] == "players.giveItem":
                return {"matched": 1, "applied": 1, "targets": [{
                    "uuid": PLAYER, "applied": True, "code": None,
                    "requested": 3, "given": 3, "leftovers": [], "dropped": 0,
                }]}
            if request["method"] == "inventories.ofPlayer":
                return {"inventory": {"kind": "player", "player": PLAYER, "size": 41,
                                      "slots": list(range(36)) + ["head", "chest", "legs", "feet", "off_hand"]}}
            return TARGET_RESULT

        def handle(connection, stopping):
            hello = read_request(connection)
            requests.append(hello)
            metadata = hello_result(world="lesson")
            metadata["capabilities"].extend(("inventories.ofPlayer", "players.setGameMode"))
            connection.sendall(encode_frame({"jsonrpc": "2.0", "id": hello["id"], "result": metadata}))
            while not stopping.is_set():
                request = read_request(connection)
                if request is None:
                    return
                requests.append(request)
                connection.sendall(encode_frame({"jsonrpc": "2.0", "id": request["id"], "result": answer(request)}))

        with peer(handle) as server:
            with Minecraft.create("127.0.0.1", server.port, timeout=1) as mc:
                selected = selector.playerByName("YourNick")
                self.assertEqual(mc.players.giveItem(selected, items.EMERALD, 3).targets[0].given, 3)
                self.assertEqual(mc.effects.add(selected, effects.SPEED, 100, 2).applied, 1)
                self.assertEqual(mc.setPos(selected, 1, 80, -1).applied, 1)
                self.assertEqual(mc.players.setGameMode(selected, gamemode.CREATIVE).applied, 1)
                inventory = mc.inventories.ofPlayer(selected)
                self.assertIsInstance(inventory, InventoryRef)
                self.assertEqual(inventory.player, UUID(PLAYER))
        self.assertEqual([request["method"] for request in requests], [
            "system.hello", "players.giveItem", "effects.add", "players.teleport",
            "players.setGameMode", "inventories.ofPlayer",
        ])
        for request in requests[1:]:
            with self.subTest(method=request["method"]):
                self.assertEqual(request["params"]["targets"], "@a[name=YourNick,limit=1]")
                self.assertIsNone(request["params"]["executor"])


if __name__ == "__main__":
    unittest.main()
