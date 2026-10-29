"""Native 0.3.1 acceptance and true 0.3.0 region-fill comparison.

Requires prebuilt frozen artifacts and installed SDKs. Builds/downloads/publishes
nothing; only its disposable Paper133 fixtures are started and stopped.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import statistics
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from smoke_i05 import I05Harness
from smoke_i03 import I03Paper
sys.path.insert(0, str(ROOT / "integration/tests"))
from conftest import require_port_free, sha256
from game_client import GameClient
from observer_client import ObserverClient


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


class ReleaseHarness(I05Harness):
    def __init__(self, *, old=False):
        version = "0.3.0" if old else "0.3.1"
        release = ROOT / ("dist/v0.3" if old else "dist/v0.3.1")
        python = ROOT / (".venv-v03-314" if old else ".venv-v031-314") / "Scripts/python.exe"
        super().__init__(release / f"minebridge-paper-{version}.jar",
                         release / f"minebridge-{version}-py3-none-any.whl", python, number=version)
        self.version = version
        self.stage, self.world_name = "V031", "v031-" + ("baseline" if old else "release")
        self.workspace = ROOT / ".work" / ("v031-" + self.run_id)
        self.server = self.workspace / "server"
        self.artifacts = ROOT / "integration/artifacts" / ("v031-" + self.run_id)

    def prepare(self):
        super().prepare()
        scripts = [Path(__file__), ROOT / "integration/tests/v031_worker.py",
                   ROOT / "tools/smoke_i05.py", ROOT / "tools/smoke_i03.py",
                   ROOT / "integration/tests/conftest.py", ROOT / "integration/tests/game_client.py",
                   ROOT / "integration/tests/observer_client.py",
                   ROOT / "integration/observer-plugin/src/main/java/dev/minebridge/observer/ReleaseObserver.java",
                   ROOT / "integration/observer-plugin/src/main/java/dev/minebridge/observer/ObserverPlugin.java"]
        self.manifest.update(stage="V031", version=self.version, baseline030=self.version == "0.3.0",
                             contract="v0.3.1/protocol-2.0", scope="Installed artifacts, local two-process/two-game-client fixture",
                             scripts={str(path.relative_to(ROOT)): sha256(path) for path in scripts})
        self.save_manifest()


class Worker:
    def __init__(self, harness, player=None):
        self.events, self.stderr, self.sequence, self.pending = queue.Queue(), [], 0, None
        env = os.environ.copy()
        env.pop("MINEBRIDGE_TOKEN", None)
        env.pop("PYTHONPATH", None)
        command = [str(harness.python), "-I", str(ROOT / "integration/tests/v031_worker.py"),
                   "--port", str(harness.port), "--version", harness.version]
        if player is not None: command += ["--player", player]
        self.process = subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        def output():
            for line in self.process.stdout:
                try: self.events.put(json.loads(line))
                except ValueError: self.events.put({"type":"fatal", "line":line[:200]})
            self.events.put({"type":"eof"})
        def errors():
            for line in self.process.stderr:
                if len(self.stderr) < 40: self.stderr.append(line)
        self.threads = [threading.Thread(target=output, daemon=True), threading.Thread(target=errors, daemon=True)]
        for thread in self.threads: thread.start()
        try:
            ready = self.event()
            assert ready["type"] == "ready", ready
            self.info = ready["info"]
            assert self.info["version"] == harness.version and self.info["isolated"]
            assert self.info["pluginVersion"] == harness.version
            assert "site-packages" in self.info["package"]
        except BaseException:
            self.abort()
            raise

    def event(self):
        try: value = self.events.get(timeout=120)
        except queue.Empty: raise AssertionError("Installed worker timed out: " + "".join(self.stderr)) from None
        assert value["type"] not in ("fatal", "eof"), (value, self.stderr)
        return value

    def start(self, op, **params):
        assert self.pending is None
        self.sequence += 1
        self.pending = self.sequence
        self.process.stdin.write(json.dumps({"id":self.pending, "op":op, **params}) + "\n")
        self.process.stdin.flush()

    def result(self, *, error=None):
        value = self.event()
        assert value["id"] == self.pending, value
        self.pending = None
        if error is not None:
            assert value.get("error", {}).get("type") == error, value
            return value["error"]
        assert "error" not in value, value
        return value["result"]

    def call(self, op, *, error=None, **params):
        self.start(op, **params)
        return self.result(error=error)

    def close(self):
        if self.process.poll() is None:
            result = self.call("close")
            assert not result["remainingThreads"], result
            self.process.stdin.close()
            self.process.wait(timeout=15)
        assert self.process.returncode == 0 and not self.stderr, self.stderr
        self.abort()

    def abort(self):
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=10)
        for thread in self.threads: thread.join(timeout=5)
        for pipe in (self.process.stdin, self.process.stdout, self.process.stderr):
            if pipe is not None and not pipe.closed: pipe.close()


def check_inputs(harness):
    for row in harness.manifest["artifacts"].values(): assert sha256(Path(row["path"])) == row["sha256"], row
    for path, digest in harness.manifest["scripts"].items(): assert sha256(ROOT / path) == digest, path


def run():
    harnesses, games, workers = [], [], []
    summary = {"allPassed":False, "manifests":[]}
    try:
        for old in (False, True):
            h = ReleaseHarness(old=old)
            h.prepare()
            harnesses.append(h)
            summary["manifests"].append(str(h.artifacts / "manifest.json"))
            print(json.dumps({"phase":"server-start", "version":h.version, "runId":h.run_id,
                              "workspace":str(h.workspace)}), flush=True)
            def check(name, result):
                h.manifest["checks"].append({"name":name, "passed":True, "result":result})
                h.save_manifest()
                print(json.dumps({"passed":name, "version":h.version}), flush=True)

            local_games, local_workers = [], []
            with I03Paper(h, control=True, mode="v031-baseline" if old else "v031-release") as paper:
                paper.wait_ready()
                observer = ObserverClient(paper, h.artifacts / "observer.json")
                root_case = observer.case_id()
                world = next(w for w in observer.result(root_case, "worlds")["worlds"] if w["name"] == h.world_name)
                protocol = observer.result(root_case, "gameProtocol")
                for index, name in enumerate(("V031Alice", "V031Bob")):
                    game = GameClient(h.game_port, name, protocol)
                    games.append(game); local_games.append(game)
                    game.wait_ready(); paper.command("op " + name)
                    observer.result(root_case, "playerPlace", name, world["uuid"], 128.5+index*32, 210, 128.5)
                    observer.result(root_case, "i04EmptyPlayer", name)
                    observer.result(root_case, "i03Block", world["uuid"], 128+index*32, 209, 128, "COBBLESTONE")
                alice, bob = Worker(h, "V031Alice"), Worker(h, "V031Bob")
                workers.extend((alice,bob)); local_workers.extend((alice,bob))
                assert alice.info["pid"] != bob.info["pid"] and alice.info["sessionId"] != bob.info["sessionId"]
                check("two-installed-sdk-processes-and-real-game-connections", {"workers":[alice.info,bob.info]})

                held_cases = []
                def hold_region(start, end):
                    case = observer.case_id(); held_cases.append(case)
                    positions = [f"{x*16},209,{z*16}" for x in range(start[0]//16,end[0]//16+1)
                                 for z in range(start[2]//16,end[2]//16+1)]
                    assert len(positions) <= 16
                    return observer.result(case, "setup", world["uuid"], *positions)
                def verify(start, end, specification):
                    result = observer.result(root_case, "releaseRegion", world["uuid"], *start, *end, specification)
                    assert result["volume"] == result["matched"] and result["firstMismatch"] is None, result
                    return result
                def fill(start, end, material="minecraft:stone", **kwargs):
                    return alice.call("region", **{"from":start,"to":end,"key":material,**kwargs})

                start, end = [256,210,128], [285,239,157]
                held = hold_region(start, [286,240,158])
                fill(start, end)  # Untimed identical area/chunk/Paper-setter warmup.
                measured = []
                for material in ("minecraft:cobblestone", "minecraft:stone", "minecraft:cobblestone"):
                    measured.append(fill(start,end,material))
                    verify(start,end,material)
                check("acknowledged-loaded-30-cube-27000-exact-native-cells", {"measurements":measured,"held":held})

                if old:
                    summary["old030"] = measured
                else:
                    native = []
                    for material in ("minecraft:stone", "minecraft:cobblestone", "minecraft:stone"):
                        began = time.perf_counter()
                        dispatched = observer.result(root_case,"releaseFill",world["uuid"],*start,*end,material)
                        assert dispatched["nativeCommandDispatched"], dispatched
                        # A nested native command can be queued until the plugin's
                        # onCommand returns. Its dispatch return is not completion.
                        # A separate console command observes every final cell.
                        observed = observer.await_value(root_case,"releaseRegion",(world["uuid"],*start,*end,material),
                            lambda row: row["matched"] == 27000 and row["firstMismatch"] is None,timeout=15)
                        result = {**observed,"seconds":time.perf_counter()-began,
                                  "nativeCommandDispatched":True,"dispatchOnlySeconds":dispatched["seconds"],
                                  "includesCompletionReadback":True,"nativeCompletionUpperBound":True}
                        native.append(result)
                    summary.update(new031=measured, vanillaFill=native)
                    check("timed-native-vanilla-fill-on-same-held-27000-cell-area", native)
                    cube31 = fill(start,[286,240,158],"minecraft:cobblestone")
                    native31 = verify(start,[286,240,158],"minecraft:cobblestone")
                    assert cube31["volume"] == native31["matched"] == 29791
                    check("inclusive-31-cube-within-fast-budget", {"api":cube31,"native":native31})

                    named_position = [176.5,212,136.5]
                    named = alice.call("named",name="V031Bob",position=named_position)
                    assert named["give"]["matched"] == named["give"]["applied"] == 1
                    assert named["give"]["targets"][0]["given"] == 3
                    assert named["effect"]["matched"] == named["teleport"]["applied"] == 1
                    assert named["slot"]["amount"] == 4 and named["slot"]["key"]["key"] == "minecraft:diamond"
                    native_player = observer.result(root_case,"i04Player","V031Bob")
                    native_other = observer.result(root_case,"i04Player","V031Alice")
                    locations = observer.result(root_case,"players")["players"]
                    bob_location = next(row for row in locations if row["name"]=="V031Bob")
                    alice_location = next(row for row in locations if row["name"]=="V031Alice")
                    assert [bob_location[key] for key in ("x","y","z")] == named_position, bob_location
                    assert [alice_location[key] for key in ("x","y","z")] == [128.5,210,128.5], alice_location
                    assert next(row["item"] for row in native_player["slots"] if row["slot"]==2)["amount"]==4
                    assert next(row["item"] for row in native_other["slots"] if row["slot"]==2) is None
                    control = observer.result(root_case,"controlPlayer","V031Bob")
                    assert any(row["key"]=="minecraft:speed" and row["amplifier"]==1 for row in control["effects"])
                    for missing in ("Absent031", "v031bob"):
                        result = alice.call("namedMissing",name=missing)
                        assert all(result[key]["matched"]==result[key]["applied"]==0 for key in ("give","effect","teleport")), result
                        assert result["positionError"]["code"] == result["inventoryError"]["code"] == "INVALID_TARGET", result
                    check("named-player-give-effects-teleport-slots-and-exact-case-missing-selection",
                          {"api":named,"native":native_player,"otherPlayer":native_other,"settings":control,"locations":locations})

                    fill([192,209,120],[207,209,135])
                    difficulty = observer.result(root_case,"releaseDifficulty",world["uuid"],"PEACEFUL")
                    assert difficulty["difficulty"] == "PEACEFUL", difficulty
                    blocked = []
                    for kind in ("GIANT","ZOMBIE"):
                        result=alice.call("spawn",entity=kind,position=[200,210,128],error="PeacefulSpawnError")
                        assert result["code"] == "PEACEFUL_SPAWN_BLOCKED" and result["outcome"] == "not-applied", result
                        blocked.append(result)
                    before = observer.result(root_case,"releaseEntities",world["uuid"])
                    assert not [row for row in before["entities"] if row["type"] in ("GIANT","ZOMBIE")], before
                    created = [alice.call("spawn",entity=kind,position=[200+index*2,210,128])
                               for index,kind in enumerate(("COW","SHULKER"))]
                    peaceful = observer.result(root_case,"releaseEntities",world["uuid"])
                    assert all(any(row["uuid"]==entity["uuid"] and row["valid"] for row in peaceful["entities"])
                               for entity in created), peaceful
                    difficulty = observer.result(root_case,"releaseDifficulty",world["uuid"],"NORMAL")
                    assert difficulty["difficulty"] == "NORMAL", difficulty
                    giant=alice.call("spawn",entity="GIANT",position=[200,210,128]); created.append(giant)
                    normal=observer.result(root_case,"releaseEntities",world["uuid"])
                    assert any(row["uuid"]==giant["uuid"] and row["type"]=="GIANT" and row["valid"] for row in normal["entities"]), normal
                    for entity in created: observer.result(root_case,"i03Remove",entity["uuid"])
                    assert bob.call("getBlock")==4
                    check("peaceful-specific-not-applied-error-allowed-shulker-cow-and-normal-giant",
                          {"blocked":blocked,"peaceful":peaceful,"normal":normal})

                    # Native support physics, independently of the inert fill benchmark.
                    # Removing a torch's support through setBlocks must notify neighbours.
                    hold_region([224,210,128],[224,210,128])
                    observer.result(root_case,"i03Block",world["uuid"],224,209,128,"STONE")
                    observer.result(root_case,"i03Block",world["uuid"],224,210,128,"TORCH")
                    removed_support = fill([224,209,128],[224,209,128],"minecraft:air")
                    torch = verify([224,210,128],[224,210,128],"minecraft:air")
                    check("setBlocks-preserves-native-neighbour-physics", {"api":removed_support,"native":torch})

                    cold_start, cold_end = [-20017,80,-20017], [-19987,82,-19987]
                    cold_before = observer.result(root_case,"checkChunk",world["uuid"],cold_start[0]//16,cold_start[2]//16)
                    assert not cold_before["loaded"],cold_before
                    cold=fill(cold_start,cold_end,"minecraft:oak_log",states={"axis":"x"})
                    hold_region(cold_start,cold_end)
                    cold_native=verify(cold_start,cold_end,"minecraft:oak_log[axis=x]")
                    check("unloaded-negative-chunks-load-and-preserve-every-oriented-block",
                          {"before":cold_before,"api":cold,"native":cold_native})

                    large_start, large_end = [384,210,128], [447,225,191]
                    hold_region(large_start,large_end)
                    alice.start("region",**{"from":large_start,"to":large_end,"key":"minecraft:stone"})
                    peer_started=time.perf_counter(); assert bob.call("getBlock")==4
                    peer_completed=time.perf_counter()
                    large=alice.result()
                    assert large["finishedAt"] > peer_completed, {"large":large,"peerCompleted":peer_completed}
                    large_native=verify(large_start,large_end,"minecraft:stone")
                    assert large_native["matched"]==65536
                    check("larger-region-yields-peer-rpc-before-final-ack-with-complete-native-readback",
                          {"api":large,"peerSeconds":peer_completed-peer_started,"native":large_native})

                for case in held_cases: observer.result(case,"cleanup")
                for worker in local_workers: worker.close()
                for game in local_games:
                    assert not game.errors,game.evidence()
                    game.close()
                check("clean-installed-worker-threads-and-game-connections", {"games":[game.evidence() for game in local_games]})
                h.manifest["modes"].append(paper.finish())
                require_port_free(h.game_port)
            check_inputs(h)
            h.manifest["allPassed"] = True
            h.save_manifest()
        summary["performance"] = {"mediansSeconds":{key:statistics.median(row["seconds"] for row in summary[key])
                                                    for key in ("new031","old030","vanillaFill")},
                                  "volume":27000,"includesFlush":True,"repeats":3,"chunksHeld":True,
                                  "logging":False,"eventFlood":False,"testControl":True,
                                  "nativeFillTiming":"Parent elapsed dispatch through separate full readback; includes IPC and verification, upper bound only",
                                  "seed":20261021,"scope":"Local inert loaded blocks; chunk generation measured separately"}
        for h in harnesses: check_inputs(h)
        summary["allPassed"] = True
    finally:
        for worker in workers: worker.abort()
        for game in games: game.close()
        for h in harnesses: h.save_manifest()
        save(ROOT / ".work/v031-paper-results.json",summary)
    return summary


if __name__ == "__main__": print(json.dumps(run(),indent=2))
