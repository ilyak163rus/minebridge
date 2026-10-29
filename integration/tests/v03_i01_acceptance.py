"""Compact public-API I01 scenarios; independent Paper observations decide postconditions."""

import struct
import time
from observer_client import ObserverClient
from game_client import GameClient


def applied(result, expected):
    assert result["applied"] == expected, result
    return result


def acceptance(harness, paper, Worker, games, workers, check):
    observer = ObserverClient(paper, harness.artifacts / "observer.json")
    case = observer.case_id()
    world = next(row for row in observer.result(case, "worlds")["worlds"] if row["name"] == harness.world_name)
    protocol = observer.result(case, "gameProtocol")
    for index, name in enumerate(("V03Alice", "V03Bob")):
        game = GameClient(harness.game_port, name, protocol); games.append(game); game.wait_ready()
        observer.result(case, "playerPlace", name, world["uuid"], 128 + 32 * index, 210, 128)
    alice = Worker(harness, games[0].name, logging=True); workers.append(alice)
    bob = Worker(harness, games[1].name); workers.append(bob)
    assert alice.context["pid"] != bob.context["pid"]
    assert alice.context["info"]["sessionId"] != bob.context["info"]["sessionId"]
    for peer, logging in ((alice, True), (bob, False)):
        info = peer.context["info"]
        assert info["world"]["uuid"] == world["uuid"] and info["writeMode"] == "buffered" and info["logging"] is logging
        assert peer.context["tokenEnvironmentAbsent"]
        assert "players.setGameMode" in info["capabilities"] and "worlds.setGameRule" in info["capabilities"]
        assert peer.context["nextBefore"] == peer.context["nextAfter"]
    check("two-real-game-clients-two-source-processes-cached-public-info", {
        "players": [game.evidence() for game in games], "python": [peer.context for peer in workers]})
    rebound = alice.call("rebind", player=games[1].name)
    assert rebound["derived"][0]["uuid"] == games[1].uuid and rebound["original"][0]["uuid"] == games[0].uuid
    assert rebound["sameInfo"]
    check("withContext-keeps-original-self-and-shares-cached-info", rebound)

    rules = alice.call("rules")
    by_name = {row["name"]: row for row in rules}
    for name in ("KEEP_INVENTORY", "DO_DAYLIGHT_CYCLE", "DO_WEATHER_CYCLE", "NATURAL_REGENERATION", "RANDOM_TICK_SPEED"):
        assert name in by_name and by_name[name]["key"].startswith("minecraft:"), name
    for name in ("DO_DAYLIGHT_CYCLE", "DO_WEATHER_CYCLE", "NATURAL_REGENERATION"):
        alice.call("setRule", constant=name, value=False)
        assert observer.result(case, "controlRule", world["uuid"], by_name[name]["key"])["value"] is False
    # Explicit stable fixture prerequisites: no fall simulation/incoming damage,
    # no natural regeneration, hunger below the regeneration threshold.
    applied(alice.call("set", kind="FoodLevel", target="@a", value=10), 2)
    applied(alice.call("set", kind="GameMode", target="@a", value="adventure"), 2)
    applied(alice.call("set", kind="GameMode", value="creative"), 1)
    modes = [observer.result(case, "controlPlayer", game.name) for game in games]
    assert modes[0]["gameMode"] == "creative" and modes[1]["gameMode"] == "adventure"
    assert alice.call("get", kind="GameMode") == "creative" and bob.call("get", kind="GameMode") == "adventure"
    check("game-mode-self-and-all-with-independent-observer", modes)

    observer.result(case, "controlHealthFixture", games[0].name, 20, 10)
    observer.result(case, "controlHealthFixture", games[1].name, 10, 8)
    rejected = alice.call("set", kind="Health", target="@a", value=15, error="InvalidPlayerValueError")
    assert rejected["outcome"] == "not-applied"
    unchanged = [observer.result(case, "controlPlayer", game.name) for game in games]
    assert [row["health"] for row in unchanged] == [10, 8]
    applied(alice.call("set", kind="Health", value=1.1), 1)
    actual = observer.result(case, "controlPlayer", games[0].name)
    expected = struct.unpack("f", struct.pack("f", 1.1))[0]
    assert actual["health"] == expected and alice.call("get", kind="Health") == expected
    underflow = alice.call("set", kind="Health", value=1e-300, error="InvalidPlayerValueError")
    assert underflow["outcome"] == "not-applied"
    applied(bob.call("set", kind="FoodLevel", value=7), 1)
    assert observer.result(case, "controlPlayer", games[1].name)["foodLevel"] == 7 and bob.call("get", kind="FoodLevel") == 7
    check("actual-max-hp-prevalidation-native-float-readback-and-food", {"rejected": rejected, "unchanged": unchanged, "actual": actual, "underflow": underflow})

    applied(alice.call("set", kind="GameMode", target="@a", value="survival"), 2)
    observer.result(case, "controlCancel", "gameMode", games[1].uuid)
    result = alice.call("set", kind="GameMode", target="@a", value="adventure")
    applied(result, 1)
    refused = next(row for row in result["targets"] if row["uuid"] == games[1].uuid)
    assert refused["code"] == "GAME_MODE_REJECTED" and refused["applied"] is False
    mode_state = observer.result(case, "controlState")
    assert mode_state["modeCancelled"] >= 1
    assert observer.result(case, "controlPlayer", games[1].name)["gameMode"] == "survival"
    assert observer.result(case, "controlPlayer", games[0].name)["gameMode"] == "adventure"
    observer.result(case, "controlCancel", "reset", "all")
    check("cancelled-game-mode-visible-per-target-with-other-session-alive", {"result": result, "observer": mode_state, "bob": bob.call("get", kind="GameMode")})

    applied(alice.call("effectAdd"), 1); applied(bob.call("effectAdd", named=True), 1)
    snapshots = [observer.result(case, "controlPlayer", game.name) for game in games]
    speed = [next(effect for effect in row["effects"] if effect["key"] == "minecraft:speed") for row in snapshots]
    assert all(row["level"] == 200 and row["amplifier"] == 199 and 0 < row["durationTicks"] <= 2000 for row in speed)
    assert abs(speed[0]["durationTicks"] - speed[1]["durationTicks"]) <= 20
    observer.result(case, "controlCancel", "effectRemove", games[0].uuid)
    removal = alice.call("effectRemove"); applied(removal, 0)
    assert removal["targets"][0]["code"] == "EFFECT_REJECTED"
    effect_state = observer.result(case, "controlState"); assert effect_state["effectCancelled"] >= 1
    assert any(e["key"] == "minecraft:speed" for e in observer.result(case, "controlPlayer", games[0].name)["effects"])
    applied(bob.call("effectRemove"), 1); applied(bob.call("effectRemove"), 1)
    assert observer.result(case, "controlPlayer", games[1].name)["effects"] == []
    observer.result(case, "controlCancel", "reset", "all")
    applied(alice.call("effectAdd", effect="GLOWING", duration=10, level=1), 1)
    applied(alice.call("effectClear"), 1); applied(alice.call("effectClear"), 1)
    assert observer.result(case, "controlPlayer", games[0].name)["effects"] == []
    check("positional-named-effects-removal-clear-idempotence-and-cancellation", {"speed": speed, "rejected": removal, "observer": effect_state})

    positions = [(128.25, 210.5, 144.75), (129.125, 211.25, 145.5), (130.875, 212.5, 146.125)]
    for entry, position in zip(("root", "players", "teleport"), positions):
        applied(alice.call("pos", entry=entry, position=position), 1)
        at = alice.call("getPos"); assert (at["x"], at["y"], at["z"]) == position
        rows = observer.result(case, "players")["players"]; actual = next(row for row in rows if row["uuid"] == games[0].uuid)
        assert tuple(actual[key] for key in ("x", "y", "z")) == position
    far = (24000.25, 220.5, 24000.75)
    applied(bob.call("pos", position=far), 1)
    far_state = bob.call("getPos"); assert tuple(far_state[k] for k in ("x", "y", "z")) == far
    check("setPos-aliases-fractional-and-auto-loaded-far-teleport", {"entries": positions, "far": far_state})

    alice.call("setRule", constant="KEEP_INVENTORY", value=True)
    assert alice.call("getRule", constant="KEEP_INVENTORY") is True
    assert alice.call("getRule", rule=by_name["KEEP_INVENTORY"]["key"]) is True
    assert observer.result(case, "controlRule", world["uuid"], by_name["KEEP_INVENTORY"]["key"])["value"] is True
    random_key = by_name["RANDOM_TICK_SPEED"]["key"]
    alice.call("setRule", constant="RANDOM_TICK_SPEED", value=7)
    assert alice.call("getRule", rule=random_key) == 7
    assert observer.result(case, "controlRule", world["uuid"], random_key)["value"] == 7
    unknown = alice.call("getRule", rule="minecraft:not_a_real_game_rule", error="InvalidGameRuleError")
    badtype = alice.call("setRule", rule=random_key, forgeBool=True, value=True, error="InvalidRuleValueError")
    assert badtype["outcome"] == "not-applied" and observer.result(case, "controlRule", world["uuid"], random_key)["value"] == 7
    alice.call("setTime", value=24000, error="ValueError")
    alice.call("setRule", constant="RANDOM_TICK_SPEED", value=2147483648, error="ValueError")
    alice.call("setTime", value=23000); before = observer.result(case, "controlWorld", world["uuid"])
    alice.call("setTime", value=1000); after = observer.result(case, "controlWorld", world["uuid"])
    assert alice.call("getTime") == 1000 and after["time"] == 1000 and after["fullTime"] - before["fullTime"] == 2000
    check("typed-game-rules-canonical-aliases-errors-and-Paper-time-semantics", {"uniqueRules": len({r["key"] for r in rules}), "before": before, "after": after, "unknown": unknown, "badtype": badtype})

    weather_states = []
    for kind in ("rain", "thunder", "clear"):
        alice.call("setWeather", value=kind)
        assert alice.call("getWeather") == kind
        state = observer.result(case, "controlWorld", world["uuid"]); weather_states.append(state)
        assert state["storm"] is (kind != "clear") and state["thundering"] is (kind == "thunder")
    alice.call("setWeather", value="rain")
    observer.result(case, "controlCancel", "weather", world["uuid"])
    rejected_weather = alice.call("setWeather", value="clear", error="WorldChangeRejectedError")
    assert rejected_weather["outcome"] == "unknown"
    state = observer.result(case, "controlState"); assert state["weatherCancelled"] >= 1
    assert alice.call("getWeather") == "rain"
    observer.result(case, "controlCancel", "reset", "all"); alice.call("setWeather", value="clear")
    check("world-weather-readback-and-cancelled-setter-never-claims-success", {"states": weather_states, "rejected": rejected_weather, "observer": state})

    fixture = observer.case_id(); anchor = (128, 215, 128)
    observer.result(fixture, "setup", world["uuid"], "%d,%d,%d" % anchor)
    managed = alice.call("contextManager", position=anchor)
    assert managed["closed"] and managed["preservedBody"]
    assert observer.result(case, "read", world["uuid"], *anchor)["key"] == "minecraft:cobblestone"
    chat = games[0].wait_chat("v03-i01-context-close")
    observer.result(fixture, "cleanup")
    check("context-manager-drains-and-preserves-body-error", {"managed": managed, "chat": chat})

    alice.close(); bob.close(); time.sleep(.15)
    alice_lines = [line for line in paper.lines if "ACTION session=" + alice.context["info"]["sessionId"] in line]
    bob_lines = [line for line in paper.lines if "ACTION session=" + bob.context["info"]["sessionId"] in line]
    assert alice_lines and not bob_lines
    assert any("method=players.setGameMode" in line for line in alice_lines)
    assert any("method=worlds.setGameRule" in line for line in alice_lines)
    assert any("method=effects.remove" in line for line in alice_lines)
    check("logging-is-session-local-and-clients-close-without-receiver-leaks", {"aliceLines": len(alice_lines), "bobLines": len(bob_lines)})
    for game in games:
        assert not game.errors, game.evidence()
        game.close()
