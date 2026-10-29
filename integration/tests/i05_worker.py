"""I05 installed-wheel process; its bounded stdin pipe is test orchestration only."""

from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
import json
import os
from pathlib import Path
import sys
import threading
import time
from uuid import UUID

import minebridge
from minebridge import Minecraft, block, effects, entity, items, selector
from minebridge.models import BlockSpec, ItemStack


def evidence(value):
    if is_dataclass(value):
        return evidence(asdict(value))
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): evidence(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [evidence(item) for item in value]
    return value


def failure(value):
    return {"type": type(value).__name__, "code": getattr(value, "code", None),
            "outcome": getattr(value, "outcome", None),
            "method": getattr(value, "method", None),
            "requestId": getattr(value, "request_id", None),
            "failures": len(getattr(value, "failures", ()))}


def publish(value):
    print(json.dumps(evidence(value), allow_nan=False), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--player")
    parser.add_argument("--mode", default="buffered")
    args = parser.parse_args()
    package = Path(minebridge.__file__).resolve()
    root = Path(__file__).resolve().parents[2]
    assert not package.is_relative_to(root / "python/src"), package
    assert minebridge.__version__ == "0.2.0", minebridge.__version__
    baseline = {thread.ident for thread in threading.enumerate()}
    # No token or world option: exactly two positional connection arguments.
    options = {"writeMode": args.mode} if args.mode != "buffered" else {}
    if args.player:
        options["player"] = args.player
    mc = Minecraft.create("127.0.0.1", args.port, **options)
    refs = {}

    def describe():
        context = mc._transport.context
        return {"pid": os.getpid(), "package": str(package), "version": minebridge.__version__,
                "python": sys.version.split()[0], "sessionId": context.session_id,
                "world": {"name": context.world.name, "uuid": context.world.uuid,
                          "key": context.world.key}, "capabilities": context.capabilities,
                "nextRequestId": mc._transport._next_id,
                "tokenEnvironmentAbsent": "MINEBRIDGE_TOKEN" not in os.environ}

    def target(value):
        if isinstance(value, list):
            return [refs[key] for key in value]
        return value

    def perform(c):
        nonlocal mc
        op = c["op"]
        if op == "describe":
            return describe()
        if op == "blocks":
            y = c["y"]
            mc.setBlock(128, y, 128, 4)
            assert mc.getBlock(128, y, 128) == 4
            mc.blocks.setBlock(129, y, 128, block.STONE)
            assert mc.blocks.getBlock(129, y, 128).key == "minecraft:stone"
            mc.setBlocks(159, y, 143, 128, y, 128, block.COBBLESTONE)
            values = mc.getBlocks(159, y, 143, 128, y, 128)
            assert values == {(x, y, z): 4 for x in range(128, 160) for z in range(128, 144)}
            modern = mc.blocks.getBlocks(128, y, 128, 159, y, 143)
            assert set(modern) == set(values) and all(v.key == "minecraft:cobblestone" for v in modern.values())
            mc.blocks.setBlocks(-15.2, y, -15.2, -16.2, y, -16.2, 1)
            assert mc.getBlocks(-16, y, -16, -17, y, -17) == {
                (x, y, z): 1 for x in (-17, -16) for z in (-17, -16)}
            mc.setBlock(128, y + 2, 128, block.OAK_STAIRS.withStates(facing="east", half="top"))
            mc.setBlock(130, y + 2, 128, "minecraft:oak_log[axis=x]")
            stairs, log = mc.blocks.getBlock(128, y + 2, 128), mc.blocks.getBlock(130, y + 2, 128)
            assert stairs.states["facing"] == "east" and stairs.states["half"] == "top"
            assert log.states["axis"] == "x"
            return {"legacyRegionCount": len(values), "modernRegionCount": len(modern),
                    "stairs": {"key": stairs.key, "states": dict(stairs.states)},
                    "log": {"key": log.key, "states": dict(log.states)}}
        if op in ("set", "setBlocks"):
            if op == "set":
                mc.setBlock(*c["position"], c.get("block", 4))
            else:
                mc.setBlocks(*c["from"], *c["to"], c.get("block", 4))
            if c.get("flush", True):
                mc.flush()
            return {"sent": True}
        if op == "far":
            started = time.perf_counter()
            original = mc.blocks.getBlock(*c["position"])
            mc.setBlock(*c["position"], block.COBBLESTONE)
            assert mc.getBlock(*c["position"]) == 4
            return {"originalKey": original.key, "seconds": time.perf_counter() - started}
        if op == "benchmark":
            rows = []
            for repeat in range(c.get("repeats", 1)):
                started = time.perf_counter()
                for index in range(c["count"]):
                    mc.setBlock(128 + index % 32, c["y"], 128 + index // 32,
                                block.COBBLESTONE if repeat % 2 == 0 else block.STONE)
                sent = time.perf_counter()
                mc.flush()
                rows.append({"count": c["count"], "enqueueSeconds": sent - started,
                             "completedSeconds": time.perf_counter() - started})
            return rows
        if op == "players":
            players = mc.players.list(c.get("target", selector.ALL_PLAYERS))
            for player in players:
                refs[player.name] = player
            return players
        if op == "getPlayer":
            player = mc.players.get(c["target"])
            refs[player.name] = player
            return {"player": player, "rootId": mc.getPlayerEntityId(player.name)}
        if op == "position":
            return mc.players.getPos(target(c.get("target", "@s")))
        if op == "teleport":
            return mc.players.teleport(target(c.get("target", "@s")), *c["position"], world=c.get("world"))
        if op == "context":
            other = mc.withContext(player=c["player"])
            original = mc.players.list(selector.SELF)
            rebound = other.players.list(selector.SELF)
            cleared = other.withContext()
            try:
                cleared.players.list(selector.SELF)
            except Exception as error:
                missing = failure(error)
            else:
                raise AssertionError("Cleared context accepted SELF")
            return {"original": original, "rebound": rebound, "cleared": missing}
        if op == "give":
            value = getattr(items, c.get("item", "IRON_SWORD"))
            if c.get("name"):
                value = ItemStack(value, name=c["name"], lore=("I05", "Literal <red> text"))
            return mc.players.giveItem(target(c.get("target", "@s")), value, c.get("amount"),
                                       overflow=c.get("overflow", "return"))
        if op == "effect":
            return mc.effects.add(target(c.get("target", "@s")), getattr(effects, c.get("effect", "SPEED")),
                                  duration=c.get("duration", 30), level=c.get("level", 2), particles=False)
        if op == "spawn":
            options = {}
            if c.get("item"):
                options["item"] = ItemStack(getattr(items, c["item"]), amount=c.get("amount", 1))
            if c.get("block"):
                options["block"] = BlockSpec(c["block"], c.get("states", {}))
            if c.get("face"):
                options["face"] = c["face"]
            if c.get("owner"):
                options["owner"] = c["owner"]
            if c.get("modernRoute"):
                value = mc.entities.spawn(getattr(entity, c["entity"]), *c["position"], **options)
            else:
                value = mc.spawnEntity(*c["position"], getattr(entity, c["entity"]), **options)
            refs[c.get("ref", c["entity"])] = value
            return value
        if op == "chat":
            mc.postToChat(c["message"])
            mc.flush()
            return None
        if op == "flush":
            mc.flush()
            return None
        if op == "read":
            return mc.getBlock(*c["position"])
        if op == "deferred":
            mc.setBlock(*c["position"], "minecraft:i05_unknown_block")
            # The parent has armed a pre-dequeue gate. This signal proves that
            # buffering returned before the invalid mutation was dispatched.
            publish({"type": "buffered", "id": c["id"]})
            if c["barrier"] == "write":
                path = Path(c["gate"])
                deadline = time.monotonic() + 15
                while not path.exists():
                    assert time.monotonic() < deadline, "Deferred-error barrier timed out"
                    time.sleep(.005)
                # This diagnostic wait establishes arrival of the deferred
                # error; the assertion itself remains the next public write.
                with mc._transport._condition:
                    assert mc._transport._condition.wait_for(
                        lambda: bool(mc._transport._failures), timeout=5), "Deferred reply did not arrive"
                mc.setBlock(*c["position"], 4)
            elif c["barrier"] == "flush":
                mc.flush()
            elif c["barrier"] == "read":
                mc.getBlock(*c["position"])
            else:
                mc.close()
            raise AssertionError("Deferred invalid block was silently accepted")
        if op == "close":
            mc.close()
            mc.close()
            return {"remainingThreads": [thread.name for thread in threading.enumerate()
                                         if thread.ident not in baseline]}
        raise AssertionError("Unknown bounded worker operation")

    publish({"type": "ready", "result": describe()})
    try:
        for line in sys.stdin:
            assert len(line) < 16384, "Oversized worker command"
            command = json.loads(line)
            started = time.perf_counter()
            started_ns = time.monotonic_ns()
            try:
                result = perform(command)
                publish({"type": "result", "id": command["id"], "result": result,
                         "seconds": time.perf_counter() - started,
                         "startedNs": started_ns, "finishedNs": time.monotonic_ns()})
            except Exception as error:
                publish({"type": "result", "id": command["id"], "error": failure(error),
                         "seconds": time.perf_counter() - started,
                         "startedNs": started_ns, "finishedNs": time.monotonic_ns()})
            if command["op"] == "close":
                break
    finally:
        try:
            mc.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
