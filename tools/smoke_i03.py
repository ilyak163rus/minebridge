"""Compact I03 acceptance: real pinned Paper, two game clients, source Python.

Only temporary development/test plugin JARs are used. No wheel or release
archive is built, and existing project EULA consent is copied unchanged.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import json
from pathlib import Path
import queue
import shutil
import sys
import threading
import time
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "python/src"
sys.path.insert(0, str(ROOT / "integration/tests"))
import conftest
from conftest import Harness, PaperRun, free_game_port, require_port_free, sha256
from game_client import GameClient
from observer_client import ObserverClient


class I03Harness(Harness):
    def __init__(self, production: Path, *, prototype=False):
        super().__init__(SOURCE / "minebridge/__init__.py", stage="T10")
        self.stage, self.world_name = "I03", "i03-lesson"
        self.workspace = ROOT / ".work" / ("i03-" + self.run_id)
        self.server = self.workspace / "server"
        self.artifacts = ROOT / "integration/artifacts" / ("i03-" + self.run_id)
        self.production = production.resolve()
        self.port = free_game_port()
        conftest.BRIDGE_PORT = self.port
        self.prototype = prototype

    def prepare(self):
        require_port_free(self.port)
        assert not self.workspace.exists() and not self.artifacts.exists()
        paper = Path(self.toolchain["paperJar"])
        for artifact in (self.java, self.production, self.observer, paper):
            assert artifact.is_file(), artifact
        assert sha256(paper) == self.toolchain["artifacts"]["paper"]["sha256"]
        consent = ROOT / ".work/t02-server/eula.txt"
        assert "eula=true" in consent.read_text(encoding="utf-8").splitlines()
        self.server.mkdir(parents=True)
        self.artifacts.mkdir(parents=True)
        for name in ("libraries", "cache", "versions"):
            source = ROOT / ".work/t02-server" / name
            if source.is_dir():
                shutil.copytree(source, self.server / name)
        shutil.copy2(consent, self.server / "eula.txt")
        plugins = self.server / "plugins"
        (plugins / "Minebridge").mkdir(parents=True)
        shutil.copy2(self.production, plugins / "Minebridge.jar")
        shutil.copy2(self.observer, plugins / "MinebridgeObserver.jar")
        (plugins / "Minebridge/config.yml").write_text(
            "listenAddress: '127.0.0.1'\n" + f"port: {self.port}\n", encoding="utf-8")
        template = (ROOT / "integration/configs/server.properties").read_text(encoding="utf-8")
        template = template.replace("online-mode=true", "online-mode=false").replace("max-players=1", "max-players=4")
        (self.server / "server.properties").write_text(
            template.format(game_port=self.game_port, world_name=self.world_name)
            + "\nenforce-secure-profile=false\nnetwork-compression-threshold=256\n", encoding="utf-8")
        self.manifest = {"schemaVersion": 1, "stage": "I03", "runId": self.run_id,
            "prototypeOnly": self.prototype, "server": str(self.server), "world": self.world_name,
            "network": {"address": "127.0.0.1", "bridgePort": self.port, "gamePort": self.game_port,
                        "offlineModeDisposableFixture": True},
            "artifacts": {"paper": self.describe(paper), "production": self.describe(self.production),
                          "observer": self.describe(self.observer)},
            "pythonSources": str(SOURCE), "releasePackaged": False, "wheelBuilt": False,
            "pythonSourceSha256": {} if self.prototype else {str(path.relative_to(SOURCE)): sha256(path)
                for path in sorted((SOURCE / "minebridge").rglob("*"))
                if path.is_file() and "__pycache__" not in path.parts},
            "eula": {"copiedExistingConsent": True, "acceptedAutomatically": False},
            "checks": [], "modes": [], "allPassed": False}
        self.save_manifest()


class I03Paper(PaperRun):
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
            listener |= f"TCP listener ready on port {self.harness.port}." in line
            observer |= "[MinebridgeObserver]" in line and "Enabling" in line
            if done and listener and observer:
                return
        raise AssertionError("I03 Paper readiness deadline elapsed: " + str(self.log))


def run(production: Path, *, prototype=False):
    harness = I03Harness(production, prototype=prototype)
    harness.prepare()
    print(json.dumps({"phase": "server-start", "workspace": str(harness.workspace)}), flush=True)
    summary = {"stage": "I03", "allPassed": False, "manifest": str(harness.artifacts / "manifest.json")}

    def check(name, result):
        harness.manifest["checks"].append({"name": name, "passed": True, "result": result})
        harness.save_manifest()
        print(json.dumps({"passed": name}), flush=True)
        return result

    clients = []
    try:
        with I03Paper(harness, control=True, mode="i03-players") as paper:
            paper.wait_ready()
            observer = ObserverClient(paper, harness.artifacts / "observer.json")
            case = observer.case_id()
            protocol = observer.result(case, "gameProtocol")
            (harness.artifacts / "game-protocol.json").write_text(json.dumps(protocol, indent=2), encoding="utf-8")
            for name in ("I03Alice", "I03Bob"):
                client = GameClient(harness.game_port, name, protocol)
                clients.append(client)
                client.wait_ready()
            world_rows = observer.result(case, "worlds")["worlds"]
            world = next(row for row in world_rows if row["name"] == harness.world_name)
            for index, client in enumerate(clients):
                observer.result(case, "playerPlace", client.name, world["uuid"], 128 + index * 32, 200, 128)
            actual = observer.result(case, "players")["players"]
            assert len(actual) == 2
            for client in clients:
                row = next(row for row in actual if row["name"] == client.name)
                assert row["uuid"] == client.uuid and row["entityId"] == client.entity_id
            check("two-real-game-clients", {"clients": [client.evidence() for client in clients],
                                             "observerPlayers": actual})
            if prototype:
                paper.command("say I03-prototype-chat")
                check("game-client-chat-receipt", [client.wait_chat("I03-prototype-chat") for client in clients])
            else:
                acceptance(harness, paper, observer, case, world_rows, clients, check)
            for client in clients:
                assert not client.errors, client.evidence()
                client.close()
            harness.manifest["modes"].append(paper.finish())
        for artifact in harness.manifest["artifacts"].values():
            assert sha256(Path(artifact["path"])) == artifact["sha256"], "Acceptance input changed"
        for relative, digest in harness.manifest["pythonSourceSha256"].items():
            assert sha256(SOURCE / relative) == digest, "Python acceptance input changed: " + relative
        summary["allPassed"] = harness.manifest["allPassed"] = True
    finally:
        for client in clients:
            client.close()
        harness.save_manifest()
        target = ROOT / ".work" / ("i03-prototype-results.json" if prototype else "i03-paper-results.json")
        target.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def acceptance(harness, paper, observer, case, world_rows, clients, check):
    sys.path.insert(0, str(SOURCE))
    import minebridge
    from minebridge import Minecraft, block, selector
    from minebridge.errors import (ContextWorldMismatchError, InvalidSelectorError,
        InvalidTargetError, MissingContextError, PlayerNotFoundError)
    from minebridge.models import EntityRef

    assert Path(minebridge.__file__).resolve().is_relative_to(SOURCE)
    world = next(row for row in world_rows if row["name"] == harness.world_name)

    def expect(error, action):
        try:
            action()
        except error as failure:
            return {"type": type(failure).__name__, "code": failure.code,
                    "outcome": failure.outcome}
        raise AssertionError("Expected " + error.__name__)

    def names(players):
        return {player.name for player in players}

    def outcome(result):
        return {"matched": result.matched, "applied": result.applied,
                "targets": [{"uuid": str(row.uuid), "applied": row.applied, "code": row.code}
                            for row in result.targets]}

    def position(location):
        return {name: getattr(location, name) for name in ("world", "x", "y", "z", "yaw", "pitch")}

    def actual_players():
        return {row["name"]: row for row in observer.result(case, "players")["players"]}

    with ExitStack() as cleanup:
        unbound = Minecraft.create("127.0.0.1", harness.port)
        cleanup.callback(unbound.close)
        bob = Minecraft.create("127.0.0.1", harness.port, player="I03Bob")
        cleanup.callback(bob.close)
        alice = unbound.withContext(player="I03Alice")
        sessions = [unbound._transport.context.session_id, bob._transport.context.session_id]
        assert sessions[0] != sessions[1]
        refs = {player.name: player for player in unbound.players.list()}
        assert set(refs) == {"I03Alice", "I03Bob"}
        for client in clients:
            ref = refs[client.name]
            assert str(ref.uuid) == client.uuid and ref.entityId == client.entity_id
            assert unbound.getPlayerEntityId(client.name) == client.entity_id
            assert unbound.players.get(ref.uuid) == ref
            assert unbound.players.get(str(ref.uuid)) == ref
        assert names(alice.players.list(selector.SELF)) == {"I03Alice"}
        assert names(bob.players.list(selector.SELF)) == {"I03Bob"}
        assert names(alice.withContext(player=refs["I03Bob"]).players.list(selector.SELF)) == {"I03Bob"}
        missing = expect(MissingContextError, lambda: unbound.players.list(selector.SELF))
        assert names(alice.players.list(selector.SELF)) == {"I03Alice"}
        missing_cleared = expect(MissingContextError, lambda: alice.withContext().players.list(selector.SELF))
        check("lookup-uuid-runtime-id-context-views-no-implicit-bind", {
            "sessionIds": sessions, "unboundSelf": missing, "clearedSelf": missing_cleared,
            "refs": [{"name": ref.name, "uuid": str(ref.uuid), "entityId": ref.entityId} for ref in refs.values()]})

        assert names(unbound.players.list(selector.ALL_PLAYERS)) == set(refs)
        random = unbound.players.list(selector.RANDOM_PLAYER)
        assert len(random) == 1 and random[0].name in refs
        assert names(alice.players.list(selector.NEAREST_PLAYER)) == {"I03Alice"}
        assert names(bob.players.list(selector.NEAREST_PLAYER)) == {"I03Bob"}
        assert names(unbound.players.list("@a[name=I03Bob]")) == {"I03Bob"}
        assert names(alice.players.list("@a[distance=..5]")) == {"I03Alice"}
        assert names(alice.players.list('@a["distance"=..5]')) == {"I03Alice"}
        assert names(bob.players.list("@a[distance=..5]")) == {"I03Bob"}
        assert names(unbound.players.list(list(refs.values()))) == set(refs)
        assert unbound.players.list("@a[tag=never_i03_fixture]") == []
        empty = unbound.players.teleport("@a[tag=never_i03_fixture]", 12, 200, 12)
        assert empty.matched == empty.applied == 0 and not empty.targets
        invalid = {
            "nearestWithoutContext": expect(MissingContextError, lambda: unbound.players.list(selector.NEAREST_PLAYER)),
            "distanceWithoutContext": expect(MissingContextError, lambda: unbound.players.list("@a[distance=..5]")),
            "quotedDistanceWithoutContext": expect(MissingContextError, lambda: unbound.players.list('@a["distance"=..5]')),
            "syntax": expect(InvalidSelectorError, lambda: unbound.players.list("@a[")),
            "missingExactPlayer": expect(PlayerNotFoundError, lambda: unbound.getPlayerEntityId("NobodyI03")),
            "multiplePositions": expect(InvalidTargetError, lambda: unbound.players.getPos(selector.ALL_PLAYERS)),
        }
        check("vanilla-selectors-origin-empty-and-typed-errors", {
            "randomPlayer": random[0].name, "emptyTeleport": outcome(empty), "errors": invalid})

        at = alice.players.getPos(selector.SELF)
        assert position(at) == {"world": harness.world_name, "x": 128., "y": 200., "z": 128., "yaw": 0., "pitch": 0.}
        moved = alice.players.teleport(selector.SELF, 144.25, 210.5, 144.75)
        assert moved.matched == moved.applied == 1
        assert moved.targets[0].uuid == refs["I03Alice"].uuid and moved.targets[0].applied
        after = actual_players()["I03Alice"]
        assert (after["x"], after["y"], after["z"]) == (144.25, 210.5, 144.75)
        assert position(alice.players.getPos(refs["I03Alice"]))["x"] == 144.25
        check("fractional-position-and-teleport-independent-observer", {"result": outcome(moved), "observer": after})

        fixture = observer.result(case, "entityFixture", world["uuid"], 150, 210, 144)
        before = actual_players()
        errors = {
            "allEntities": expect(InvalidTargetError, lambda: alice.players.teleport(selector.ALL_ENTITIES, 180, 220, 180)),
            "nonplayerUuid": expect(InvalidTargetError, lambda: alice.players.teleport(fixture["uuid"], 180, 220, 180)),
            "mixedReferenceList": expect(InvalidTargetError, lambda: alice.players.teleport(
                [refs["I03Alice"], EntityRef(UUID(fixture["uuid"]), fixture["entityId"])], 180, 220, 180)),
        }
        assert actual_players() == before, "Invalid target mutation moved a player before full validation"
        check("whole-target-set-prevalidation-no-partial-teleport", {"fixture": fixture, "errors": errors, "unchanged": True})

        marker = "I03-buffered-" + harness.run_id
        unbound.setBlock(160, 210, 128, block.COBBLESTONE)
        unbound.postToChat(marker)
        # A synchronous player lookup is a FIFO barrier for both prior writes.
        assert unbound.players.get("I03Alice") == refs["I03Alice"]
        snapshot = observer.result(case, "read", world["uuid"], 160, 210, 128)
        assert snapshot["key"] == "minecraft:cobblestone"
        chats = [client.wait_chat(marker) for client in clients]
        unbound.flush()
        check("buffered-block-chat-player-read-barrier-real-chat-receipt", {"block": snapshot, "clients": chats})

        gate = threading.Barrier(2)

        def concurrent(client, index):
            gate.wait(timeout=10)
            result = client.players.teleport(selector.SELF, 256.25 + index * 32, 220.5, 256.75)
            client.postToChat("I03-concurrent-" + str(index) + "-" + harness.run_id)
            current = client.players.getPos(selector.SELF)
            assert result.matched == result.applied == 1
            assert current.x == 256.25 + index * 32
            return {"teleport": outcome(result), "position": position(current)}

        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="i03-sessions") as pool:
            futures = [pool.submit(concurrent, facade, index) for index, facade in enumerate((alice, bob))]
            concurrent_results = [future.result(timeout=45) for future in futures]
        for index in (0, 1):
            for client in clients:
                client.wait_chat("I03-concurrent-" + str(index) + "-" + harness.run_id)
        check("two-simultaneous-python-sessions-independent-self", {"sessions": sessions, "results": concurrent_results})

        far = [20_000.25, 220.5, 20_000.75]
        prior = observer.result(case, "checkChunk", world["uuid"], 1250, 1250)
        assert not prior["loaded"], "Far teleport fixture unexpectedly loaded beforehand"
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="i03-chunks") as pool:
            started = time.perf_counter()
            future = pool.submit(alice.players.teleport, selector.SELF, *far)
            bob.setBlock(288, 219, 256, block.STONE)
            assert names(bob.players.list(selector.SELF)) == {"I03Bob"}
            other_completed = time.perf_counter() - started
            far_result = future.result(timeout=60)
        assert far_result.matched == far_result.applied == 1
        after = actual_players()["I03Alice"]
        assert [after["x"], after["y"], after["z"]] == far
        assert alice.players.getPos(selector.SELF).x == far[0]
        check("far-teleport-loads-chunk-other-session-progress", {"before": prior, "teleport": outcome(far_result),
            "observer": after, "otherSessionSeconds": other_completed, "totalSeconds": time.perf_counter() - started})

        nether = next(row for row in world_rows if row["name"].endswith("_nether"))
        observer.result(case, "playerPlace", "I03Alice", nether["uuid"], 128, 200, 128)
        mismatch = expect(ContextWorldMismatchError, lambda: alice.players.list(selector.NEAREST_PLAYER))
        assert names(unbound.players.list(selector.ALL_PLAYERS)) == set(refs)
        observer.result(case, "playerPlace", "I03Alice", world["uuid"], 128, 200, 128)
        assert names(alice.players.list(selector.SELF)) == {"I03Alice"}
        clients[1].close()
        observer.await_value(case, "players", (), lambda row: len(row["players"]) == 1)
        stale = expect(PlayerNotFoundError, lambda: bob.players.list(selector.SELF))
        assert names(alice.players.list(selector.SELF)) == {"I03Alice"}
        check("executor-world-mismatch-and-offline-binding", {"worldMismatch": mismatch, "offlineExecutor": stale})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin", type=Path, default=ROOT / "plugin/build/libs/minebridge-paper-0.2.0-dev1.jar")
    parser.add_argument("--prototype", action="store_true")
    arguments = parser.parse_args()
    print(json.dumps(run(arguments.plugin, prototype=arguments.prototype), indent=2))
