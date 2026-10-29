"""Isolated installed SDK worker for the 0.3.1 native acceptance fixture."""

import argparse
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
import json
import os
from pathlib import Path
import sys
import threading
import time
from uuid import UUID

import minebridge
from minebridge import Minecraft, effects, entity, items, selector
from minebridge.models import BlockSpec


def evidence(value):
    if is_dataclass(value):
        return {field.name: evidence(getattr(value, field.name)) for field in fields(value)
                if not field.name.startswith("_")}
    if isinstance(value, UUID): return str(value)
    if isinstance(value, Mapping): return {str(key): evidence(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)): return [evidence(item) for item in value]
    return value


def failure(error):
    return {"type": type(error).__name__, "message": str(error),
            **{key: getattr(error, key) for key in ("code", "outcome", "method", "request_id") if hasattr(error, key)}}


def emit(value):
    print(json.dumps(evidence(value), ensure_ascii=True, allow_nan=False), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--player")
    args = parser.parse_args()
    package = Path(minebridge.__file__).resolve()
    assert minebridge.__version__ == args.version and "site-packages" in package.parts
    assert sys.flags.isolated and "MINEBRIDGE_TOKEN" not in os.environ
    baseline = {thread.ident for thread in threading.enumerate()}
    options = {} if args.player is None else {"player": args.player}
    mc = Minecraft.create("127.0.0.1", args.port, **options)
    info = mc._transport.context

    def group(target):
        return {"give": mc.players.giveItem(target, items.EMERALD, 3),
                "effect": mc.effects.add(target, effects.SPEED, 30, 2)}

    def perform(command):
        op = command["op"]
        if op == "region":
            material = BlockSpec(command.get("key", "minecraft:stone"), command.get("states", {}))
            started = time.perf_counter()
            mc.setBlocks(*command["from"], *command["to"], material)
            sent = time.perf_counter()
            mc.flush()
            finished = time.perf_counter()
            volume = 1
            for a, b in zip(command["from"], command["to"]): volume *= abs(b-a)+1
            return {"volume": volume, "seconds": finished-started, "enqueueSeconds": sent-started,
                    "startedAt": started, "finishedAt": finished, "acknowledged": True}
        if op == "getBlock": return mc.getBlock(*command.get("position", [128,209,128]))
        if op == "getBlockSpec": return mc.blocks.getBlock(*command["position"])
        if op == "named":
            target = selector.playerByName(command["name"])
            result = group(target)
            result["selector"] = str(target)
            result["teleport"] = mc.setPos(target, *command["position"])
            inventory = mc.inventories.ofPlayer(target)
            result["slotWrite"] = inventory.setItem(2, items.DIAMOND, 4)
            result["slot"] = inventory.getItem(2)
            result["position"] = mc.players.getPos(target)
            return result
        if op == "namedMissing":
            target = selector.playerByName(command["name"])
            result = group(target)
            result["teleport"] = mc.setPos(target, 160.5, 210, 128.5)
            for name, operation in (("positionError", lambda: mc.players.getPos(target)),
                                    ("inventoryError", lambda: mc.inventories.ofPlayer(target))):
                try: operation()
                except Exception as error: result[name] = failure(error)
                else: raise AssertionError("Missing singleton target unexpectedly succeeded")
            return result
        if op == "spawn": return mc.spawnEntity(*command["position"], getattr(entity, command["entity"]))
        if op == "close":
            mc.close()
            return {"remainingThreads": [thread.name for thread in threading.enumerate() if thread.ident not in baseline]}
        raise AssertionError("Unexpected bounded fixture operation")

    emit({"type":"ready", "info":{"pid":os.getpid(), "python":sys.version, "version":minebridge.__version__,
          "package":str(package), "isolated":bool(sys.flags.isolated), "sessionId":info.session_id,
          "pluginVersion":info.plugin_version,
          "world":{"uuid":info.world.uuid, "name":info.world.name}, "player":args.player}})
    try:
        for line in sys.stdin:
            assert len(line) < 16384
            command = json.loads(line)
            try: emit({"type":"result", "id":command["id"], "result":perform(command)})
            except Exception as error: emit({"type":"result", "id":command["id"], "error":failure(error)})
            if command["op"] == "close": break
    finally:
        mc.close()


if __name__ == "__main__": main()
