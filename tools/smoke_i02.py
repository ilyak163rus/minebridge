"""Compact I02 acceptance against real pinned Paper and current Python sources.

No release build, wheel installation, download, EULA acceptance or deletion.
The supplied plugin JAR is a temporary development build needed by Paper;
release packaging remains the final v0.2 iteration. Existing local console
observer independently verifies block data, never the production ACK payload.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import queue
import shutil
import statistics
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "python/src"


def save(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def failure_info(failure: Exception) -> dict:
    return {"type": type(failure).__name__, "message": str(failure),
            "code": getattr(failure, "code", None),
            "outcome": getattr(failure, "outcome", None)}


def wait_file(path: Path, *, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while not path.is_file():
        if time.monotonic() >= deadline:
            raise AssertionError("Worker barrier deadline elapsed: " + str(path))
        time.sleep(.005)


def worker(command: dict) -> dict:
    # Explicit source import, including in isolated (-I) subprocesses.
    sys.path.insert(0, str(SOURCE))
    import minebridge
    from minebridge import Minecraft, block
    from minebridge.models import BlockSpec
    from minebridge.errors import InvalidBlockError, RegionBusyError, UnsupportedLegacyBlockError

    package = Path(minebridge.__file__).resolve()
    assert package.is_relative_to(SOURCE), package
    baseline = {thread.ident for thread in threading.enumerate()}
    result = {"pid": os.getpid(), "package": str(package), "python": sys.version.split()[0]}
    mc = None
    try:
        options = {"writeMode": command["mode"]} if command.get("mode") else {}
        mc = Minecraft.create("127.0.0.1", command["port"], **options)
        context = mc._transport.context  # Correlation only, not a diagnostic RPC.
        result.update({"sessionId": context.session_id, "world": context.world.name,
                       "worldUuid": context.world.uuid})
        if command.get("ready"):
            save(Path(command["ready"]), {**result, "nextRequestId": mc._transport._next_id})
            wait_file(Path(command["gate"]))
        operation, y = command.get("operation", "basics"), command["y"]
        if operation == "basics":
            mc.setBlock(128, y, 128, 4)
            assert mc.getBlock(128, y, 128) == 4
            mc.setBlock(129, y, 128, block.STONE)
            assert mc.blocks.getBlock(129, y, 128).key == "minecraft:stone"
            # Read is an implicit barrier for an earlier buffered region write.
            mc.setBlocks(159, y, 143, 128, y, 128, block.COBBLESTONE)
            before = mc._transport._next_id
            rows = mc.getBlocks(159, y, 143, 128, y, 128)
            pages = mc._transport._next_id - before
            expected = {(x, y, z): 4 for x in range(128, 160) for z in range(128, 144)}
            assert rows == expected, (len(rows), len(expected))
            assert pages == 8, pages
            result.update({"rootRegionCount": len(rows), "readPages": pages})
            modern_rows = mc.blocks.getBlocks(128, y, 128, 159, y, 143)
            assert set(modern_rows) == set(expected)
            assert all(value.key == "minecraft:cobblestone" for value in modern_rows.values())
            # A fractional negative coordinate must floor, including both corners.
            mc.setBlocks(-15.2, y, -15.2, -16.2, y, -16.2, 1)
            negative = mc.getBlocks(-16, y, -16, -17, y, -17)
            assert negative == {(x, y, z): 1 for x in (-17, -16) for z in (-17, -16)}
            result["negativeRegionCount"] = len(negative)
            stairs = BlockSpec("minecraft:oak_stairs", {"facing": "east", "half": "top"})
            mc.setBlock(128, y + 2, 128, stairs)
            actual = mc.blocks.getBlock(128, y + 2, 128)
            assert actual.key == stairs.key and all(actual.states[k] == v for k, v in stairs.states.items())
            mc.setBlock(130, y + 2, 128, "minecraft:oak_log[axis=x]")
            log = mc.blocks.getBlock(130, y + 2, 128)
            assert log.key == "minecraft:oak_log" and log.states["axis"] == "x"
            result["states"] = {"stairs": dict(actual.states), "log": dict(log.states)}
            mc.setBlock(132, y + 2, 128, BlockSpec("minecraft:stone", {"facing": "east"}))
            try:
                mc.flush()
            except InvalidBlockError as failure:
                result["invalidStates"] = failure_info(failure)
            else:
                raise AssertionError("Stone with facing did not fail")
            mc.setBlock(134, y + 2, 128, "minecraft:amethyst_block")
            modern = mc.blocks.getBlock(134, y + 2, 128)
            assert modern.key == "minecraft:amethyst_block"
            try:
                mc.getBlock(134, y + 2, 128)
            except UnsupportedLegacyBlockError as failure:
                result["unsupportedLegacy"] = failure_info(failure)
            else:
                raise AssertionError("Modern block received an invented historical numeric ID")
            result["modernKey"] = modern.key
        elif operation == "far":
            at = command["position"]
            started = time.perf_counter()
            original = mc.blocks.getBlock(*at)
            mc.setBlock(*at, block.COBBLESTONE)
            assert mc.getBlock(*at) == 4
            result.update({"originalKey": original.key, "completedSeconds": time.perf_counter() - started})
        elif operation == "fill":
            started = time.perf_counter()
            mc.setBlocks(*command["from"], *command["to"], command.get("block", 4))
            mc.flush()
            result["completedSeconds"] = time.perf_counter() - started
            assert mc.getBlock(*command["from"]) == command.get("block", 4)
            assert mc.getBlock(*command["to"]) == command.get("block", 4)
        elif operation == "conflict":
            mc.setBlock(*command["position"], block.STONE)
            try:
                mc.flush()
            except RegionBusyError as failure:
                result["expectedConflict"] = failure_info(failure)
            else:
                raise AssertionError("Conflicting mutation did not report RegionBusyError")
            mc.setBlock(240, y, 240, block.STONE)
            assert mc.getBlock(240, y, 240) == 1
            result["unrelatedWriteCompleted"] = True
        elif operation == "benchmark":
            timings = []
            for repeat in range(6):
                material = block.COBBLESTONE if repeat % 2 == 0 else block.STONE
                started = time.perf_counter()
                for index in range(100):
                    mc.setBlock(128 + index % 32, y, 128 + index // 32, material)
                enqueued = time.perf_counter()
                mc.flush()
                if repeat:
                    timings.append({"enqueueSeconds": enqueued - started,
                                    "completedSeconds": time.perf_counter() - started})
            result["timings"] = timings
            result["medianSeconds"] = statistics.median(row["completedSeconds"] for row in timings)
        elif operation == "shutdown":
            mc.setBlock(128, y, 128, 1)
            try:
                mc.flush()
            except Exception as failure:
                result["shutdownError"] = failure_info(failure)
            else:
                raise AssertionError("Held write unexpectedly completed during shutdown")
        else:
            raise AssertionError("Unexpected worker operation")
    except Exception as failure:
        result["error"] = failure_info(failure)
    finally:
        if mc is not None:
            try:
                mc.close()
            except Exception as failure:
                result["closeError"] = failure_info(failure)
            mc.close()
        result["remainingThreads"] = [thread.name for thread in threading.enumerate()
                                      if thread.ident not in baseline]
    return result


def run(production: Path, python: Path) -> dict:
    sys.path.insert(0, str(ROOT / "integration/tests"))
    import conftest
    from conftest import Harness, PaperRun, free_game_port, require_port_free, sha256
    from observer_client import ObserverClient

    conftest.BRIDGE_PORT = port = free_game_port()

    class I02Harness(Harness):
        def __init__(self):
            # Harness owns toolchain, fresh run ID, process paths and manifest IO.
            super().__init__(ROOT / "python/src/minebridge/__init__.py", stage="T10")
            self.stage, self.world_name = "I02", "i02-lesson"
            self.workspace = ROOT / ".work" / ("i02-" + self.run_id)
            self.server = self.workspace / "server"
            self.artifacts = ROOT / "integration/artifacts" / ("i02-" + self.run_id)
            self.production, self.python = production.resolve(), python.resolve()

        def prepare(self):
            require_port_free(port)
            assert not self.workspace.exists() and not self.artifacts.exists()
            paper = Path(self.toolchain["paperJar"])
            for artifact in (self.java, self.python, self.production, self.observer, paper):
                assert artifact.is_file(), artifact
            assert sha256(paper) == self.toolchain["artifacts"]["paper"]["sha256"]
            consent = ROOT / ".work/t02-server/eula.txt"
            assert "eula=true" in consent.read_text(encoding="utf-8").splitlines()
            self.server.mkdir(parents=True)
            self.artifacts.mkdir(parents=True)
            caches = []
            for name in ("libraries", "cache", "versions"):
                source = ROOT / ".work/t02-server" / name
                if source.is_dir():
                    shutil.copytree(source, self.server / name)
                    caches.append(name)
            shutil.copy2(consent, self.server / "eula.txt")
            plugin_dir = self.server / "plugins"
            (plugin_dir / "Minebridge").mkdir(parents=True)
            shutil.copy2(self.production, plugin_dir / "Minebridge.jar")
            shutil.copy2(self.observer, plugin_dir / "MinebridgeObserver.jar")
            (plugin_dir / "Minebridge/config.yml").write_text(
                "listenAddress: '127.0.0.1'\n" + f"port: {port}\n", encoding="utf-8")
            template = (ROOT / "integration/configs/server.properties").read_text(encoding="utf-8")
            (self.server / "server.properties").write_text(
                template.format(game_port=self.game_port, world_name=self.world_name), encoding="utf-8")
            self.manifest = {"schemaVersion": 1, "stage": "I02", "runId": self.run_id,
                "contract": "v0.2-i02/protocol-2.0", "server": str(self.server),
                "world": {"name": self.world_name, "fresh": True, "seed": "20261021"},
                "network": {"address": "127.0.0.1", "bridgePort": port, "gamePort": self.game_port},
                "artifacts": {"paper": self.describe(paper), "production": self.describe(self.production),
                              "observer": self.describe(self.observer)},
                "pythonSources": str(SOURCE), "wheelBuilt": False, "releasePackaged": False,
                "pythonSourceSha256": {str(path.relative_to(SOURCE)): sha256(path)
                    for path in sorted((SOURCE / "minebridge").rglob("*"))
                    if path.is_file() and "__pycache__" not in path.parts},
                "eula": {"copiedExistingConsent": True, "acceptedAutomatically": False,
                         "source": str(consent), "sha256": sha256(consent)},
                "bootstrapCachesCopied": caches, "checks": [], "modes": [], "allPassed": False}
            self.save_manifest()

    class I02Paper(PaperRun):
        def wait_ready(self):
            deadline, done, listener, observer = time.monotonic() + 300, False, False, False
            while time.monotonic() < deadline:
                try:
                    line = self.events.get(timeout=.2)
                except queue.Empty:
                    if self.process.poll() is not None:
                        break
                    continue
                done |= "Done (" in line
                listener |= f"TCP listener ready on port {port}." in line
                observer |= "[MinebridgeObserver]" in line and "Enabling" in line
                if done and listener and observer:
                    return
            raise AssertionError("I02 Paper readiness deadline elapsed: " + str(self.log))

    processes = []

    def spawn(command):
        env = os.environ.copy()
        env.pop("MINEBRIDGE_TOKEN", None)
        process = subprocess.Popen([str(python), "-I", str(Path(__file__).resolve()),
                                    "--worker", json.dumps({"port": port, **command})],
                                   cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8",
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        processes.append(process)
        return process

    def collect(process, *, timeout=90):
        try:
            output, stderr = process.communicate(timeout=timeout)
        except BaseException:
            process.kill()
            process.communicate(timeout=10)
            raise
        assert process.returncode == 0, stderr[-3000:]
        result = json.loads(output)
        assert result["remainingThreads"] == [], result
        assert "error" not in result and "closeError" not in result, result
        return result

    harness = I02Harness()
    harness.prepare()

    def check(name, result):
        harness.manifest["checks"].append({"name": name, "passed": True, "result": result})
        harness.save_manifest()
        return result

    summary = {"stage": "I02", "allPassed": False,
               "manifest": str(harness.artifacts / "manifest.json")}
    target = ROOT / ".work/i02-paper-results.json"
    save(target, summary)
    try:
        with I02Paper(harness, control=True, mode="i02-blocks") as paper:
            paper.wait_ready()
            observer = ObserverClient(paper, harness.artifacts / "observer.json")
            case = observer.case_id()
            world = next(row for row in observer.result(case, "worlds")["worlds"]
                         if row["name"] == harness.world_name)
            y = world["maxYExclusive"] - 40
            anchors = [(128, y, 128), (144, y, 128), (128, y + 2, 128),
                       (130, y + 2, 128), (134, y + 2, 128)]
            observer.result(case, "setup", world["uuid"], *("%d,%d,%d" % at for at in anchors))
            check("root-modern-states-pages-negative-barrier", collect(spawn({"y": y})))
            for at, key, properties in ((anchors[2], "minecraft:oak_stairs", {"facing": "east", "half": "top"}),
                                        (anchors[3], "minecraft:oak_log", {"axis": "x"}),
                                        (anchors[4], "minecraft:amethyst_block", {})):
                snapshot = observer.result(case, "read", world["uuid"], *at)
                assert snapshot["key"] == key and all(snapshot["properties"][k] == v for k, v in properties.items())
            far = [20_000, y, 20_000]
            before = observer.result(case, "checkChunk", world["uuid"], far[0] // 16, far[2] // 16)
            assert not before["loaded"]
            far_result = collect(spawn({"operation": "far", "position": far, "y": y}))
            # Production releases its lease on completion, so the chunk may
            # already have unloaded. Observer setup is explicit fixture loading
            # and captures the real original before clearing its test position.
            far_case = observer.case_id()
            oracle = observer.result(far_case, "setup", world["uuid"], "%d,%d,%d" % tuple(far))
            assert oracle["originals"][0]["key"] == "minecraft:cobblestone"
            check("far-read-generates-then-write-without-player",
                  {"before": before, "oracleOriginal": oracle["originals"][0], **far_result})
            observer.result(far_case, "cleanup")

            # Separate processes operate simultaneously in disjoint layers of one chunk.
            gate = harness.workspace / "shared-go"
            commands, peers = [], []
            for index in (0, 1):
                bottom = y + 4 + index * 10
                command = {"operation": "fill", "y": y, "from": [256, bottom, 256],
                           "to": [271, bottom + 7, 271], "block": 1 + 3 * index,
                           "ready": str(harness.workspace / f"shared-ready-{index}"), "gate": str(gate)}
                commands.append(command)
                peers.append(spawn(command))
            for command in commands:
                wait_file(Path(command["ready"]))
            gate.write_text("go", encoding="utf-8")
            results = [collect(peer) for peer in peers]
            assert results[0]["pid"] != results[1]["pid"]
            assert results[0]["sessionId"] != results[1]["sessionId"]
            shared_case = observer.case_id()
            oracle = observer.result(shared_case, "setup", world["uuid"],
                                     *("%d,%d,%d" % tuple(command["to"]) for command in commands))
            for command, snapshot in zip(commands, oracle["originals"]):
                assert snapshot["key"] == ("minecraft:stone" if command["block"] == 1 else "minecraft:cobblestone")
            check("two-processes-shared-chunk-disjoint-regions", {"clients": results,
                                                                   "oracleOriginals": oracle["originals"]})
            observer.result(shared_case, "cleanup")

            # Keep a region job active long enough to observe its first setter,
            # then conflict from a second already-connected Python process.
            region_case = observer.case_id()
            first = [512, y, 512]
            last = [575, y + 15, 575]
            observer.result(region_case, "setup", world["uuid"], "%d,%d,%d" % tuple(first))
            commands, peers = [], []
            for index, operation in enumerate(("fill", "conflict")):
                command = {"operation": operation, "y": y, "from": first, "to": last,
                           "position": first, "ready": str(harness.workspace / f"overlap-ready-{index}"),
                           "gate": str(harness.workspace / f"overlap-go-{index}")}
                commands.append(command)
                peers.append(spawn(command))
            for command in commands:
                wait_file(Path(command["ready"]))
            Path(commands[0]["gate"]).write_text("go", encoding="utf-8")
            observer.await_value(region_case, "read", (world["uuid"], *first),
                                 lambda row: row["key"] == "minecraft:cobblestone", timeout=30)
            assert peers[0].poll() is None, "Region finished before the overlap observation"
            Path(commands[1]["gate"]).write_text("go", encoding="utf-8")
            conflict = collect(peers[1])
            assert peers[0].poll() is None, "Unrelated write did not progress before region completion"
            fill = collect(peers[0])
            check("region-reservation-conflict-and-other-session-progress", {"fill": fill, "other": conflict})
            observer.result(region_case, "cleanup")

            benchmark = collect(spawn({"operation": "benchmark", "y": y}))
            assert benchmark["medianSeconds"] <= .5, benchmark
            check("buffered100-regression-five-runs", benchmark)

            # Known pre-dequeue local gate: prove shutdown bounds a waiting writer.
            ready, gate = harness.workspace / "shutdown-ready", harness.workspace / "shutdown-go"
            process = spawn({"operation": "shutdown", "y": y, "ready": str(ready), "gate": str(gate)})
            wait_file(ready)
            context = json.loads(ready.read_text(encoding="utf-8"))
            session, request = context["sessionId"], context["nextRequestId"]
            observer.result(case, "gateArm", session, request)
            gate.write_text("go", encoding="utf-8")
            observer.await_value(case, "gateStatus", (session, request), lambda row: row["state"] == "GATED")
            started = time.perf_counter()
            mode = paper.finish()
            result = collect(process, timeout=15)
            assert result["shutdownError"]["type"] in ("ConnectionError", "OperationTimeoutError", "ServerOperationError"), result
            check("shutdown-waiting-write-no-worker-leak", {"client": result, "seconds": time.perf_counter() - started})
            harness.manifest["modes"].append(mode)
        for artifact in harness.manifest["artifacts"].values():
            assert sha256(Path(artifact["path"])) == artifact["sha256"], "An acceptance input changed"
        for relative, digest in harness.manifest["pythonSourceSha256"].items():
            assert sha256(SOURCE / relative) == digest, "A Python acceptance source changed: " + relative
        summary.update({"allPassed": True, "buffered100MedianSeconds": benchmark["medianSeconds"],
                        "scriptSha256": sha256(Path(__file__))})
        harness.manifest["allPassed"] = True
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=10)
        harness.save_manifest()
        save(target, summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin", type=Path, default=ROOT / "plugin/build/libs/minebridge-paper-0.2.0-dev1.jar")
    parser.add_argument("--python", type=Path, default=ROOT / ".venv-i01-314/Scripts/python.exe")
    parser.add_argument("--worker")
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(json.loads(args.worker))), flush=True)
    else:
        print(json.dumps(run(args.plugin, args.python), indent=2))


if __name__ == "__main__":
    main()
