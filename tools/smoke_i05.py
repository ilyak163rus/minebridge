"""Combined v0.2 acceptance: final installed wheel, final JAR, real pinned Paper.

Two independent Python processes and two real Minecraft network clients share
one disposable server. A second fresh world uses identical plugin config with
test control disabled. This runner builds, installs, downloads and deletes nothing.
"""

from __future__ import annotations

import argparse
import hashlib
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
from smoke_i03 import I03Harness, I03Paper
sys.path.insert(0, str(ROOT / "integration/tests"))
import conftest
from conftest import require_port_free, sha256
from fault_proxy import FaultProxy
from game_client import GameClient
from observer_client import ObserverClient


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


class I05Harness(I03Harness):
    def __init__(self, production, wheel, python, *, number, port=None):
        super().__init__(production)
        self.stage, self.world_name = "I05", "v02-lesson-" + str(number)
        self.workspace = ROOT / ".work" / ("i05-" + self.run_id)
        self.server = self.workspace / "server"
        self.artifacts = ROOT / "integration/artifacts" / ("i05-" + self.run_id)
        self.wheel, self.python = wheel.resolve(), python.resolve()
        if port is not None:
            self.port = port
        conftest.BRIDGE_PORT = self.port

    def prepare(self):
        self.verify_installed_wheel()
        super().prepare()
        self.manifest.update({"stage": "I05", "contract": "v0.2/protocol-2.0",
            "releasePackaged": True, "wheelBuilt": True, "installed": self.installed,
            "scope": "Local two-process/two-game-client release acceptance; not classroom load or LAN acceptance"})
        self.manifest.pop("pythonSources", None)
        self.manifest.pop("pythonSourceSha256", None)
        self.manifest["artifacts"]["wheel"] = self.describe(self.wheel)
        self.manifest["scripts"] = {str(path.relative_to(ROOT)): sha256(path) for path in
            (Path(__file__), ROOT / "integration/tests/i05_worker.py", ROOT / "integration/tests/game_client.py")}
        self.save_manifest()


class Worker:
    """A persistent separate installed-wheel process, one public call at a time."""
    def __init__(self, harness, player=None, *, mode="buffered", port=None):
        self.events, self.stderr, self.sequence, self.pending = queue.Queue(), [], 0, None
        self.history = []
        environment = os.environ.copy()
        environment.pop("MINEBRIDGE_TOKEN", None)
        command = [str(harness.python), "-I", str(ROOT / "integration/tests/i05_worker.py"),
                   "--port", str(port or harness.port), "--mode", mode]
        if player:
            command.extend(["--player", player])
        self.process = subprocess.Popen(command, cwd=ROOT, env=environment,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        def output():
            for line in self.process.stdout:
                try:
                    self.events.put(json.loads(line))
                except ValueError:
                    self.events.put({"type": "fatal", "line": line[:200]})
            self.events.put({"type": "eof"})
        def errors():
            for line in self.process.stderr:
                if len(self.stderr) < 80:
                    self.stderr.append(line)
        self.threads = [threading.Thread(target=output, daemon=True), threading.Thread(target=errors, daemon=True)]
        for thread in self.threads:
            thread.start()
        row = self.event(timeout=30)
        assert row["type"] == "ready", (row, self.stderr)
        self.context = row["result"]
        assert self.context["tokenEnvironmentAbsent"]

    def event(self, timeout=30):
        try:
            result = self.events.get(timeout=timeout)
        except queue.Empty:
            raise AssertionError("Installed worker deadline elapsed: " + "".join(self.stderr)[-2000:]) from None
        assert result["type"] not in ("fatal", "eof"), (result, self.stderr)
        return result

    def start(self, op, **params):
        assert self.pending is None, "Overlapping public calls in one worker"
        self.sequence += 1
        self.pending = self.sequence
        self.process.stdin.write(json.dumps({"id": self.sequence, "op": op, **params}) + "\n")
        self.process.stdin.flush()
        return self.sequence

    def result(self, *, error=None, timeout=90):
        row = self.event(timeout)
        assert row["type"] == "result" and row["id"] == self.pending, row
        self.pending = None
        self.history.append(row)
        if error is None:
            assert "error" not in row, row
            return row["result"]
        assert row.get("error", {}).get("type") == error, row
        return row

    def call(self, op, *, error=None, timeout=90, **params):
        self.start(op, **params)
        return self.result(error=error, timeout=timeout)

    def close(self):
        if self.process.poll() is None:
            if self.pending is None:
                result = self.call("close", timeout=15)
                assert result["remainingThreads"] == [], result
            self.process.stdin.close()
            self.process.wait(timeout=15)
        assert self.process.returncode == 0, self.stderr
        for thread in self.threads:
            thread.join(timeout=5)
        for pipe in (self.process.stdout, self.process.stderr):
            pipe.close()

    def abort(self):
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=10)


def names(rows):
    return {row["name"] for row in rows}


def amount(snapshot, key):
    return sum(slot["item"]["amount"] for slot in snapshot["slots"]
               if slot["item"] is not None and slot["item"]["key"] == key)


def full_acceptance(harness, paper, observer, case, world, game, check, workers):
    alice, bob = [Worker(harness, player=client.name) for client in game]
    workers.extend([alice, bob])
    assert alice.context["pid"] != bob.context["pid"]
    assert alice.context["sessionId"] != bob.context["sessionId"]
    for peer in (alice, bob):
        assert peer.context["world"] == {"name": world["name"], "uuid": world["uuid"], "key": "minecraft:overworld"}
    check("final-installed-wheel-two-independent-python-processes", [peer.context for peer in (alice, bob)])
    actual = observer.result(case, "players")["players"]
    refs = alice.call("players")
    assert names(refs) == {client.name for client in game}
    for client in game:
        player = alice.call("getPlayer", target=client.name)
        assert player["rootId"] == client.entity_id and player["player"]["uuid"] == client.uuid
        assert alice.call("getPlayer", target=client.uuid)["player"] == player["player"]
    bob.call("players")
    context = alice.call("context", player=game[1].name)
    assert names(context["original"]) == {game[0].name}
    assert names(context["rebound"]) == {game[1].name}
    assert context["cleared"]["type"] == "MissingContextError"
    for peer, client in zip((alice, bob), game):
        assert names(peer.call("players", target="@s")) == {client.name}
        assert names(peer.call("players", target="@p")) == {client.name}
        assert names(peer.call("players", target="@a[distance=..5]")) == {client.name}
    assert len(alice.call("players", target="@r")) == 1
    assert alice.call("players", target="@a[tag=absent_i05]") == []
    invalid = alice.call("players", target="@a[", error="InvalidSelectorError")
    check("players-runtime-id-uuid-context-vanilla-selectors-and-typed-errors",
          {"observer": actual, "context": context, "invalid": invalid})

    # Keep Alice at her original position until the independent real-damage
    # assertion. A loaded chunk alone does not establish entity ticking.
    for client in game:
        observer.result(case, "inventoryFixture", client.name, "empty")
    alice.start("give", item="IRON_SWORD")
    bob.start("give", item="EMERALD", amount=2, name="I05 reward")
    rewards = [alice.result(), bob.result()]
    assert all(row["matched"] == row["applied"] == 1 for row in rewards)
    inventory = [observer.result(case, "inventory", client.name) for client in game]
    assert amount(inventory[0], "minecraft:iron_sword") == 1
    assert amount(inventory[0], "minecraft:emerald") == 0
    assert amount(inventory[1], "minecraft:emerald") == 2
    observer.result(case, "inventoryFixture", game[0].name, "partial")
    partial = alice.call("give", item="DIAMOND", amount=10)
    row = partial["targets"][0]
    assert row["requested"] == 10 and row["given"] == 4 and sum(v["amount"] for v in row["leftovers"]) == 6
    observer.result(case, "inventoryFixture", game[0].name, "full")
    full = alice.call("give", item="DIAMOND", amount=10)
    assert full["targets"][0]["given"] == 0 and sum(v["amount"] for v in full["targets"][0]["leftovers"]) == 10
    dropped = alice.call("give", item="DIAMOND", amount=10, overflow="drop")
    assert dropped["targets"][0]["dropped"] == 10
    drops = observer.result(case, "nearbyDrops", world["uuid"], 128, 200, 128, 16)
    assert sum(row["item"]["amount"] for row in drops["items"] if row["item"]["key"] == "minecraft:diamond") == 10
    check("two-process-self-inventory-named-items-partial-full-and-overflow",
          {"rewards": rewards, "inventory": inventory, "partial": partial, "full": full, "drop": dropped})

    cow = alice.call("spawn", entity="COW", position=[176.25, 200, 128.75])
    observer.result(case, "entityHold", cow["uuid"])
    applied = alice.call("effect", target=[game[0].name, "COW"])
    assert applied["matched"] == applied["applied"] == 2
    for uuid in (game[0].uuid, cow["uuid"]):
        snapshot = observer.result(case, "entityState", uuid)
        speed = next(row for row in snapshot["effects"] if row["key"] == "minecraft:speed")
        assert speed["amplifier"] == 1 and speed["particles"] is False and 500 <= speed["duration"] <= 600
    item = alice.call("spawn", entity="ITEM", position=[192.25, 201, 128.75], item="EMERALD", amount=4)
    item_state = observer.result(case, "entityHold", item["uuid"])
    assert item_state["item"]["key"] == "minecraft:emerald" and item_state["item"]["amount"] == 4
    before = observer.result(case, "entityState", game[1].uuid)["effects"]
    mixed = alice.call("effect", target=[game[1].name, "ITEM"], effect="JUMP_BOOST", error="InvalidTargetError")
    assert observer.result(case, "entityState", game[1].uuid)["effects"] == before
    falling = alice.call("spawn", entity="FALLING_BLOCK", position=[200.25, 210, 128.75],
                         block="minecraft:oak_log", states={"axis": "x"}, modernRoute=True)
    falling_state = observer.result(case, "entityHold", falling["uuid"])
    assert "axis=x" in falling_state["block"]
    unsupported = alice.call("spawn", entity="PLAYER", position=[200, 210, 128], error="UnsupportedEntityTypeError")
    check("effects-living-prevalidation-mob-item-falling-and-explicit-unsupported-player",
          {"effect": applied, "mixed": mixed, "item": item_state, "falling": falling_state, "unsupported": unsupported})

    adapters = []
    for index, kind in enumerate(("PAINTING", "ITEM_FRAME", "GLOW_ITEM_FRAME")):
        x = 256 + index * 16
        observer.result(case, "hangingFixture", world["uuid"], x, 200, 128)
        created = alice.call("spawn", entity=kind, position=[x + .5, 200.5, 128.5], face="south")
        state = observer.result(case, "entityState", created["uuid"])
        assert state["exists"] and state["valid"] and state["face"] == "south"
        adapters.append(state)
    observer.result(case, "inventoryFixture", game[0].name, "fishing-rod")
    hook = alice.call("spawn", entity="FISHING_BOBBER", position=[132.25, 201, 132.75], owner=game[0].name)
    assert observer.result(case, "entityState", hook["uuid"])["owner"] == game[0].uuid
    victim = observer.result(case, "livingFixture", world["uuid"], 132.5, 200, 132.5)
    ticking = observer.await_value(case, "entityState", (victim["uuid"],), lambda row:
        row.get("ticking") is True and row.get("ticksLived", 0) >= 2, timeout=20)
    assert ticking["health"] == 10
    strike = alice.call("spawn", entity="LIGHTNING_BOLT", position=[132.5, 200, 132.5])
    events = observer.await_value(case, "lightningEvents", (), lambda row:
        any(v["uuid"] == strike["uuid"] for v in row["strikes"]) and
        any(v["entity"] == victim["uuid"] for v in row["damage"]), timeout=8)
    assert any(v["uuid"] == strike["uuid"] and not v["effect"] and not v["cancelled"] for v in events["strikes"])
    assert any(v["entity"] == victim["uuid"] and v["lightning"] == strike["uuid"] and
               v["damage"] > 0 and not v["cancelled"] for v in events["damage"])
    damaged = observer.result(case, "entityState", victim["uuid"])
    assert damaged["exists"] and damaged["health"] < ticking["health"]
    check("special-spawn-adapters-and-real-lightning-gameplay-damage",
          {"adapters": adapters, "hook": hook, "ticking": ticking, "strike": strike, "damage": events, "after": damaged})

    before_bob = bob.call("position")
    moved = bob.call("teleport", position=[176.25, 210.5, 144.75])
    assert moved["matched"] == moved["applied"] == 1
    after_bob = next(row for row in observer.result(case, "players")["players"] if row["name"] == game[1].name)
    assert [after_bob[axis] for axis in ("x", "y", "z")] == [176.25, 210.5, 144.75]
    marker = "I05-" + harness.run_id
    alice.call("chat", message=marker)
    receipts = [client.wait_chat(marker) for client in game]
    check("fractional-position-teleport-and-real-chat-packets", {"before": before_bob, "after": after_bob, "chat": receipts})

    y = world["maxYExclusive"] - 40
    anchors = [(x, y, z) for x in (128, 144) for z in (128, 144)] + [(128, y + 2, 128), (130, y + 2, 128)]
    blocks_case = observer.case_id()
    observer.result(blocks_case, "setup", world["uuid"], *("%d,%d,%d" % at for at in anchors))
    blocks = alice.call("blocks", y=y)
    for at, key, states in ((anchors[-2], "minecraft:oak_stairs", {"facing": "east", "half": "top"}),
                            (anchors[-1], "minecraft:oak_log", {"axis": "x"})):
        actual = observer.result(case, "read", world["uuid"], *at)
        assert actual["key"] == key and all(actual["properties"][k] == v for k, v in states.items())
    check("root-and-modern-blocks-regions-negative-coordinates-states-read-barriers", blocks)

    concurrent = []
    for index, peer in enumerate((alice, bob)):
        start, end = [256, y + index * 10, 256], [271, y + index * 10 + 7, 271]
        peer.start("setBlocks", **{"from": start, "to": end, "block": 1 + index * 3})
        concurrent.append({"from": start, "to": end})
    done = [alice.result(), bob.result()]
    intervals = [peer.history[-1] for peer in (alice, bob)]
    assert max(row["startedNs"] for row in intervals) < min(row["finishedNs"] for row in intervals), intervals
    shared_case = observer.case_id()
    snapshot = observer.result(shared_case, "setup", world["uuid"],
                               *("%d,%d,%d" % tuple(row["to"]) for row in concurrent))
    assert [row["key"] for row in snapshot["originals"]] == ["minecraft:stone", "minecraft:cobblestone"]
    observer.result(shared_case, "cleanup")
    check("two-process-concurrent-disjoint-regions-and-independent-self",
          {"regions": concurrent, "results": done, "processIntervals": intervals, "oracle": snapshot["originals"],
           "self": [alice.call("players", target="@s"), bob.call("players", target="@s")]})

    reservation_case = observer.case_id()
    first, last = [512, y, 512], [575, y + 15, 575]
    observer.result(reservation_case, "setup", world["uuid"], "%d,%d,%d" % tuple(first))
    alice.start("setBlocks", **{"from": first, "to": last})
    observer.await_value(case, "read", (world["uuid"], *first), lambda row: row["key"] == "minecraft:cobblestone", timeout=30)
    assert alice.events.empty(), "Reservation completed before conflict was attempted"
    conflict = bob.call("set", position=first, error="RegionBusyError")
    bob.call("set", position=[240, y, 240], block=1)
    assert alice.events.empty(), "Other-session progress was not observed during the active job"
    alice.result(timeout=90)
    check("overlap-reservation-conflict-does-not-break-other-session", {"conflict": conflict, "otherSessionProgress": True})
    observer.result(reservation_case, "cleanup")

    far = [20_000, y, 20_000]
    before = observer.result(case, "checkChunk", world["uuid"], 1250, 1250)
    assert not before["loaded"]
    far_result = alice.call("far", position=far)
    far_case = observer.case_id()
    oracle = observer.result(far_case, "setup", world["uuid"], "%d,%d,%d" % tuple(far))
    assert oracle["originals"][0]["key"] == "minecraft:cobblestone"
    observer.result(far_case, "cleanup")
    far_mob = alice.call("spawn", entity="COW", position=[22_000.25, 220, 22_000.75])
    spawn_event = next(row for row in observer.result(case, "farSpawnEvents")["spawns"] if row["uuid"] == far_mob["uuid"])
    assert spawn_event["x"] == 22_000.25 and spawn_event["cancelled"] is False
    far_teleport = bob.call("teleport", position=[24_000.25, 220.5, 24_000.75])
    assert far_teleport["matched"] == far_teleport["applied"] == 1
    check("unloaded-chunks-generate-for-block-read-write-spawn-and-teleport",
          {"before": before, "block": far_result, "oracle": oracle["originals"], "spawn": spawn_event, "teleport": far_teleport})

    nether = next(row for row in observer.result(case, "worlds")["worlds"] if row["name"].endswith("_nether"))
    observer.result(case, "playerPlace", game[1].name, nether["uuid"], 128, 200, 128)
    mismatch = bob.call("players", target="@p", error="ContextWorldMismatchError")
    assert names(alice.call("players")) == {client.name for client in game}
    observer.result(case, "playerPlace", game[1].name, world["uuid"], 160, 200, 128)
    check("context-world-mismatch-is-explicit-and-group-selector-remains-global", mismatch)

    before_stats = observer.result(case, "serverStats")
    alice.call("benchmark", count=100, repeats=1, y=y)
    buffered100 = alice.call("benchmark", count=100, repeats=5, y=y)
    buffered1000 = alice.call("benchmark", count=1000, repeats=2, y=y)
    sync = Worker(harness, mode="sync")
    workers.append(sync)
    synchronous = sync.call("benchmark", count=100, repeats=1, y=y)
    sync.close()
    after_stats = observer.result(case, "serverStats")
    median = statistics.median(row["completedSeconds"] for row in buffered100)
    assert median <= .5, ("buffered100 regression target", median)
    performance = {"buffered100": buffered100, "buffered100MedianSeconds": median,
                   "buffered1000": buffered1000, "sync100": synchronous,
                   "newChunkReadWriteSeconds": far_result["seconds"],
                   "serverBefore": before_stats, "serverAfter": after_stats,
                   "claim": "Local loopback, two players; no classroom-load or LAN performance claim"}
    harness.manifest["performance"] = performance
    check("repeat-buffered100-1000-sync-baseline-and-independent-paper-tps-mspt", performance)
    observer.result(blocks_case, "cleanup")
    alice.close()
    bob.close()


def faults_and_shutdown(harness, paper, observer, case, world, check, workers):
    at = [128, world["maxYExclusive"] - 8, 128]
    results = {}
    for barrier in ("write", "flush", "read", "close"):
        peer = Worker(harness)
        workers.append(peer)
        context = peer.call("describe")
        session, request = context["sessionId"], context["nextRequestId"]
        gate_case = observer.case_id()
        observer.result(gate_case, "gateArm", session, request)
        release = harness.workspace / ("deferred-" + barrier)
        peer.start("deferred", position=at, barrier=barrier, gate=str(release))
        signal = peer.event()
        assert signal["type"] == "buffered", signal
        observer.await_value(gate_case, "gateStatus", (session, request), lambda row: row["state"] == "GATED")
        observer.result(gate_case, "gateRelease", session, request)
        if barrier == "write":
            release.write_text("released", encoding="utf-8")
        row = peer.result(error="InvalidBlockError")
        assert row["error"]["outcome"] == "not-applied" and row["error"]["method"] == "blocks.set"
        assert row["error"]["requestId"] == request
        results[barrier] = row
        peer.close()
    check("deferred-errors-surface-on-next-write-flush-read-and-close", results)

    with FaultProxy(token=harness.token, evidence=harness.artifacts / "connection-break.json", upstream_port=harness.port) as proxy:
        peer = Worker(harness, port=proxy.port)
        workers.append(peer)
        peer.start("set", position=at)
        held = proxy.await_captured(timeout=10)
        started = time.perf_counter()
        proxy.drop()
        failure = peer.result(error="ConnectionError", timeout=15)
        assert failure["error"]["outcome"] == "unknown"
        peer.close()
        assert proxy.wait_closed(timeout=5)
        snapshot = proxy.snapshot()
        assert len(snapshot["connections"]) == 1 and snapshot["connections"][0]["mutationRequests"] == 1
        check("one-connection-break-pending-mutation-bounded-unknown-no-retry",
              {"heldRealResponse": held, "failure": failure, "seconds": time.perf_counter() - started, "proxy": snapshot})

    waiting = Worker(harness)
    workers.append(waiting)
    context = waiting.call("describe")
    session, request = context["sessionId"], context["nextRequestId"]
    shutdown_case = observer.case_id()
    observer.result(shutdown_case, "gateArm", session, request)
    waiting.start("set", position=at)
    observer.await_value(shutdown_case, "gateStatus", (session, request), lambda row: row["state"] == "GATED")
    started = time.perf_counter()
    mode = paper.finish()
    failure = waiting.result(error="ConnectionError", timeout=15)
    assert failure["error"]["outcome"] == "unknown"
    waiting.close()
    require_port_free(harness.game_port)
    check("normal-server-shutdown-bounds-waiting-write-frees-ports-and-client-threads",
          {"failure": failure, "seconds": time.perf_counter() - started, "bridgePortFree": True, "gamePortFree": True})
    return mode


def run(wheel, production, python):
    summary = {"stage": "I05", "allPassed": False, "runs": [], "worlds": []}
    target = ROOT / ".work/i05-paper-results.json"
    first_config = first_port = None
    try:
        for number in (1, 2):
            harness = I05Harness(production, wheel, python, number=number, port=first_port)
            harness.prepare()
            config = (harness.server / "plugins/Minebridge/config.yml").read_bytes()
            if first_config is None:
                first_config, first_port = config, harness.port
            assert config == first_config
            summary["runs"].append(str(harness.artifacts / "manifest.json"))
            save(target, summary)
            clients, workers = [], []
            def check(name, result):
                harness.manifest["checks"].append({"name": name, "passed": True, "result": result})
                harness.save_manifest()
                print(json.dumps({"passed": name}), flush=True)
            print(json.dumps({"phase": "server-start", "number": number, "workspace": str(harness.workspace)}), flush=True)
            try:
                with I03Paper(harness, control=number == 1, mode="combined" if number == 1 else "production-fresh-world") as paper:
                    paper.wait_ready()
                    observer = ObserverClient(paper, harness.artifacts / "observer.json")
                    case = observer.case_id()
                    world = next(row for row in observer.result(case, "worlds")["worlds"] if row["name"] == harness.world_name)
                    summary["worlds"].append(world)
                    if number == 1:
                        protocol = observer.result(case, "gameProtocol")
                        save(harness.artifacts / "game-protocol.json", protocol)
                        for name in ("V02Alice", "V02Bob"):
                            client = GameClient(harness.game_port, name, protocol)
                            clients.append(client)
                            client.wait_ready()
                        for index, client in enumerate(clients):
                            observer.result(case, "playerPlace", client.name, world["uuid"], 128 + index * 32, 200, 128)
                        check("two-real-minecraft-game-clients", [client.evidence() for client in clients])
                        full_acceptance(harness, paper, observer, case, world, clients, check, workers)
                        for client in clients:
                            assert not client.errors, client.evidence()
                            client.close()
                        mode = faults_and_shutdown(harness, paper, observer, case, world, check, workers)
                    else:
                        status = observer.result(case, "status")
                        assert status["controlEnabled"] is False
                        peer = Worker(harness)
                        workers.append(peer)
                        assert peer.context["world"]["uuid"] == world["uuid"]
                        peer.call("set", position=[128, world["maxYExclusive"] - 8, 128])
                        assert peer.call("read", position=[128, world["maxYExclusive"] - 8, 128]) == 4
                        peer.close()
                        check("production-control-disabled-two-argument-connect-new-automatic-overworld",
                              {"context": peer.context, "observer": status, "world": world})
                        mode = paper.finish()
                        require_port_free(harness.game_port)
                    harness.manifest["modes"].append(mode)
                for artifact in harness.manifest["artifacts"].values():
                    assert sha256(Path(artifact["path"])) == artifact["sha256"], "Acceptance input changed"
                for relative, digest in harness.manifest["scripts"].items():
                    assert sha256(ROOT / relative) == digest, "Acceptance script changed: " + relative
                harness.manifest["allPassed"] = True
            finally:
                for client in clients:
                    client.close()
                for peer in workers:
                    peer.abort()
                harness.manifest["finalGameClients"] = [client.evidence() for client in clients]
                harness.save_manifest()
        assert summary["worlds"][0]["name"] != summary["worlds"][1]["name"]
        assert summary["worlds"][0]["uuid"] != summary["worlds"][1]["uuid"]
        summary["identicalBridgeConfigSha256"] = hashlib.sha256(first_config).hexdigest()
        summary["allPassed"] = True
    finally:
        save(target, summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin", type=Path, default=ROOT / "dist/v0.2/minebridge-paper-0.2.0.jar")
    parser.add_argument("--wheel", type=Path, default=ROOT / "dist/v0.2/minebridge-0.2.0-py3-none-any.whl")
    parser.add_argument("--python", type=Path, default=ROOT / ".venv-v02-314/Scripts/python.exe")
    arguments = parser.parse_args()
    print(json.dumps(run(arguments.wheel, arguments.plugin, arguments.python), indent=2))
