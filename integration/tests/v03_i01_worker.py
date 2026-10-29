"""Source-only I01 process; stdin is bounded local orchestration, never production RPC."""

from dataclasses import asdict, is_dataclass
import argparse
import json
import os
from pathlib import Path
import sys
import threading
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python/src"))
import minebridge
from minebridge import Minecraft, block, effects, gamemode, gamerule, selector, weather
from minebridge.models import GameRuleKey


def evidence(value):
    if is_dataclass(value): return evidence(asdict(value))
    if isinstance(value, UUID): return str(value)
    if isinstance(value, dict): return {str(key): evidence(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)): return [evidence(item) for item in value]
    return value


def emit(value): print(json.dumps(evidence(value), allow_nan=False), flush=True)


def failure(value):
    return {"type": type(value).__name__, "code": getattr(value, "code", None),
            "outcome": getattr(value, "outcome", None), "method": getattr(value, "method", None),
            "requestId": getattr(value, "request_id", None)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--player", required=True)
    parser.add_argument("--logging", action="store_true")
    args = parser.parse_args()
    package = Path(minebridge.__file__).resolve()
    assert package.is_relative_to(ROOT / "python/src")
    assert minebridge.__version__ == "0.3.0.dev1"
    baseline = {thread.ident for thread in threading.enumerate()}
    mc = Minecraft.create("127.0.0.1", args.port, player=args.player, logging=args.logging)

    def target(value): return selector.SELF if value == "$self" else value

    def perform(c):
        op = c["op"]
        if op == "info":
            before = mc._transport._next_id
            info = mc.server.getInfo(); caps = mc.server.getCapabilities()
            immutable = False
            try: info.writeMode = "sync"
            except AttributeError: immutable = True
            after = mc._transport._next_id
            assert before == after and immutable
            return {"info": info, "capabilities": caps, "nextBefore": before, "nextAfter": after,
                    "pid": os.getpid(), "package": str(package), "version": minebridge.__version__,
                    "tokenEnvironmentAbsent": "MINEBRIDGE_TOKEN" not in os.environ}
        if op == "rebind":
            derived = mc.withContext(player=c["player"])
            assert derived.server.getInfo() == mc.server.getInfo()
            return {"derived": derived.players.list(selector.SELF), "original": mc.players.list(selector.SELF),
                    "sameInfo": derived.server.getInfo() == mc.server.getInfo()}
        if op == "get": return getattr(mc.players, "get" + c["kind"])(target(c.get("target", "$self")))
        if op == "set": return getattr(mc.players, "set" + c["kind"])(target(c.get("target", "$self")), c["value"])
        if op == "effectAdd":
            selected = target(c.get("target", "$self"))
            effect = getattr(effects, c.get("effect", "SPEED"))
            if c.get("named"):
                return mc.effects.add(selected, effect, duration=c.get("duration", 100), level=c.get("level", 200))
            return mc.effects.add(selected, effect, c.get("duration", 100), c.get("level", 200))
        if op == "effectRemove": return mc.effects.remove(target(c.get("target", "$self")), effects.SPEED)
        if op == "effectClear": return mc.effects.clear(target(c.get("target", "$self")))
        if op == "pos":
            selected = target(c.get("target", "$self")); position = c["position"]
            if c.get("entry") == "players": return mc.players.setPos(selected, *position)
            if c.get("entry") == "teleport": return mc.players.teleport(selected, *position)
            return mc.setPos(selected, *position)
        if op == "getPos": return mc.players.getPos(target(c.get("target", "$self")))
        if op == "rules":
            return [{"name": name, "key": value.key, "type": "bool" if value.valueType is bool else "int",
                     "default": value.defaultValue}
                    for name in gamerule.__all__ if isinstance(value := getattr(gamerule, name), GameRuleKey)]
        if op in ("getRule", "setRule"):
            rule = getattr(gamerule, c["constant"]) if "constant" in c else c["rule"]
            if c.get("forgeBool"): rule = GameRuleKey(c["rule"], bool, False)
            if op == "getRule": return mc.worlds.getGameRule(rule)
            return mc.worlds.setGameRule(rule, c["value"])
        if op == "getTime": return mc.worlds.getTime()
        if op == "setTime": return mc.worlds.setTime(c["value"])
        if op == "getWeather": return mc.worlds.getWeather()
        if op == "setWeather": return mc.worlds.setWeather(c["value"])
        if op == "contextManager":
            with Minecraft.create("127.0.0.1", args.port) as temporary:
                temporary.setBlock(*c["position"], block.COBBLESTONE)
                temporary.postToChat("v03-i01-context-close")
                info = temporary.server.getInfo()
            assert temporary._transport.closed
            notes = []
            try:
                with Minecraft.create("127.0.0.1", args.port) as invalid:
                    invalid.setBlock(128, 320, 128, block.COBBLESTONE)
                    raise ValueError("body-sentinel")
            except ValueError as original:
                assert str(original) == "body-sentinel"
                notes = list(getattr(original, "__notes__", ()))
            assert notes and invalid._transport.closed
            return {"info": info, "closed": temporary._transport.closed, "preservedBody": True, "notes": notes}
        if op == "close":
            mc.close(); mc.close()
            return {"remainingThreads": [thread.name for thread in threading.enumerate() if thread.ident not in baseline]}
        raise AssertionError("Unknown bounded worker operation")

    emit({"type": "ready", "result": perform({"op": "info"})})
    try:
        for line in sys.stdin:
            assert len(line) < 16384
            command = json.loads(line)
            try: emit({"type": "result", "id": command["id"], "result": perform(command)})
            except Exception as error: emit({"type": "result", "id": command["id"], "error": failure(error)})
            if command["op"] == "close": break
    finally:
        try: mc.close()
        except Exception: pass


if __name__ == "__main__": main()
