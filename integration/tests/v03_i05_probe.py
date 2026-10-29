"""Isolated installed-package release probes, also runnable with the old0.2.1 wheel."""

import argparse
import json
from pathlib import Path
import sys
import time
import minebridge
from minebridge.minecraft import Minecraft
from minebridge import block


def emit(value): print(json.dumps(value, ensure_ascii=True), flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("op", choices=("short", "legacy", "benchmark", "fresh"))
    p.add_argument("--port", required=True, type=int)
    p.add_argument("--expect-version", default="0.3.0")
    p.add_argument("--marker", default="i05-short")
    args = p.parse_args()
    package = Path(minebridge.__file__).resolve()
    assert "site-packages" in package.parts and minebridge.__version__ == args.expect_version
    mc = Minecraft.create("127.0.0.1", args.port)
    info = {"package": str(package), "version": minebridge.__version__, "python": sys.version,
            "sessionId": mc._transport.context.session_id, "isolated": bool(sys.flags.isolated)}
    if args.op == "short":
        emit({"type": "ready", "info": info}); sys.stdin.readline()
        mc.setBlock(132, 210, 128, 4)
        mc.postToChat(args.marker)
        return  # Explicitly no close/finally/flush: normal-exit hook is under test.
    try:
        if args.op == "legacy":
            from minebridge import effects, entity, items, selector
            runtime_id = mc.getPlayerEntityId("I05Alice")
            mc.setBlock(134, 210, 128, 4)
            mc.setBlocks(134, 210, 129, 136, 210, 129, block.COBBLESTONE)
            me = mc.withContext(player="I05Alice")
            effect=me.effects.add(selector.SELF, effects.SPEED, duration=2, level=1)
            gift = me.players.giveItem(selector.SELF, items.EMERALD, 2)
            spawned = me.spawnEntity(136, 211, 128, entity.COW)
            mc.postToChat(args.marker)
            emit({"info": info, "runtimeId": runtime_id, "block": mc.getBlock(134, 210, 128),
                  "giftApplied": gift.applied, "effectApplied":effect.applied,"spawned": str(spawned.uuid)})
        elif args.op == "fresh":
            mc.setBlock(0, 0, 0, block.COBBLESTONE)
            mc.flush()
            context = mc._transport.context
            emit({"info": info, "block": mc.getBlock(0, 0, 0),
                  "world": {"uuid": context.world.uuid, "name": context.world.name}})
        else:
            mc.setBlocks(256, 210, 128, 287, 210, 159, block.AIR); mc.flush()
            for i in range(1000):
                mc.setBlock(256 + i % 32, 210, 128 + i // 32 % 32, block.STONE)
            mc.flush()  # Identical untimed streaming warmup for each isolated SDK process.
            results = []
            for n in (100, 1000):
                for repeat in range(3):
                    material = block.COBBLESTONE if repeat % 2 == 0 else block.STONE
                    started = time.perf_counter()
                    for i in range(n): mc.setBlock(256 + i % 32, 210, 128 + i // 32 % 32, material)
                    mc.flush()
                    results.append({"blocks": n, "repeat": repeat, "seconds": time.perf_counter() - started})
            emit({"info": info, "measurements": results, "untimedWarmupBlocks":1000})
    finally:
        mc.close()


if __name__ == "__main__": main()
