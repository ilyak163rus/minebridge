"""Final installed-wheel worker: explicit event consumer and independent stdin control."""

import argparse
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import threading
import time
from uuid import UUID

import minebridge
from minebridge import Minecraft, block, effects, events, gamemode, gamerule, items, selector, weather
from minebridge.models import EventType


def evidence(value):
    if is_dataclass(value):
        return {field.name: evidence(getattr(value, field.name)) for field in fields(value)
                if not field.name.startswith("_")}
    if isinstance(value, UUID): return str(value)
    if isinstance(value, Mapping): return {str(key): evidence(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)): return [evidence(item) for item in value]
    return value


def failure(error):
    result = {"type": type(error).__name__}
    for key in ("code", "outcome", "method", "source", "lostCount", "subscriptionIds", "reason", "availableFrom", "tail"):
        if hasattr(error, key): result[key] = evidence(getattr(error, key))
    return result


def emit(value): print(json.dumps(evidence(value), ensure_ascii=True, allow_nan=False), flush=True)


def batch(value):
    return {"events": evidence(list(value)), "metadata": {key: evidence(getattr(value, key))
            for key in ("hasMore", "nextCursor", "upperBound", "availableFrom", "sessionStart", "windowLimited")
            if hasattr(value, key)}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--player")
    parser.add_argument("--logging", action="store_true")
    args = parser.parse_args()
    package = Path(minebridge.__file__).resolve()
    assert minebridge.__version__ == importlib.metadata.version("minebridge") == "0.3.0"
    assert "site-packages" in package.parts and "python" not in package.parts[-4:-2], package
    baseline = {thread.ident for thread in threading.enumerate()}
    mc = Minecraft.create("127.0.0.1", args.port, player=args.player, logging=args.logging)
    gate = threading.Event(); gate.set()
    condition = threading.Condition()
    subscriptions, refs, counts, latest = {}, {}, {}, {}
    samples, run_errors = [], []
    consumer = None
    blocked = False

    def state():
        with condition:
            return {"counts": dict(counts), "latest": dict(latest), "samples": list(samples),
                    "runErrors": list(run_errors), "runAlive": consumer is not None and consumer.is_alive(),
                    "handlerBlocked": blocked}

    def consume():
        try: mc.events.run()
        except Exception as error:
            with condition: run_errors.append(failure(error)); condition.notify_all()
        finally:
            with condition: condition.notify_all()

    def join_consumer():
        if consumer is not None:
            consumer.join(timeout=15)
            assert not consumer.is_alive(), "Explicit event consumer did not finish"

    def remember(label, event, extra=None):
        row = {"label": label, "event": evidence(event), "thread": threading.current_thread().name,
               **(extra or {})}
        with condition:
            counts[label] = counts.get(label, 0) + 1
            latest[label] = row
            if len(samples) < 64: samples.append(row)
            condition.notify_all()

    def perform(c):
        nonlocal consumer, blocked
        op = c["op"]; kind = EventType(c.get("type", "chat.message"))
        if op == "info":
            return {"pid": os.getpid(), "package": str(package), "version": minebridge.__version__,
                    "info": mc.server.getInfo(), "tokenEnvironmentAbsent": "MINEBRIDGE_TOKEN" not in os.environ,
                    "pythonVersion": sys.version, "isolated": bool(sys.flags.isolated)}
        if op == "subscribe":
            label, mode = c["label"], c.get("mode", "record")
            assert label not in subscriptions
            def handler(event):
                nonlocal blocked
                if c.get("message") is not None and getattr(event, "message", None) != c["message"]:
                    return
                if mode == "blocked":
                    with condition: blocked = True
                    remember(label, event, {"entered": True})
                    gate.wait()
                    with condition: blocked = False; condition.notify_all()
                    return
                extra = {}
                if mode == "chat-action":
                    inventory = mc.inventories.ofPlayer(event.player)
                    extra["slot"] = evidence(inventory.setItem(2, items.DIAMOND, 4))
                    extra["chest"] = evidence(refs["chest"].setItem(0, items.EMERALD, 3))
                    extra["block"] = mc.getBlock(128, 209, 128)
                    mc.postToChat("i05-reward-ack"); mc.flush()
                elif mode == "block-action":
                    extra["slot"] = evidence(mc.inventories.ofPlayer(event.player).setItem(3, items.COMPASS, 1))
                elif mode == "lava-action":
                    extra["slot"] = evidence(mc.inventories.ofPlayer(event.player).setItem(4, items.EMERALD, 1))
                    extra["teleport"] = evidence(mc.setPos(event.player, 128.5, 210, 128.5))
                remember(label, event, extra)
                if mode == "raise": raise ValueError("intentional fixture handler exception")
            selection = c.get("players", "@a")
            if selection == "$self": selection = selector.SELF
            if mode == "blocked": gate.clear()
            subscriptions[label] = mc.events.subscribe(kind, None if mode == "manual" else handler,
                                                      players=selection)
            return {"id": subscriptions[label].id, "world": subscriptions[label].world}
        if op == "unsubscribe":
            subscriptions.pop(c["label"]).unsubscribe(); return {"unsubscribed": True}
        if op == "startRun":
            assert consumer is None or not consumer.is_alive()
            with condition: run_errors.clear()
            consumer = threading.Thread(target=consume, name="i05-explicit-event-consumer")
            consumer.start(); return {"started": True}
        if op == "stopRun":
            mc.events.stop()
            if c.get("join", True): join_consumer()
            return state()
        if op == "release": gate.set(); return {"released": True}
        if op == "state": return state()
        if op == "waitCount":
            deadline = time.monotonic() + c.get("timeout", 15)
            with condition:
                while counts.get(c["label"], 0) < c["count"] and not run_errors:
                    left = deadline - time.monotonic(); assert left > 0, state(); condition.wait(left)
            result = state(); assert not result["runErrors"], result
            return result
        if op == "waitRunEnd": join_consumer(); return state()
        if op == "pollLive": return mc.events.poll(timeout=c.get("timeout", 0))
        if op == "poll":
            reader = mc.events if "context" not in c else mc.withContext(player=c["context"]).events
            return batch(reader.pollChatPosts(limit=c.get("limit", 1000)) if c.get("alias") == "chat"
                         else reader.pollEvents(kind, limit=c.get("limit", 1000)))
        if op == "recent": return batch(mc.events.getRecent(kind, limit=c.get("limit", 20)))
        if op == "clear": mc.events.clearPending(None if c.get("all") else kind); return {"cleared": True}
        if op == "setBlock":
            mc.setBlock(*c.get("position", [128, 209, 128]), c.get("block", "minecraft:cobblestone"))
            mc.flush(); return {"acknowledged": True}
        if op == "getBlock": return mc.getBlock(*c.get("position", [128, 209, 128]))
        if op == "openChest":
            refs[c.get("label", "chest")] = mc.inventories.ofBlock(*c["position"], combined=c.get("combined", False))
            return {"size": refs[c.get("label", "chest")].size, "world": refs[c.get("label", "chest")].world}
        if op == "getSlot": return mc.inventories.ofPlayer(c.get("target", selector.SELF)).getItem(c["slot"])
        if op == "controls":
            mc.players.setGameMode(selector.SELF, gamemode.CREATIVE)
            mc.effects.add(selector.SELF, effects.SPEED, 100, 200)
            mc.worlds.setWeather(weather.CLEAR); mc.worlds.setTime(1000)
            mc.worlds.setGameRule(gamerule.KEEP_INVENTORY, True)
            return {"mode": mc.players.getGameMode(selector.SELF), "time": mc.worlds.getTime(),
                    "weather": mc.worlds.getWeather(), "rule": mc.worlds.getGameRule(gamerule.KEEP_INVENTORY)}
        if op == "clearEffects": return mc.effects.clear(selector.SELF)
        if op == "benchmark":
            output = []
            mc.setBlocks(256, 210, 128, 287, 210, 159, block.AIR); mc.flush()
            for n in c.get("counts", [100, 1000]):
                for repeat in range(c.get("repeats", 3)):
                    started = time.perf_counter()
                    material = block.COBBLESTONE if repeat % 2 == 0 else block.STONE
                    for i in range(n): mc.setBlock(256 + i % 32, 210 + i // 1024, 128 + i // 32 % 32, material)
                    mc.flush(); output.append({"blocks": n, "repeat": repeat, "seconds": time.perf_counter() - started})
            return output
        if op == "close":
            gate.set(); close_error = None
            try: mc.close()
            except Exception as error: close_error = failure(error)
            join_consumer()
            return {"state": state(), "closeError": close_error,
                    "remainingThreads": [t.name for t in threading.enumerate() if t.ident not in baseline]}
        raise AssertionError("Unknown bounded final-release worker operation")

    emit({"type": "ready", "result": perform({"op": "info"})})
    try:
        for line in sys.stdin:
            assert len(line) < 32768
            command = json.loads(line)
            try: emit({"type": "result", "id": command["id"], "result": perform(command)})
            except Exception as error: emit({"type": "result", "id": command["id"], "error": failure(error)})
            if command["op"] == "close": break
    finally:
        gate.set(); mc.close(); join_consumer()


if __name__ == "__main__": main()
