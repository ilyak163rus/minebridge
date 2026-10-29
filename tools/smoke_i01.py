"""Compact I01 acceptance on pinned Paper, using prebuilt JAR and installed wheel.

No build, download, EULA acceptance or deletion. Reuses the independent T10
console observer and lifecycle fixture. Fresh worlds are disposable fixtures;
the observer holds four chunks and verifies real block state after public ACKs.
"""

from __future__ import annotations

import argparse
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


def save(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def worker(command: dict) -> dict:
    """Runs only in a fresh installed-wheel interpreter, never imports src/."""
    import minebridge
    from minebridge import Minecraft, block

    package = Path(minebridge.__file__).resolve()
    assert not package.is_relative_to(ROOT / "python/src")
    baseline = {thread.ident for thread in threading.enumerate()}
    options = {}
    if command.get("mode") is not None:
        options["writeMode"] = command["mode"]
    if command.get("token") is not None:
        options["token"] = command["token"]
    result = {"pid": os.getpid(), "package": str(package), "python": sys.version.split()[0],
              "tokenEnvironmentAbsent": "MINEBRIDGE_TOKEN" not in os.environ}
    mc = None

    def error(failure: Exception) -> dict:
        return {"type": type(failure).__name__, "code": getattr(failure, "code", None),
                "outcome": getattr(failure, "outcome", None),
                "requestId": getattr(failure, "request_id", None),
                "method": getattr(failure, "method", None),
                "failures": len(getattr(failure, "failures", ())) }

    try:
        # With no options this is exactly the student's two-argument call.
        mc = Minecraft.create("127.0.0.1", command["port"], **options)
        context = mc._transport.context  # Diagnostic correlation, not an operation API.
        result["world"] = {"name": context.world.name, "uuid": context.world.uuid}
        result["worldKey"] = context.world.key
        result["sessionId"] = context.session_id
        if command.get("ready"):
            Path(command["ready"]).write_text("ready", encoding="utf-8")
            deadline = time.monotonic() + 15
            while not Path(command["gate"]).exists():
                if time.monotonic() >= deadline:
                    raise AssertionError("Concurrent worker start barrier timed out")
                time.sleep(.005)
        operation = command.get("operation", "write")
        if operation == "error":
            mc.setBlock(*command["position"], command.get("block", "minecraft:cobblestone"))
            result["setReturned"] = True
            try:
                if command["barrier"] == "flush":
                    mc.flush()
                else:
                    mc.close()
            except Exception as failure:
                result["deferredError"] = error(failure)
            else:
                raise AssertionError("Invalid server operation did not fail at its barrier")
        elif operation == "write":
            count, repeats = command.get("count", 1), command.get("repeats", 1)
            y, offset = command["y"], command.get("offset", 0)
            timings = []
            for repeat in range(repeats):
                material = block.COBBLESTONE if repeat % 2 == 0 else block.STONE
                started = time.perf_counter()
                for index in range(count):
                    mc.setBlock(128 + index % 32, y, 128 + index // 32 + offset, material)
                sent = time.perf_counter()
                mc.flush()
                finished = time.perf_counter()
                timings.append({"count": count, "enqueueSeconds": sent - started,
                                "completedSeconds": finished - started})
            result.update({"timings": timings, "finalKey": "minecraft:cobblestone"
                           if (repeats - 1) % 2 == 0 else "minecraft:stone"})
        elif operation != "connect":
            raise AssertionError("Unexpected fixture operation")
    except Exception as failure:
        result["error"] = error(failure)
    finally:
        if mc is not None:
            try:
                mc.close()
            except Exception as failure:
                result["closeError"] = error(failure)
            mc.close()  # Idempotence after success and after a deferred failure.
        result["remainingThreads"] = [thread.name for thread in threading.enumerate()
                                      if thread.ident not in baseline]
    return result


def run(wheel: Path, production: Path, python: Path) -> dict:
    sys.path.insert(0, str(ROOT / "integration/tests"))
    import conftest
    from conftest import Harness, PaperRun, free_game_port, sha256
    from observer_client import ObserverClient

    # Existing fixtures read this module constant dynamically; no fixture edits.
    conftest.BRIDGE_PORT = port = free_game_port()

    class I01Harness(Harness):
        def __init__(self, name: str):
            super().__init__(wheel, stage="T10")
            self.stage, self.world_name = "I01", name
            self.workspace = ROOT / ".work" / ("i01-" + self.run_id)
            self.server = self.workspace / "server"
            self.artifacts = ROOT / "integration/artifacts" / ("i01-" + self.run_id)
            self.production, self.python = production.resolve(), python.resolve()

        def prepare(self):
            # The historical stage controls only inherited scope text.
            self.stage = "T10"
            super().prepare()
            self.stage = "I01"
            self.write_config(False)
            self.manifest.update({"stage": "I01", "contract": "v0.2-i01/protocol-2.0",
                                  "scope": "Compact real-Paper I01 acceptance", "checks": []})
            self.save_manifest()

        def write_config(self, authenticated: bool):
            # Legacy fields must neither pin an obsolete world nor enable auth.
            config = ("listenAddress: '127.0.0.1'\n" + f"port: {port}\n"
                      "defaultWorld: 'obsolete-world-not-present'\n"
                      f"token: {json.dumps(self.token)}\n")
            if authenticated:
                config += "authEnabled: true\n"
            (self.server / "plugins/Minebridge/config.yml").write_text(config, encoding="utf-8")
            return config

    class I01Paper(PaperRun):
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
            raise AssertionError("I01 Paper readiness deadline elapsed: " + str(self.log))

    def spawn(harness, command):
        env = os.environ.copy()
        env.pop("MINEBRIDGE_TOKEN", None)
        # Auth test token supplied through this subprocess argument is never logged.
        return subprocess.Popen([str(harness.python), "-I", str(Path(__file__).resolve()),
                                 "--worker", json.dumps({"port": port, **command})],
                                cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8",
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def collect(process, *, timeout=45):
        try:
            output, stderr = process.communicate(timeout=timeout)
        except BaseException:
            process.kill()
            process.communicate(timeout=10)
            raise
        if process.returncode:
            raise AssertionError("Installed-wheel worker failed: " + stderr[-2000:])
        result = json.loads(output)
        assert result["remainingThreads"] == [], result
        assert result["tokenEnvironmentAbsent"], result
        return result

    def client(harness, command):
        return collect(spawn(harness, command))

    def check(harness, name, result, *, error=None):
        assert result.get("error", {}).get("code") == error, result
        assert "closeError" not in result, result
        harness.manifest["checks"].append({"name": name, "passed": True, "result": result})
        harness.save_manifest()
        return result

    summary = {"stage": "I01", "allPassed": False, "runs": [], "worlds": []}
    output = ROOT / ".work/i01-paper-results.json"
    save(output, summary)
    first_config = None
    try:
        for number in (1, 2):
            harness = I01Harness(f"i01-lesson-{number}")
            # Identical bridge configuration, two freshly generated level names.
            if first_config is not None:
                harness.token = first_token
            harness.prepare()
            config = (harness.server / "plugins/Minebridge/config.yml").read_bytes()
            if first_config is None:
                first_config, first_token = config, harness.token
            assert config == first_config
            summary["runs"].append(str(harness.artifacts / "manifest.json"))
            save(output, summary)
            successful = False
            try:
                with I01Paper(harness, control=False, mode="auth-off") as paper:
                    paper.wait_ready()
                    observer = ObserverClient(paper, harness.artifacts / "observer-off.json")
                    worlds = observer.result(observer.case_id(), "worlds")["worlds"]
                    world = next(item for item in worlds if item["name"] == harness.world_name)
                    summary["worlds"].append(world)
                    y = world["maxYExclusive"] - 8
                    case = observer.case_id()
                    anchors = [(x, y, z) for x in (128, 144) for z in (128, 144)]
                    fixture = observer.result(case, "setup", world["uuid"],
                                              *("%d,%d,%d" % at for at in anchors))
                    assert len(fixture["chunks"]) == 4

                    def verify(command, result):
                        assert result["world"] == {"name": world["name"], "uuid": world["uuid"]}
                        assert result["worldKey"] == "minecraft:overworld", result
                        count, offset = command.get("count", 1), command.get("offset", 0)
                        for index in sorted({0, count // 2, count - 1}):
                            at = (128 + index % 32, y, 128 + index // 32 + offset)
                            snapshot = observer.result(case, "read", world["uuid"], *at)
                            assert snapshot["key"] == result["finalKey"], snapshot

                    command = {"y": y}
                    basic = check(harness, "two-argument-default-buffered", client(harness, command))
                    verify(command, basic)
                    if number == 1:
                        # Warm up execution/network before recording the five requested runs.
                        command = {"y": y, "count": 100}
                        check(harness, "warmup", client(harness, command))
                        tick_before = observer.call(case, "read", world["uuid"], *anchors[0])["tick"]
                        clock_before = time.monotonic()
                        command = {"y": y, "count": 100, "repeats": 5}
                        timed = check(harness, "buffered-100-five-runs", client(harness, command))
                        clock_after = time.monotonic()
                        tick_after = observer.call(case, "read", world["uuid"], *anchors[0])["tick"]
                        median = statistics.median(item["completedSeconds"] for item in timed["timings"])
                        harness.manifest["performance"] = {"buffered100MedianSeconds": median,
                            "targetSeconds": .5, "targetPassed": median <= .5,
                            "tickRateApproximation": (tick_after - tick_before) / (clock_after - clock_before),
                            "tickRateNote": "Observer tick-count/wall-clock sample, not Paper TPS telemetry"}
                        harness.save_manifest()
                        assert median <= .5, ("100-block speed criterion", median)
                        verify(command, timed)
                        for name, command in (("buffered-1000-bounded-window", {"y": y, "count": 1000}),
                                              ("sync-100-equivalence", {"y": y, "count": 100, "mode": "sync"})):
                            result = check(harness, name, client(harness, command))
                            verify(command, result)

                        gate = harness.workspace / "concurrent-start"
                        processes = []
                        commands = []
                        try:
                            for index in (0, 1):
                                command = {"y": y, "count": 128, "offset": 8 * index,
                                           "ready": str(harness.workspace / f"ready-{index}"), "gate": str(gate)}
                                commands.append(command)
                                processes.append(spawn(harness, command))
                            deadline = time.monotonic() + 15
                            while not all(Path(command["ready"]).is_file() for command in commands):
                                if any(process.poll() is not None for process in processes) or time.monotonic() >= deadline:
                                    raise AssertionError("Two Python clients did not reach their start barrier")
                                time.sleep(.01)
                            gate.write_text("start", encoding="utf-8")
                            results = [check(harness, f"concurrent-client-{index}", collect(process))
                                       for index, process in enumerate(processes)]
                            assert results[0]["pid"] != results[1]["pid"]
                            assert results[0]["sessionId"] != results[1]["sessionId"]
                            for command, result in zip(commands, results):
                                verify(command, result)
                        finally:
                            for process in processes:
                                if process.poll() is None:
                                    process.kill()
                                    process.communicate(timeout=10)

                        far = [1_000_000, y, 1_000_000]
                        unloaded = observer.result(case, "checkChunk", world["uuid"], far[0] // 16, far[2] // 16)
                        assert not unloaded["loaded"]
                        for barrier in ("flush", "close"):
                            for name, position, material, expected in (
                                ("invalid-block", list(anchors[0]), "minecraft:i01_missing_block", "INVALID_BLOCK"),
                                ("unloaded-chunk", far, "minecraft:cobblestone", "CHUNK_NOT_LOADED")):
                                result = check(harness, f"deferred-{name}-{barrier}", client(harness,
                                    {"operation": "error", "position": position, "block": material, "barrier": barrier}))
                                assert result["setReturned"]
                                failure = result["deferredError"]
                                assert failure["code"] == expected and failure["outcome"] == "not-applied", failure
                                assert failure["method"] == "blocks.set" and type(failure["requestId"]) is int, failure
                    observer.result(case, "cleanup")
                    harness.manifest["modes"].append(paper.finish())

                if number == 2:
                    harness.write_config(True)
                    with I01Paper(harness, control=False, mode="auth-on") as paper:
                        paper.wait_ready()
                        for name, options in (("auth-missing", {}), ("auth-wrong", {"token": "wrong-i01-token"})):
                            check(harness, name, client(harness, {"operation": "connect", **options}), error="AUTH_FAILED")
                        check(harness, "auth-correct", client(harness,
                              {"operation": "connect", "token": harness.token}))
                        harness.manifest["modes"].append(paper.finish())
                for artifact in harness.manifest["artifacts"].values():
                    assert sha256(Path(artifact["path"])) == artifact["sha256"], "An acceptance artifact changed"
                successful = True
            finally:
                harness.manifest["allPassed"] = successful
                harness.save_manifest()
        assert summary["worlds"][0]["name"] != summary["worlds"][1]["name"]
        assert summary["worlds"][0]["uuid"] != summary["worlds"][1]["uuid"]
        summary["identicalBridgeConfigSha256"] = __import__("hashlib").sha256(first_config).hexdigest()
        summary["scriptSha256"] = sha256(Path(__file__))
        summary["allPassed"] = True
    finally:
        save(output, summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, default=ROOT / "dist/v0.2/i01/minebridge-0.2.0.dev1-py3-none-any.whl")
    parser.add_argument("--plugin", type=Path, default=ROOT / "dist/v0.2/i01/minebridge-paper-0.2.0-dev1.jar")
    parser.add_argument("--python", type=Path, default=ROOT / ".venv-i01-314/Scripts/python.exe")
    parser.add_argument("--worker")
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(json.loads(args.worker))), flush=True)
    else:
        print(json.dumps(run(args.wheel, args.plugin, args.python), indent=2))


if __name__ == "__main__":
    main()
