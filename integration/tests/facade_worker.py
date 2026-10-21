"""Isolated installed-wheel public client; stdin is a bounded test control pipe."""

from __future__ import annotations

import json
import os
from dataclasses import fields
from pathlib import Path
import sys
import threading

import minebridge
from minebridge import Minecraft, block
from minebridge.models import BlockSpec, LegacyBlock

OUTPUT_LOCK = threading.Lock()


def publish(value: dict) -> None:
    with OUTPUT_LOCK:
        print(json.dumps(value, allow_nan=False, separators=(",", ":")), flush=True)


def main() -> None:
    package = Path(minebridge.__file__).resolve()
    root = Path(__file__).resolve().parents[2]
    if package.is_relative_to(root / "python/src"):
        raise RuntimeError("An installed wheel is required")
    port = int(os.environ.get("MINEBRIDGE_TEST_PORT", "4711"))
    timeout = float(os.environ.get("MINEBRIDGE_TEST_TIMEOUT", "30.0"))
    mc = Minecraft.create("127.0.0.1", port, timeout=timeout)
    worker: threading.Thread | None = None
    call_finished = threading.Event()
    try:
        def describe(event_type: str) -> dict:
            context = mc._transport.context  # Test correlation only; all writes use public API.
            limits = {}
            for field in fields(context.limits):
                first, *rest = field.name.split("_")
                key = first + "".join(word.title() for word in rest)
                limits[key] = json.loads(getattr(context.limits, field.name).text)
            return {"type": event_type, "pid": os.getpid(), "sessionId": context.session_id,
                    "world": {"name": context.world.name, "uuid": context.world.uuid,
                              "minY": context.world.min_y,
                              "maxYExclusive": context.world.max_y_exclusive},
                    "protocol": {"major": context.protocol.major, "minor": context.protocol.minor},
                    "coordinates": context.coordinates, "chunkPolicy": context.chunk_policy,
                    "applyPhysics": context.apply_physics, "capabilities": list(context.capabilities),
                    "limits": limits, "package": str(package), "python": sys.version.split()[0]}

        def failure_details(failure: Exception) -> dict:
            return {"error": type(failure).__name__, "code": getattr(failure, "code", None),
                    "outcome": getattr(failure, "outcome", None)}

        publish(describe("ready"))

        def perform(command: dict) -> None:
            try:
                target = mc.blocks if command.get("route") == "blocks" else mc
                material = command["material"]
                form = command.get("form", "constant")
                if form == "constant":
                    value = getattr(block, material)
                elif form == "numeric":
                    value = material
                elif form == "legacy":
                    value = LegacyBlock(material, command.get("legacyData", 0))
                elif form == "modern":
                    value = material
                elif form == "spec":
                    value = BlockSpec(material)
                else:
                    raise RuntimeError("Unexpected fixture material form")
                result = target.setBlock(*command["position"], value, command.get("data", 0))
                completed = {"type": "result", "commandId": command["commandId"],
                             "ok": True, "returnedNone": result is None}
            except Exception as failure:
                completed = {"type": "result", "commandId": command["commandId"],
                             "ok": False, **failure_details(failure)}
            call_finished.set()
            publish(completed)

        while True:
            line = sys.stdin.readline(4097)
            if not line:
                break
            if len(line) > 4096 or not line.endswith("\n"):
                raise RuntimeError("Unbounded test command")
            command = json.loads(line)
            operation = command.get("op")
            if operation == "pending":
                publish({"type": "pending", "probeId": command["probeId"],
                         "pending": worker is not None and worker.is_alive() and not call_finished.is_set()})
                continue
            if operation == "reopen":
                if worker is not None:
                    worker.join(timeout=5)
                    if worker.is_alive():
                        raise RuntimeError("Cannot reopen during a public call")
                old_session = mc._transport.context.session_id
                mc.close()
                mc.close()
                old_closed = mc._transport.closed
                try:
                    mc.setBlock(*command["position"], block.COBBLESTONE)
                except Exception as failure:
                    closed_write = failure_details(failure)
                else:
                    raise RuntimeError("Closed public object accepted a write")
                mc = Minecraft.create("127.0.0.1", port, timeout=timeout)
                publish({**describe("reopened"), "oldSessionId": old_session,
                         "oldClosed": old_closed, "closedWrite": closed_write})
                continue
            if operation == "close":
                mc.close()
                mc.close()
                if worker is not None:
                    worker.join(timeout=5)
                    if worker.is_alive():
                        raise RuntimeError("Pending public call survived close")
                publish({"type": "closed", "closed": mc._transport.closed})
                break
            if operation != "set":
                raise RuntimeError("Unexpected test operation or concurrent public calls")
            if worker is not None:
                # A result line can arrive just before the publishing thread
                # actually exits. Join that completion before the next call.
                worker.join(timeout=5)
                if worker.is_alive():
                    raise RuntimeError("Unexpected concurrent public calls")
            call_finished.clear()
            worker = threading.Thread(target=perform, args=(command,), daemon=True)
            worker.start()
    finally:
        mc.close()
        if worker is not None:
            worker.join(timeout=5)


if __name__ == "__main__":
    try:
        main()
    except BaseException as failure:
        publish({"type": "fatal", "error": type(failure).__name__})
        raise SystemExit(1) from None
