"""Targeted 0.2.1 acceptance: normal Python exit and opt-in server activity logs."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from smoke_i05 import I05Harness, I03Paper, GameClient, ObserverClient, sha256, save
from conftest import require_port_free


def run():
    harness = I05Harness(ROOT / "dist/v0.2.1/minebridge-paper-0.2.1.jar",
        ROOT / "dist/v0.2.1/minebridge-0.2.1-py3-none-any.whl",
        ROOT / ".venv-v021-314/Scripts/python.exe", number="patch")
    harness.world_name = "v021-exit-and-logging"
    harness.workspace = ROOT / ".work" / ("v021-" + harness.run_id)
    harness.server = harness.workspace / "server"
    harness.artifacts = ROOT / "integration/artifacts" / ("v021-" + harness.run_id)
    harness.prepare()
    harness.manifest["stage"] = "v0.2.1"
    harness.manifest["scope"] = "Targeted local patch acceptance; not LAN or classroom load"
    harness.manifest["scripts"][str(Path(__file__).relative_to(ROOT))] = sha256(Path(__file__))
    summary = {"allPassed": False, "manifest": str(harness.artifacts / "manifest.json")}
    children, clients = [], []

    def check(name, result):
        harness.manifest["checks"].append({"name": name, "passed": True, "result": result})
        harness.save_manifest()
        print("PASS " + name, flush=True)

    try:
        with I03Paper(harness, control=True, mode="exit-and-logging") as paper:
            paper.wait_ready()
            observer = ObserverClient(paper, harness.artifacts / "observer.json")
            case = observer.case_id()
            world = next(row for row in observer.result(case, "worlds")["worlds"] if row["name"] == harness.world_name)
            protocol = observer.result(case, "gameProtocol")
            client = GameClient(harness.game_port, "PatchAlice", protocol)
            clients.append(client)
            client.wait_ready()
            observer.result(case, "playerPlace", client.name, world["uuid"], 128, 210, 128)
            anchors = [(128, 210, 128), (130, 210, 128), (132, 210, 128), (0, 0, 0)]
            fixture = observer.case_id()
            observer.result(fixture, "setup", world["uuid"], *("%d,%d,%d" % at for at in anchors))

            def start(python, at, marker, *, logging=False, extra=""):
                code = ("import json,sys,minebridge\nfrom minebridge import Minecraft,block\n"
                    f"mc=Minecraft.create('127.0.0.1',{harness.port},logging={logging!r})\n"
                    "print(json.dumps({'session':mc._transport.context.session_id,'version':minebridge.__version__,"
                    "'package':minebridge.__file__}),flush=True)\nsys.stdin.readline()\n"
                    f"mc.setBlock({at[0]},{at[1]},{at[2]},block.COBBLESTONE)\n"
                    f"mc.postToChat({marker!r})\n" + extra)
                # 0.2.0 has no logging keyword; this is the original two-argument create.
                if ".venv-v02-314" in python.parts:
                    code = code.replace(f",logging={logging!r}", "")
                environment = os.environ.copy()
                environment.pop("MINEBRIDGE_TOKEN", None)
                process = subprocess.Popen([str(python), "-I", "-c", code], cwd=ROOT, env=environment,
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, encoding="utf-8", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                children.append(process)
                context = json.loads(process.stdout.readline())
                assert "site-packages" in context["package"] and "python/src" not in context["package"]
                return process, context

            # Deterministically keep the first write pending while the old process exits.
            old, context = start(ROOT / ".venv-v02-314/Scripts/python.exe", anchors[0], "v021-old")
            gate = observer.case_id()
            observer.result(gate, "gateArm", context["session"], 2)
            old.stdin.write("\n"); old.stdin.flush()
            out, err = old.communicate(timeout=10)
            assert old.returncode == 0 and not err, (out, err)
            status = observer.result(gate, "gateStatus", context["session"], 2)
            actual = observer.result(case, "read", world["uuid"], *anchors[0])
            assert actual["key"] == "minecraft:air", actual
            check("original-0.2.0-silent-exit-reproduced-with-pending-write", {"context": context, "gate": status, "block": actual})

            for label, at, logging in (("quiet", anchors[1], False), ("logged", anchors[2], True),
                                       ("user-example", anchors[3], True), ("error", (128, 320, 128), True)):
                marker = "v021-" + label
                process, context = start(harness.python, at, marker, logging=logging)
                assert context["version"] == "0.2.1"
                gate = observer.case_id()
                observer.result(gate, "gateArm", context["session"], 2)
                process.stdin.write("\n"); process.stdin.flush()
                observer.await_value(gate, "gateStatus", (context["session"], 2), lambda row: row["state"] == "GATED")
                time.sleep(.1)
                assert process.poll() is None, "New script abandoned its pending writes"
                observer.result(gate, "gateRelease", context["session"], 2)
                out, err = process.communicate(timeout=30)
                assert process.returncode == 0, (out, err)
                chat = client.wait_chat(marker)
                if label == "error":
                    assert "CoordinateOutOfBoundsError" in err and "blocks.set" in err, err
                else:
                    assert not err, err
                    actual = observer.result(case, "read", world["uuid"], *at)
                    assert actual["key"] == "minecraft:cobblestone", actual
                time.sleep(.15)
                lines = [line.strip() for line in paper.lines if "ACTION session=" + context["session"] in line]
                assert bool(lines) == logging, lines
                if logging:
                    phase = "phase=error" if label == "error" else "phase=completed"
                    assert any("method=blocks.set" in line and phase in line for line in lines), lines
                    assert any("method=chat.post" in line and "phase=completed" in line for line in lines), lines
                check(label + "-normal-exit-drains-and-session-logging", {"context": context, "stderr": err, "chat": chat, "serverLines": lines})

            extra = ("from minebridge import items,effects,entity,selector\n"
                "me=mc.withContext(player='PatchAlice')\n"
                "me.players.giveItem(selector.SELF,items.EMERALD,2)\n"
                "me.effects.add(selector.SELF,effects.SPEED,duration=5)\n"
                "me.spawnEntity(134,211,128,entity.COW)\n"
                "me.blocks.getBlock(132,210,128)\n")
            process, context = start(harness.python, anchors[2], "v021-domains", logging=True, extra=extra)
            out, err = process.communicate(input="\n", timeout=40)
            assert process.returncode == 0 and not err, (out, err)
            time.sleep(.15)
            lines = [line.strip() for line in paper.lines if "ACTION session=" + context["session"] in line]
            for method in ("players.get", "players.giveItem", "effects.add", "entities.spawn", "blocks.get"):
                assert any("method=" + method in line and "phase=completed" in line for line in lines), method
            check("logging-covers-player-context-inventory-effects-entities-and-reads", {"context": context, "serverLines": lines})
            observer.result(fixture, "cleanup")
            client.close()
            harness.manifest["modes"].append(paper.finish())
            require_port_free(harness.game_port)
        for artifact in harness.manifest["artifacts"].values():
            assert sha256(Path(artifact["path"])) == artifact["sha256"]
        harness.manifest["allPassed"] = summary["allPassed"] = True
    finally:
        for client in clients:
            client.close()
        for process in children:
            if process.poll() is None:
                process.kill(); process.wait(timeout=10)
        harness.save_manifest()
        save(ROOT / ".work/v021-paper-results.json", summary)
    return summary


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
