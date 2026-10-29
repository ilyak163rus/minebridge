"""Source-only I02 process: explicit callback consumer plus local stdin control."""

from dataclasses import asdict, is_dataclass
import argparse
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
from minebridge import Minecraft, block, events, items, selector


def evidence(value):
    if is_dataclass(value): return evidence(asdict(value))
    if isinstance(value, UUID): return str(value)
    if isinstance(value, dict): return {str(key): evidence(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)): return [evidence(item) for item in value]
    return value


def failure(value):
    return {"type": type(value).__name__, "code": getattr(value, "code", None),
            "outcome": getattr(value, "outcome", None), "method": getattr(value, "method", None),
            "source": getattr(value, "source", None)}


def emit(value): print(json.dumps(evidence(value), ensure_ascii=True, allow_nan=False), flush=True)


def batch(value):
    return {"events": evidence(list(value)), "metadata": {name: evidence(getattr(value, name))
            for name in ("hasMore", "nextCursor", "upperBound", "availableFrom", "sessionStart", "windowLimited")
            if hasattr(value, name)}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--player", required=True)
    args = parser.parse_args()
    package = Path(minebridge.__file__).resolve()
    assert package.is_relative_to(ROOT / "python/src")
    assert minebridge.__version__ == "0.3.0.dev2"
    baseline = {thread.ident for thread in threading.enumerate()}
    mc = Minecraft.create("127.0.0.1", args.port, player=args.player)
    lock = threading.Condition()
    records, run_errors, subscriptions = [], [], {}
    consumer = None

    def state():
        with lock:
            return {"records": list(records), "runErrors": list(run_errors),
                    "runAlive": consumer is not None and consumer.is_alive()}

    def run():
        try: mc.events.run()
        except Exception as error:
            with lock: run_errors.append(failure(error))
        finally:
            with lock: lock.notify_all()

    def join_consumer():
        if consumer is not None:
            consumer.join(timeout=10)
            assert not consumer.is_alive(), "Event consumer did not wake"

    def perform(c):
        nonlocal consumer
        op = c["op"]
        if op == "info":
            return {"info": mc.server.getInfo(), "pid": os.getpid(), "package": str(package),
                    "version": minebridge.__version__, "tokenEnvironmentAbsent": "MINEBRIDGE_TOKEN" not in os.environ}
        if op == "subscribe":
            label, mode = c["label"], c.get("mode", "record")
            assert label not in subscriptions
            def handler(event):
                row = {"label": label, "event": evidence(event),
                       "threadName": threading.current_thread().name,
                       "threadId": threading.get_ident()}
                if mode == "action" and event.message == c["actionMessage"]:
                    row["block"] = mc.getBlock(128, 209, 128)
                    row["history"] = batch(mc.events.getRecent(events.CHAT_MESSAGE, limit=20))
                    row["gift"] = evidence(mc.players.giveItem(event.player, items.DIAMOND, 1))
                    mc.postToChat(c["ackMessage"])
                    mc.flush()
                    row["acknowledged"] = True
                with lock:
                    records.append(row)
                    lock.notify_all()
                if mode == "raise": raise ValueError("fixture-handler-failed")
                if mode == "stop": mc.events.stop()
            selected = c.get("players", "@a")
            if selected == "$self": selected = selector.SELF
            subscription = mc.events.subscribe(events.CHAT_MESSAGE,
                None if mode == "manual" else handler, players=selected)
            subscriptions[label] = subscription
            return {"id": subscription.id, "eventType": subscription.eventType, "world": subscription.world}
        if op == "unsubscribe":
            value = subscriptions.pop(c["label"])
            value.unsubscribe()
            return {"unsubscribed": True}
        if op == "startRun":
            assert consumer is None or not consumer.is_alive()
            consumer = threading.Thread(target=run, name="i02-explicit-callback-consumer")
            consumer.start()
            return {"started": True, "threadName": consumer.name}
        if op == "stopRun":
            mc.events.stop(); join_consumer(); return state()
        if op == "state": return state()
        if op == "waitRecords":
            deadline = time.monotonic() + c.get("timeout", 10)
            with lock:
                while len(records) < c["count"] and not run_errors:
                    remaining = deadline - time.monotonic()
                    assert remaining > 0, "Callback record deadline"
                    lock.wait(remaining)
            return state()
        if op == "waitRunEnd": join_consumer(); return state()
        if op == "pollLive": return mc.events.poll(timeout=c.get("timeout", 0))
        if op == "poll": return batch(mc.events.pollChatPosts(limit=c.get("limit", 100)))
        if op == "genericPoll": return batch(mc.events.pollEvents(events.CHAT_MESSAGE, limit=c.get("limit", 100)))
        if op == "derivedPoll":
            return batch(mc.withContext(player=c["player"]).events.pollChatPosts(limit=c.get("limit", 100)))
        if op == "recent": return batch(mc.events.getRecent(events.CHAT_MESSAGE, limit=c.get("limit", 20)))
        if op == "clear":
            if c.get("all"): mc.events.clearAll()
            else: mc.events.clearPending(events.CHAT_MESSAGE)
            return {"cleared": True}
        if op == "getBlock": return mc.getBlock(128, 209, 128)
        if op == "setBlock": mc.setBlock(128, 209, 128, block.COBBLESTONE); mc.flush(); return {"flushed": True}
        if op == "chat": mc.postToChat(c["message"]); mc.flush(); return {"flushed": True}
        if op == "close":
            mc.close(); join_consumer(); mc.close()
            return {"state": state(), "remainingThreads": [thread.name for thread in threading.enumerate()
                    if thread.ident not in baseline]}
        raise AssertionError("Unknown bounded I02 worker operation")

    emit({"type": "ready", "result": perform({"op": "info"})})
    try:
        for line in sys.stdin:
            assert len(line) < 16384
            command = json.loads(line)
            try: emit({"type": "result", "id": command["id"], "result": perform(command)})
            except Exception as error: emit({"type": "result", "id": command["id"], "error": failure(error)})
            if command["op"] == "close": break
    finally:
        mc.close(); join_consumer()


if __name__ == "__main__": main()
