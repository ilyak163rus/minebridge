"""One source-only SDK process, controlled independently from the game client."""

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

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python/src"))
import minebridge
from minebridge import Minecraft, events, block, items, selector
from minebridge.models import EventType, Region


def evidence(value):
    if is_dataclass(value):
        result = {field.name: evidence(getattr(value, field.name)) for field in fields(value)}
        if hasattr(value, "eventId") and hasattr(value, "player") and "player" not in result:
            result["player"] = evidence(value.player)
        return result
    if isinstance(value, UUID): return str(value)
    if isinstance(value, Mapping): return {str(k): evidence(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)): return [evidence(v) for v in value]
    return value


def batch(value):
    return {"events": evidence(list(value)), "metadata": {k: evidence(getattr(value, k))
            for k in ("hasMore", "nextCursor", "upperBound", "availableFrom", "sessionStart", "windowLimited") if hasattr(value, k)}}


def failure(error):
    return {"type": type(error).__name__, "code": getattr(error, "code", None),
            "outcome": getattr(error, "outcome", None), "source": getattr(error, "source", None)}


def emit(value): print(json.dumps(evidence(value), ensure_ascii=True, allow_nan=False), flush=True)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--port", type=int, required=True); parser.add_argument("--player", required=True)
    args = parser.parse_args()
    assert minebridge.__version__ == "0.3.0.dev3"
    package = Path(minebridge.__file__).resolve(); assert package.is_relative_to(ROOT / "python/src")
    baseline = {t.ident for t in threading.enumerate()}
    mc = Minecraft.create("127.0.0.1", args.port, player=args.player)
    records, run_errors, subscriptions = [], [], {}
    lock = threading.Condition(); consumer = None

    def state():
        with lock: return {"records": list(records), "runErrors": list(run_errors), "runAlive": consumer is not None and consumer.is_alive()}

    def run():
        try: mc.events.run()
        except Exception as error:
            with lock: run_errors.append(failure(error))
        finally:
            with lock: lock.notify_all()

    def join():
        if consumer is not None:
            consumer.join(timeout=10); assert not consumer.is_alive()

    def perform(c):
        nonlocal consumer
        op = c["op"]; event_type = EventType(c.get("type", "chat.message"))
        if op == "info": return {"pid": os.getpid(), "info": mc.server.getInfo(), "package": str(package), "version": minebridge.__version__}
        if op == "subscribe":
            label = c["label"]; assert label not in subscriptions
            def handler(event):
                row = {"label": label, "event": evidence(event), "thread": threading.current_thread().name}
                if c.get("action"):
                    row["readback"] = mc.getBlock(*c.get("read", [128, 209, 128]))
                    row["gift"] = evidence(mc.players.giveItem(event.player, items.DIAMOND, 1))
                with lock: records.append(row); lock.notify_all()
            selected = c.get("players", "@a")
            if selected == "$self": selected = selector.SELF
            options = {"players": selected}
            if "region" in c:
                value = c["region"]; options["region"] = Region(UUID(value["world"]), value["min"], value["max"])
            if "blocks" in c: options["blocks"] = c["blocks"]
            subscriptions[label] = mc.events.subscribe(event_type, handler, **options)
            return {"id": subscriptions[label].id, "world": subscriptions[label].world}
        if op == "unsubscribe": subscriptions.pop(c["label"]).unsubscribe(); return {"done": True}
        if op == "startRun":
            assert consumer is None or not consumer.is_alive()
            consumer = threading.Thread(target=run, name="i03-explicit-callback-consumer"); consumer.start(); return {"started": True}
        if op == "stopRun": mc.events.stop(); join(); return state()
        if op == "state": return state()
        if op == "waitRecords":
            deadline = time.monotonic() + c.get("timeout", 10)
            with lock:
                while len([r for r in records if c.get("label") is None or r["label"] == c["label"]]) < c["count"] and not run_errors:
                    left = deadline - time.monotonic(); assert left > 0, "I03 callback deadline"; lock.wait(left)
            result = state(); assert not result["runErrors"], result
            return result
        if op == "poll":
            reader = mc.events if "player" not in c else mc.withContext(player=c["player"]).events
            if "alias" in c: return batch(getattr(reader, c["alias"])(limit=c.get("limit", 1000)))
            return batch(reader.pollEvents(event_type, limit=c.get("limit", 1000)))
        if op == "recent": return batch(mc.events.getRecent(event_type, limit=c.get("limit", 1000)))
        if op == "clear": mc.events.clearPending(None if c.get("all") else event_type); return {"cleared": True}
        if op == "setBlock":
            mc.setBlock(*c["position"], c.get("block", "minecraft:cobblestone")); mc.flush(); return {"flushed": True}
        if op == "getBlock": return mc.getBlock(*c["position"])
        if op == "close":
            mc.close(); join(); return {"state": state(), "remainingThreads": [t.name for t in threading.enumerate() if t.ident not in baseline]}
        raise AssertionError("Unknown bounded I03 worker operation")

    emit({"type": "ready", "result": perform({"op": "info"})})
    try:
        for line in sys.stdin:
            assert len(line) < 16384; command = json.loads(line)
            try: emit({"type": "result", "id": command["id"], "result": perform(command)})
            except Exception as error: emit({"type": "result", "id": command["id"], "error": failure(error)})
            if command["op"] == "close": break
    finally: mc.close(); join()


if __name__ == "__main__": main()
