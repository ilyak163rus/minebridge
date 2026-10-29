"""Source-only inventory SDK process, independently controlled through stdin."""

import argparse
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
import json
import os
from pathlib import Path
import sys
import threading
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python/src"))
import minebridge
from minebridge import Minecraft, selector
from minebridge.models import ItemStack


def evidence(value):
    if is_dataclass(value): return {f.name: evidence(getattr(value, f.name)) for f in fields(value) if not f.name.startswith("_")}
    if isinstance(value, UUID): return str(value)
    if isinstance(value, Mapping): return {str(k): evidence(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)): return [evidence(v) for v in value]
    return value


def failure(error):
    return {"type": type(error).__name__, "code": getattr(error, "code", None),
            "outcome": getattr(error, "outcome", None), "method": getattr(error, "method", None)}


def emit(value): print(json.dumps(evidence(value), ensure_ascii=True, allow_nan=False), flush=True)


def metadata(ref):
    return {key: evidence(getattr(ref, key)) for key in
            ("kind", "size", "slots", "player", "world", "position", "combined", "layout")}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--port", type=int, required=True); parser.add_argument("--player", required=True)
    args = parser.parse_args()
    assert minebridge.__version__ == "0.3.0.dev4"
    package = Path(minebridge.__file__).resolve(); assert package.is_relative_to(ROOT / "python/src")
    baseline = {thread.ident for thread in threading.enumerate()}
    mc = Minecraft.create("127.0.0.1", args.port, player=args.player)
    refs, player_refs = {}, {}

    def target(value): return selector.SELF if value == "$self" else value

    def perform(c):
        op = c["op"]
        if op == "info":
            return {"pid": os.getpid(), "info": mc.server.getInfo(), "package": str(package), "version": minebridge.__version__}
        if op == "openPlayer":
            reader = mc if "context" not in c else mc.withContext(player=c["context"])
            refs[c["label"]] = reader.inventories.ofPlayer(target(c.get("target", "$self")))
            return metadata(refs[c["label"]])
        if op == "snapshotPlayer":
            player_refs[c["label"]] = mc.players.get(c["target"])
            return player_refs[c["label"]]
        if op == "openChest":
            refs[c["label"]] = mc.inventories.ofBlock(*c["position"], world=c.get("world"), combined=c.get("combined", False))
            return metadata(refs[c["label"]])
        if op == "metadata": return metadata(refs[c["label"]])
        if op == "getItem": return refs[c["label"]].getItem(c["slot"])
        if op == "setItem":
            item = c["item"]
            if "name" in c or "lore" in c: item = ItemStack(item, 1, name=c.get("name"), lore=c.get("lore"))
            return refs[c["label"]].setItem(c["slot"], item, c.get("amount"))
        if op == "copyView":
            value = refs[c["label"]].getItem(c["source"])
            return refs[c["label"]].setItem(c["slot"], value)
        if op == "clear": return refs[c["label"]].clear(c.get("slot"))
        if op == "contents":
            transport = mc._transport
            cls = type(transport); original = cls.exchange
            pages = 0
            def exchange(self, method, *args, **kwargs):
                nonlocal pages
                result = original(self, method, *args, **kwargs)
                if self is transport and method == "inventories.getContents":
                    pages += 1
                    if c.get("hook") and pages == 1:
                        assert result.result["nextOffset"] is not None, "Fixture must force a second real page"
                        emit({"type": "hook", "id": c["id"], "phase": "first-page", "pages": pages})
                        continuation = json.loads(sys.stdin.readline())
                        assert continuation == {"continue": c["id"]}
                return result
            cls.exchange = exchange
            try:
                values = refs[c["label"]].getContents()
                return {"entries": [{"slot": slot, "item": evidence(item)} for slot, item in values.items()], "pages": pages}
            finally: cls.exchange = original
        if op == "bulk":
            selection = c.get("targets", "@a")
            if isinstance(selection, list): selection = [player_refs[label] for label in selection]
            else: selection = target(selection)
            return mc.players.setItem(selection, c["slot"], c["item"], c.get("amount"))
        if op == "setBlock":
            mc.setBlock(*c["position"], c.get("block", "minecraft:chest"))
            if c.get("flush"): mc.flush()
            return {"queued": True}
        if op == "close":
            mc.close()
            return {"remainingThreads": [t.name for t in threading.enumerate() if t.ident not in baseline],
                    "metadataAfterClose": {label: metadata(ref) for label, ref in refs.items()}}
        raise AssertionError("Unknown bounded I04 worker operation")

    emit({"type": "ready", "result": perform({"op": "info"})})
    try:
        for line in sys.stdin:
            assert len(line) < 32768
            command = json.loads(line)
            try: emit({"type": "result", "id": command["id"], "result": perform(command)})
            except Exception as error: emit({"type": "result", "id": command["id"], "error": failure(error)})
            if command["op"] == "close": break
    finally: mc.close()


if __name__ == "__main__": main()
