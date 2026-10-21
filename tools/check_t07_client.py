"""Isolated installed-wheel client used only by the T07 Paper smoke harness.

Production calls below use the public facade. Private negotiated metadata is
read solely to correlate the two test processes with the independent fixture.
The lesson token is read from the environment and never sent to stdout.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import minebridge
from minebridge import Minecraft, block
from minebridge.models import BlockSpec


def publish(value: dict) -> None:
    print(json.dumps(value, allow_nan=False, separators=(",", ":")), flush=True)


def block_argument(description: dict) -> object:
    kind, value = description["kind"], description["value"]
    if kind == "constant":
        if value not in ("AIR", "STONE", "COBBLESTONE"):
            raise ValueError("Unknown smoke constant")
        return getattr(block, value)
    if kind == "spec":
        return BlockSpec(value)
    if kind in ("id", "key"):
        return value
    raise ValueError("Unknown smoke block argument")


def main() -> None:
    package_path = Path(minebridge.__file__).resolve()
    source_path = Path(__file__).resolve().parents[1] / "python/src"
    if package_path.is_relative_to(source_path):
        raise RuntimeError("Smoke must use an installed wheel")
    mode = os.environ["MINEBRIDGE_T07_AUTH_MODE"]
    options: dict = {"timeout": 3.0}
    if mode == "explicit":
        options["token"] = os.environ["MINEBRIDGE_T07_EXPLICIT_TOKEN"]
    elif mode != "environment":
        raise RuntimeError("Unknown smoke authentication mode")
    mc = Minecraft.create("127.0.0.1", int(os.environ["MINEBRIDGE_T07_PORT"]), **options)
    try:
        context = mc._transport.context
        if context is None:
            raise RuntimeError("Facade returned without negotiated metadata")
        publish({"ready": True, "sessionId": context.session_id,
                 "world": {"name": context.world.name, "uuid": context.world.uuid,
                           "minY": context.world.min_y,
                           "maxYExclusive": context.world.max_y_exclusive},
                 "python": sys.version.split()[0], "package": str(package_path),
                 "pid": os.getpid(), "authMode": mode})
        while True:
            line = sys.stdin.readline(4097)
            if not line:
                break
            if len(line) > 4096 or not line.endswith("\n"):
                raise RuntimeError("Unbounded smoke command")
            command = json.loads(line)
            if command.get("op") == "close":
                mc.close()
                mc.close()
                publish({"closed": mc._transport.closed})
                break
            if command.get("op") != "set":
                raise RuntimeError("Unknown smoke command")
            try:
                target = mc if command["route"] == "root" else mc.blocks
                result = target.setBlock(*command["position"], block_argument(command["block"]),
                                         data=command.get("data", 0))
            except Exception as failure:
                # Only class and machine metadata; never exception text, raw
                # peer input, command content or a traceback with credentials.
                publish({"error": type(failure).__name__,
                         "code": getattr(failure, "code", None),
                         "outcome": getattr(failure, "outcome", None),
                         "closed": mc._transport.closed})
            else:
                publish({"ok": True, "returnedNone": result is None,
                         "closed": mc._transport.closed})
    finally:
        mc.close()


if __name__ == "__main__":
    try:
        main()
    except BaseException as failure:
        publish({"fatal": type(failure).__name__})
        raise SystemExit(1) from None
