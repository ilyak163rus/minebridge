"""Compact I04 source acceptance on pinned Paper with two real game clients.

Uses only temporary test JARs and Python sources. Never builds a wheel or writes
release packages. Existing project EULA consent is reused unchanged.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import asdict, is_dataclass
import json
from pathlib import Path
import sys
import threading
import time
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke_i03 import I03Harness, I03Paper, ROOT, SOURCE
from conftest import sha256
from game_client import GameClient
from observer_client import ObserverClient


class I04Harness(I03Harness):
    def __init__(self, production):
        super().__init__(production)
        self.stage, self.world_name = "I04", "i04-lesson"
        self.workspace = ROOT / ".work" / ("i04-" + self.run_id)
        self.server = self.workspace / "server"
        self.artifacts = ROOT / "integration/artifacts" / ("i04-" + self.run_id)

    def prepare(self):
        super().prepare()
        self.manifest["stage"] = "I04"
        self.save_manifest()


def evidence(value):
    if is_dataclass(value):
        return evidence(asdict(value))
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): evidence(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [evidence(item) for item in value]
    return value


def run(production):
    harness = I04Harness(production)
    harness.prepare()
    print(json.dumps({"phase": "server-start", "workspace": str(harness.workspace)}), flush=True)
    summary = {"stage": "I04", "allPassed": False, "manifest": str(harness.artifacts / "manifest.json")}
    clients = []

    def check(name, result):
        harness.manifest["checks"].append({"name": name, "passed": True, "result": evidence(result)})
        harness.save_manifest()
        print(json.dumps({"passed": name}), flush=True)

    try:
        with I03Paper(harness, control=True, mode="i04-interactions") as paper:
            paper.wait_ready()
            observer = ObserverClient(paper, harness.artifacts / "observer.json")
            case = observer.case_id()
            protocol = observer.result(case, "gameProtocol")
            (harness.artifacts / "game-protocol.json").write_text(json.dumps(protocol, indent=2), encoding="utf-8")
            for name in ("I04Alice", "I04Bob"):
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
            check("two-real-game-clients", {"clients": [client.evidence() for client in clients], "players": actual})
            acceptance(harness, paper, observer, case, world, clients, check)
            for client in clients:
                assert not client.errors, client.evidence()
                client.close()
            harness.manifest["modes"].append(paper.finish())
        for artifact in harness.manifest["artifacts"].values():
            assert sha256(Path(artifact["path"])) == artifact["sha256"], "Acceptance artifact changed"
        for relative, digest in harness.manifest["pythonSourceSha256"].items():
            assert sha256(SOURCE / relative) == digest, "Acceptance source changed: " + relative
        summary["allPassed"] = harness.manifest["allPassed"] = True
    finally:
        for client in clients:
            client.close()
        harness.manifest["finalGameClients"] = [client.evidence() for client in clients]
        harness.save_manifest()
        (ROOT / ".work/i04-paper-results.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def acceptance(harness, paper, observer, case, world, clients, check):
    sys.path.insert(0, str(SOURCE))
    import minebridge
    from minebridge import Minecraft, block, effects, entity, items, selector
    from minebridge.models import EntityRef, ItemStack
    from minebridge.errors import InvalidTargetError, UnsupportedEntityTypeError

    assert Path(minebridge.__file__).resolve().is_relative_to(SOURCE)

    def expect(error, action):
        try:
            action()
        except error as failure:
            return {"type": type(failure).__name__, "code": failure.code, "outcome": failure.outcome}
        raise AssertionError("Expected " + error.__name__)

    def inventory(name):
        return observer.result(case, "inventory", name)

    def count(snapshot, key):
        return sum(slot["item"]["amount"] for slot in snapshot["slots"]
                   if slot["item"] is not None and slot["item"]["key"] == key)

    def state(ref):
        return observer.result(case, "entityState", str(ref.uuid))

    def conserved(result, *, requested, given, leftover, dropped):
        assert result.matched == result.applied == 1, result
        assert len(result.targets) == 1, result
        outcome = result.targets[0]
        assert outcome.applied is True and outcome.code is None, outcome
        assert (outcome.requested, outcome.given, sum(item.amount for item in outcome.leftovers),
                outcome.dropped) == (requested, given, leftover, dropped), outcome
        assert outcome.requested == outcome.given + sum(item.amount for item in outcome.leftovers) + outcome.dropped

    with ExitStack() as cleanup:
        alice = Minecraft.create("127.0.0.1", harness.port, player="I04Alice")
        bob = Minecraft.create("127.0.0.1", harness.port, player="I04Bob")
        cleanup.callback(alice.close)
        cleanup.callback(bob.close)
        assert alice._transport.context.session_id != bob._transport.context.session_id
        refs = {player.name: player for player in alice.players.list()}
        observer.result(case, "inventoryFixture", "I04Alice", "empty")
        observer.result(case, "inventoryFixture", "I04Bob", "empty")
        sword = alice.players.giveItem(selector.SELF, items.IRON_SWORD)
        assert sword.matched == sword.applied == 1
        assert count(inventory("I04Alice"), "minecraft:iron_sword") == 1
        prize = ItemStack(items.DIAMOND, amount=2, name="Награда I04", lore=("Строка 1", "Literal <red> text"))
        named = bob.players.giveItem(selector.SELF, prize, 3)
        snapshot = inventory("I04Bob")
        diamonds = [slot["item"] for slot in snapshot["slots"]
                    if slot["item"] is not None and slot["item"]["key"] == "minecraft:diamond"]
        assert sum(stack["amount"] for stack in diamonds) == 3
        assert all(stack["name"] == prize.name and stack["lore"] == list(prize.lore) for stack in diamonds)
        conserved(sword, requested=1, given=1, leftover=0, dropped=0)
        conserved(named, requested=3, given=3, leftover=0, dropped=0)
        random = alice.players.giveItem(selector.RANDOM_PLAYER, items.GOLD_INGOT, 1)
        assert random.matched == random.applied == 1
        assert sum(count(inventory(name), "minecraft:gold_ingot") for name in refs) == 1
        check("give-item-self-name-override-and-single-random-selection", {
            "standard": sword, "named": named, "random": random, "namedInventory": snapshot})

        observer.result(case, "inventoryFixture", "I04Alice", "partial")
        partial = alice.players.giveItem(selector.SELF, items.DIAMOND, 10)
        conserved(partial, requested=10, given=4, leftover=6, dropped=0)
        assert count(inventory("I04Alice"), "minecraft:diamond") == 64
        observer.result(case, "inventoryFixture", "I04Alice", "full")
        full = alice.players.giveItem(selector.SELF, items.DIAMOND, 10)
        conserved(full, requested=10, given=0, leftover=10, dropped=0)
        assert count(inventory("I04Alice"), "minecraft:diamond") == 0
        before_drops = observer.result(case, "nearbyDrops", world["uuid"], 128, 200, 128, 16)
        assert not before_drops["items"]
        dropped = alice.players.giveItem(selector.SELF, items.DIAMOND, 10, overflow="drop")
        conserved(dropped, requested=10, given=0, leftover=0, dropped=10)
        drops = observer.result(case, "nearbyDrops", world["uuid"], 128, 200, 128, 16)
        assert sum(row["item"]["amount"] for row in drops["items"]
                   if row["item"]["key"] == "minecraft:diamond") == 10
        check("partial-full-inventory-return-and-explicit-overflow-drop", {
            "partial": partial, "full": full, "drop": dropped, "independentDrops": drops})

        cow = alice.spawnEntity(176.25, 200, 128.75, entity.COW)
        cow_state = observer.result(case, "entityHold", str(cow.uuid))
        assert cow_state["type"] == "minecraft:cow" and cow_state["entityId"] == cow.entityId
        targets = [refs["I04Alice"], cow]
        affected = alice.effects.add(targets, effects.SPEED, duration=30, level=2, particles=False)
        assert affected.matched == affected.applied == 2
        observed_effects = []
        for target in targets:
            snapshot = state(target)
            speed = next(row for row in snapshot["effects"] if row["key"] == "minecraft:speed")
            assert 540 <= speed["duration"] <= 600, speed
            assert speed["amplifier"] == 1 and speed["particles"] is False, speed
            observed_effects.append(snapshot)
        invalid = alice.spawnEntity(184, 200, 128, entity.ITEM, item=ItemStack(items.STICK))
        before = state(refs["I04Bob"])
        failed = expect(InvalidTargetError, lambda: bob.effects.add(
            [refs["I04Bob"], invalid], effects.JUMP_BOOST, duration=30))
        assert state(refs["I04Bob"])["effects"] == before["effects"]
        check("effects-seconds-level-living-entities-and-whole-set-prevalidation", {
            "result": affected, "observer": observed_effects, "invalidMixedTarget": failed})

        item = alice.spawnEntity(192.25, 201, 128.75, entity.ITEM,
                                 item=ItemStack(items.EMERALD, amount=4, name="I04 item"))
        item_state = observer.result(case, "entityHold", str(item.uuid))
        assert item_state["type"] == "minecraft:item"
        assert item_state["item"] == {"key": "minecraft:emerald", "amount": 4, "name": "I04 item", "lore": None}
        falling = alice.spawnEntity(200.25, 210, 128.75, entity.FALLING_BLOCK,
                                    block=block.OAK_LOG.withStates(axis="x"))
        falling_state = observer.result(case, "entityHold", str(falling.uuid))
        assert falling_state["type"] == "minecraft:falling_block" and "axis=x" in falling_state["block"]
        unsupported = expect(UnsupportedEntityTypeError, lambda: alice.spawnEntity(200, 210, 128, entity.PLAYER))
        check("normal-mob-item-falling-block-and-explicit-unsupported-player", {
            "cow": cow_state, "item": item_state, "fallingBlock": falling_state, "player": unsupported})

        hanging_states = []
        for index, kind in enumerate((entity.PAINTING, entity.ITEM_FRAME, entity.GLOW_ITEM_FRAME)):
            x = 256 + index * 16
            fixture = observer.result(case, "hangingFixture", world["uuid"], x, 200, 128)
            hanging = alice.spawnEntity(x + .5, 200.5, 128.5, kind, face="south")
            snapshot = state(hanging)
            assert snapshot["exists"] and snapshot["valid"] and snapshot["type"] == kind.key, snapshot
            assert snapshot["face"] == "south", snapshot
            hanging_states.append({"fixture": fixture, "entity": hanging, "observer": snapshot})
        observer.result(case, "inventoryFixture", "I04Alice", "fishing-rod")
        hook = alice.spawnEntity(132.25, 201, 132.75, entity.FISHING_BOBBER, owner=refs["I04Alice"])
        hook_state = state(hook)
        assert hook_state["exists"] and hook_state["valid"] and hook_state["type"] == "minecraft:fishing_bobber", hook_state
        assert hook_state["owner"] == str(refs["I04Alice"].uuid), hook_state
        check("hanging-adapters-with-support-and-owned-fishing-bobber", {
            "hanging": hanging_states, "fishing": {"entity": hook, "observer": hook_state}})

        # Real damage requires ordinary entity ticking. A short chunk lease
        # permits creation without promising permanent simulation of remote
        # chunks; keep a real player nearby for this gameplay assertion.
        harness.manifest["lightningReadinessInputs"] = {
            "serverPlayers": observer.result(case, "players"),
            "gameClients": [client.evidence() for client in clients]}
        harness.save_manifest()
        lightning_fixture = observer.result(case, "livingFixture", world["uuid"], 132.5, 200, 132.5)
        # Teleport completion does not imply that the destination has finished
        # its asynchronous transition from BORDER to ENTITY_TICKING. Observe
        # actual game ticks before checking a short-lived lightning entity.
        ticking_fixture = observer.await_value(case, "entityState", (lightning_fixture["uuid"],),
            lambda row: row.get("ticking") is True and row.get("ticksLived", 0) >= 2, timeout=15)
        assert ticking_fixture["health"] == lightning_fixture["health"] == 10
        strike = alice.spawnEntity(132.5, 200, 132.5, entity.LIGHTNING_BOLT)
        events = observer.await_value(case, "lightningEvents", (), lambda row:
            any(value["uuid"] == str(strike.uuid) for value in row["strikes"])
            and any(value["entity"] == lightning_fixture["uuid"] for value in row["damage"]), timeout=8)
        actual_strike = next(row for row in events["strikes"] if row["uuid"] == str(strike.uuid))
        assert actual_strike["effect"] is False and actual_strike["cancelled"] is False
        damage = [row for row in events["damage"] if row["entity"] == lightning_fixture["uuid"]]
        assert any(row["damage"] > 0 and not row["cancelled"] for row in damage)
        assert any(row["lightning"] == str(strike.uuid) for row in damage)
        victim_after = observer.result(case, "entityState", lightning_fixture["uuid"])
        assert victim_after["exists"] and victim_after["health"] < ticking_fixture["health"], victim_after
        check("real-lightning-strike-and-independent-gameplay-damage", {
            "entity": strike, "fixtureBefore": lightning_fixture, "tickingFixture": ticking_fixture,
            "victimAfter": victim_after, "event": actual_strike, "damage": damage})

        observer.result(case, "inventoryFixture", "I04Alice", "empty")
        observer.result(case, "inventoryFixture", "I04Bob", "empty")
        gate = threading.Barrier(2)
        def session_work(client, material):
            gate.wait(timeout=10)
            reward = client.players.giveItem(selector.SELF, material, 2)
            buff = client.effects.add(selector.SELF, effects.NIGHT_VISION, duration=20)
            return {"reward": reward, "effect": buff}
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="i04-sessions") as pool:
            futures = [pool.submit(session_work, alice, items.DIAMOND), pool.submit(session_work, bob, items.EMERALD)]
            results = [future.result(timeout=30) for future in futures]
        assert count(inventory("I04Alice"), "minecraft:diamond") == 2
        assert count(inventory("I04Alice"), "minecraft:emerald") == 0
        assert count(inventory("I04Bob"), "minecraft:emerald") == 2
        assert count(inventory("I04Bob"), "minecraft:diamond") == 0
        check("two-concurrent-sessions-self-rewards-and-effects", results)

        before = observer.result(case, "checkChunk", world["uuid"], 1250, 1250)
        assert not before["loaded"]
        spawn_started = threading.Event()
        def far_spawn():
            spawn_started.set()
            return alice.spawnEntity(20_000.25, 220, 20_000.75, entity.COW)
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="i04-generation") as pool:
            started = time.perf_counter()
            spawned = pool.submit(far_spawn)
            assert spawn_started.wait(timeout=10)
            other = bob.players.giveItem(selector.SELF, items.GOLD_INGOT, 1)
            elapsed_other = time.perf_counter() - started
            other_completed_while_spawn_pending = not spawned.done()
            far = spawned.result(timeout=90)
        # Acquiring an observer-only ticket after the production operation is
        # complete allows an independent UUID lookup even if the chunk unloaded.
        far_case = observer.case_id()
        observer.result(far_case, "setup", world["uuid"], "20000,219,20000")
        far_state = observer.result(case, "entityState", str(far.uuid))
        assert far_state["exists"] and far_state["type"] == "minecraft:cow"
        spawns = observer.result(case, "farSpawnEvents")["spawns"]
        initial = next(row for row in spawns if row["uuid"] == str(far.uuid))
        assert (initial["x"], initial["y"], initial["z"]) == (20_000.25, 220, 20_000.75), initial
        assert initial["cancelled"] is False
        marker = "I04-fifo-" + harness.run_id
        alice.postToChat(marker)
        alice.flush()
        receipts = [client.wait_chat(marker) for client in clients]
        observer.result(far_case, "cleanup")
        check("far-unloaded-spawn-other-session-progress-and-public-call-ordering", {
            "before": before, "spawn": far, "observer": far_state, "initialSpawnEvent": initial,
            "otherResult": other, "otherCompletedWhileSpawnPending": other_completed_while_spawn_pending,
            "otherSeconds": elapsed_other, "totalSeconds": time.perf_counter() - started,
            "chatAfterSynchronousSpawnAndFlush": receipts,
            "queuedServerFifoClaimed": False})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin", type=Path, default=ROOT / "plugin/build/libs/minebridge-paper-0.2.0-dev1.jar")
    arguments = parser.parse_args()
    print(json.dumps(run(arguments.plugin), indent=2))
