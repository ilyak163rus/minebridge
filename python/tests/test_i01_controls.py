"""Public I01 contracts: old calls, settings, feature gates and deterministic close."""

from dataclasses import FrozenInstanceError
from importlib import resources
import inspect
import json
import unittest
from uuid import UUID

from minebridge import Minecraft, effects, errors, gamemode, selector, weather
from minebridge._handshake import context_from_result
from minebridge._protocol import Response, decode_response, encode_frame
from minebridge.models import GameMode, GameRuleKey, TargetResult
from test_handshake import hello_result


ALICE = {"uuid": "00000000-0000-0000-0000-000000000001", "entityId": 7, "name": "Alice"}
CAPABILITIES = (
    "players.getGameMode", "players.setGameMode", "players.getHealth", "players.setHealth",
    "players.getFoodLevel", "players.setFoodLevel", "effects.remove", "effects.clear",
    "worlds.getTime", "worlds.setTime", "worlds.getWeather", "worlds.setWeather",
    "worlds.getGameRule", "worlds.setGameRule",
)
SUCCESS = {"matched": 1, "applied": 1, "targets": [
    {"uuid": ALICE["uuid"], "applied": True, "code": None},
]}


class FakeTransport:
    def __init__(self, *, capabilities=CAPABILITIES, answer=None, finish_error=None):
        metadata = hello_result(world="lesson")
        metadata["capabilities"].extend(capabilities)
        frame = encode_frame({"jsonrpc": "2.0", "id": 1, "result": metadata})
        self.context = context_from_result(decode_response(frame[:-1], 1, "system.hello").result)
        self.calls = []
        self.answer = answer or (lambda method, params: SUCCESS)
        self.finish_error = finish_error
        self.finishes = 0
        self.closed = False

    def exchange(self, method, params, *, mutation=False):
        self.calls.append((method, params, mutation))
        result = {"player": ALICE} if method == "players.get" else self.answer(method, params)
        return Response(len(self.calls) + 1, result=result)

    def close(self):
        self.closed = True

    def finish(self):
        self.finishes += 1
        self.closed = True
        if self.finish_error:
            raise self.finish_error


class ControlApiTests(unittest.TestCase):
    def test_effect_positional_form_preserves_old_wire_and_particles_stays_keyword_only(self):
        transport = FakeTransport(capabilities=())
        mc = Minecraft(transport)
        a = mc.effects.add(selector.SELF, effects.SPEED, 100, 200)
        b = mc.effects.add(selector.SELF, effects.SPEED, duration=100, level=200)
        self.assertEqual(a, b)
        self.assertEqual(transport.calls[0], transport.calls[1])
        self.assertEqual(transport.calls[0][1]["effect"], {
            "key": "minecraft:speed", "durationTicks": 2000, "level": 200, "particles": True})
        self.assertEqual(inspect.signature(mc.effects.add).parameters["particles"].kind,
                         inspect.Parameter.KEYWORD_ONLY)
        with self.assertRaises(TypeError):
            mc.effects.add(selector.SELF, effects.SPEED, 100, 200, False)

    def test_root_and_player_setpos_delegate_existing_teleport_on_old_capabilities(self):
        transport = FakeTransport(capabilities=())
        mc = Minecraft(transport)
        a = mc.setPos(selector.ALL_PLAYERS, -0.25, 80.5, 3.75, world="minecraft:the_nether")
        b = mc.players.setPos(selector.ALL_PLAYERS, -0.25, 80.5, 3.75, world="minecraft:the_nether")
        c = mc.players.teleport(selector.ALL_PLAYERS, -0.25, 80.5, 3.75, world="minecraft:the_nether")
        self.assertEqual((a, b), (c, c))
        self.assertEqual(transport.calls, [transport.calls[0]] * 3)
        self.assertEqual(transport.calls[0], ("players.teleport", {
            "world": "lesson", "executor": None, "targets": "@a",
            "position": [-0.25, 80.5, 3.75], "destinationWorld": "minecraft:the_nether"}, True))

    def test_missing_capability_is_visible_before_new_rpc_but_does_not_block_aliases(self):
        transport = FakeTransport(capabilities=())
        mc = Minecraft(transport)
        calls = [lambda: mc.players.getGameMode("Alice"),
                 lambda: mc.players.setHealth(selector.ALL_PLAYERS, 5),
                 lambda: mc.effects.clear(selector.SELF),
                 lambda: mc.worlds.setTime(6000)]
        for call in calls:
            with self.assertRaises(errors.UnsupportedFeatureError):
                call()
        self.assertEqual(transport.calls, [])
        self.assertFalse(transport.closed)
        mc.close()
        with self.assertRaises(errors.ConnectionError):
            mc.players.getGameMode("Alice")

    def test_mode_health_food_results_and_explicit_context_are_preserved(self):
        def answer(method, params):
            return {"players.getGameMode": {"mode": "creative"},
                    "players.getHealth": {"value": 7.5},
                    "players.getFoodLevel": {"value": 12}}.get(method, SUCCESS)
        transport = FakeTransport(answer=answer)
        mc = Minecraft(transport).withContext(player="Alice")
        self.assertIs(mc.players.getGameMode(selector.SELF), GameMode.CREATIVE)
        self.assertEqual(mc.players.getHealth(selector.SELF), 7.5)
        self.assertEqual(mc.players.getFoodLevel(selector.SELF), 12)
        for result in (mc.players.setGameMode(selector.ALL_PLAYERS, gamemode.ADVENTURE),
                       mc.players.setHealth(selector.ALL_PLAYERS, 10.5),
                       mc.players.setFoodLevel(selector.ALL_PLAYERS, 20)):
            self.assertIsInstance(result, TargetResult)
            self.assertEqual(result.applied, 1)
        for method, params, mutation in transport.calls[1:]:
            self.assertEqual(params["world"], "lesson")
            self.assertEqual(params["executor"], ALICE["uuid"])

    def test_local_settings_validation_never_sends_wrong_values(self):
        transport = FakeTransport()
        mc = Minecraft(transport)
        for call in (lambda: mc.players.setHealth("Alice", True),
                     lambda: mc.players.setHealth("Alice", float("nan")),
                     lambda: mc.players.setHealth("Alice", -1),
                     lambda: mc.players.setHealth("Alice", 10**1000),
                     lambda: mc.players.setFoodLevel("Alice", True),
                     lambda: mc.players.setFoodLevel("Alice", 21),
                     lambda: mc.players.setGameMode("Alice", "invalid"),
                     lambda: mc.worlds.setTime(True),
                     lambda: mc.worlds.setTime(24000),
                     lambda: mc.worlds.setWeather("invalid")):
            with self.assertRaises((TypeError, ValueError)):
                call()
        self.assertEqual(transport.calls, [])

    def test_effect_removal_uses_existing_selection_and_explicit_key(self):
        transport = FakeTransport()
        mc = Minecraft(transport)
        mc.effects.remove(selector.ALL_ENTITIES, effects.SPEED)
        mc.effects.clear(selector.ALL_ENTITIES)
        self.assertEqual(transport.calls, [
            ("effects.remove", {"world": "lesson", "executor": None, "targets": "@e",
                                "effect": {"key": "minecraft:speed"}}, True),
            ("effects.clear", {"world": "lesson", "executor": None, "targets": "@e"}, True),
        ])

    def test_world_time_weather_and_rule_values_are_not_confused(self):
        boolean = GameRuleKey("minecraft:test_bool", bool, False)
        integer = GameRuleKey("minecraft:test_int", int, 3)

        def answer(method, params):
            return {"worlds.getTime": {"time": 6000},
                    "worlds.getWeather": {"weather": "rain"},
                    "worlds.getGameRule": {"rule": params.get("rule"), "value": True}}.get(method, {"applied": True})

        transport = FakeTransport(answer=answer)
        mc = Minecraft(transport)
        self.assertEqual(mc.worlds.getTime(), 6000)
        self.assertIs(mc.worlds.getWeather(), weather.RAIN)
        self.assertIs(mc.worlds.getGameRule(boolean), True)
        mc.worlds.setGameRule(boolean, True)
        mc.worlds.setGameRule(integer, 5, world="minecraft:the_nether")
        self.assertEqual(transport.calls[-1], ("worlds.setGameRule", {
            "world": "minecraft:the_nether", "rule": "minecraft:test_int", "value": 5}, True))
        before = len(transport.calls)
        for rule, value in ((boolean, 1), (integer, True), (integer, 2.5)):
            with self.assertRaises(TypeError):
                mc.worlds.setGameRule(rule, value)
        self.assertEqual(len(transport.calls), before)

    def test_mismatched_rule_echo_or_value_type_closes_instead_of_returning_wrong_setting(self):
        rule = GameRuleKey("minecraft:test", bool, False)
        for payload in ({"rule": "wrong", "value": True}, {"rule": rule.key, "value": 1}):
            transport = FakeTransport(answer=lambda method, params: payload)
            with self.assertRaises(errors.ProtocolError):
                Minecraft(transport).worlds.getGameRule(rule)
            self.assertTrue(transport.closed)

    def test_generated_rules_and_safe_aliases_keep_real_types_for_raw_key_calls(self):
        from minebridge import gamerule
        snapshot = json.loads(resources.files("minebridge._data")
                              .joinpath("gamerules-paper-26.2.json").read_text(encoding="utf-8"))
        self.assertTrue(snapshot["rules"])
        for row in snapshot["rules"]:
            key = getattr(gamerule, row["constant"])
            self.assertEqual(key.key, row["key"])
            self.assertIs(key.valueType, {"bool": bool, "int": int}[row["valueType"]])
            self.assertEqual(key.defaultValue, row["defaultValue"])
            self.assertIs(gamerule._BY_KEY[key.key], key)
            for alias in row["aliases"]:
                self.assertIs(getattr(gamerule, alias), key)
        for row in snapshot["unsupportedLegacyAliases"]:
            self.assertFalse(hasattr(gamerule, row["constant"]))
        boolean = next(gamerule._BY_KEY[row["key"]] for row in snapshot["rules"]
                       if row["valueType"] == "bool")
        integer = next(gamerule._BY_KEY[row["key"]] for row in snapshot["rules"]
                       if row["valueType"] == "int")
        transport = FakeTransport(answer=lambda method, params: {"applied": True})
        mc = Minecraft(transport)
        for key, wrong_value in ((boolean.key, 1), (integer.key, True)):
            with self.assertRaises(TypeError):
                mc.worlds.setGameRule(key, wrong_value)
        self.assertEqual(transport.calls, [])
        mc.worlds.setGameRule(boolean.key, boolean.defaultValue)
        mc.worlds.setGameRule(integer.key, integer.defaultValue)
        self.assertEqual([row[1]["rule"] for row in transport.calls], [boolean.key, integer.key])

    def test_connection_info_is_cached_frozen_and_preserves_facade_flags(self):
        transport = FakeTransport()
        mc = Minecraft(transport, "sync", logging=True)
        rebound = mc.withContext(player="Alice")
        before = len(transport.calls)
        info = rebound.server.getInfo()
        self.assertEqual(info.writeMode, "sync")
        self.assertTrue(info.logging)
        self.assertEqual(info.world.name, "lesson")
        self.assertIsInstance(info.world.uuid, UUID)
        self.assertEqual(info, mc.server.getInfo())
        self.assertEqual(rebound.server.getCapabilities(), info.capabilities)
        self.assertEqual(len(transport.calls), before)
        with self.assertRaises(FrozenInstanceError):
            info.logging = False
        rebound.close()
        self.assertEqual(mc.server.getInfo(), info)
        mc.close()
        self.assertEqual(transport.finishes, 1)

    def test_context_manager_drains_and_does_not_hide_body_exception(self):
        transport = FakeTransport()
        with Minecraft(transport) as mc:
            self.assertIs(mc._transport, transport)
        self.assertEqual(transport.finishes, 1)
        with self.assertRaisesRegex(errors.ConnectionError, "close failed"):
            with Minecraft(FakeTransport(finish_error=errors.ConnectionError("close failed"))):
                pass
        original = ValueError("body failed")
        try:
            with Minecraft(FakeTransport(finish_error=errors.ConnectionError("close failed"))):
                raise original
        except ValueError as result:
            self.assertIs(result, original)
            self.assertIn("close failed", result.__notes__[0])
        else:
            self.fail("Context manager hid the body exception")
