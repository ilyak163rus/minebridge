"""Native Paper I03 scenarios. No production capture APIs or synthetic events."""

import json
import time
from game_client import GameClient
from observer_client import ObserverClient


def records(batch): return batch["events"]
def ids(batch): return [e["eventId"] for e in records(batch)]
def key(value): return value.get("key") if isinstance(value, dict) else value
def xyz(value): return [value[axis] for axis in ("x", "y", "z")] if isinstance(value, dict) else value


def acceptance(harness, paper, Worker, games, workers, check):
    observer = ObserverClient(paper, harness.artifacts / "observer.json"); case = observer.case_id()
    world = next(w for w in observer.result(case, "worlds")["worlds"] if w["name"] == harness.world_name)
    protocol = observer.result(case, "gameProtocol")

    def setup_player(game, x=128.5, y=210, z=128.5, mode="CREATIVE", invulnerable=True, yaw=0, pitch=0):
        value = observer.result(case, "i03Player", game.name, world["uuid"], x, y, z, yaw, pitch, mode, str(invulnerable).lower())
        tick(2)
        return value

    def tick(count=3):
        start = observer.result(case, "i03State")["tick"]
        return observer.await_value(case, "i03State", (), lambda r: r["tick"] >= start + count, timeout=12 + count / 10)

    def native(event_type, predicate=lambda e: True, after=0, timeout=12):
        value = observer.await_value(case, "i03State", (), lambda r: any(
            e["type"] == event_type and e["sequence"] > after and predicate(e) for e in r["events"]), timeout=timeout)
        return next(e for e in value["events"] if e["type"] == event_type and e["sequence"] > after and predicate(e))

    def marker(): return observer.result(case, "i03State")["sequence"]

    def recent(peer, event_type, predicate=lambda e: True, timeout=12):
        deadline = time.monotonic() + timeout
        while True:
            result = peer.call("recent", type=event_type)
            if any(predicate(e) for e in records(result)): return result
            assert time.monotonic() < deadline, ("Missing history", event_type, result)
            tick(1)

    def block(x, y, z, material): return observer.result(case, "i03Block", world["uuid"], x, y, z, material)
    def item(game, material, amount=1, hand="HAND"): return observer.result(case, "i03Item", game.name, material, amount, hand)
    def cancel(kind, enabled): return observer.result(case, "i03Cancel", kind, str(enabled).lower())

    for name in ("I03Alice", "I03Bob"):
        game = GameClient(harness.game_port, name, protocol); games.append(game); game.wait_ready(); paper.command("op " + name)
    alice_game, bob_game = games
    setup_player(alice_game); setup_player(bob_game, x=144.5)
    for game in games: item(game, "AIR")
    alice, bob = Worker(harness, alice_game.name), Worker(harness, bob_game.name); workers.extend([alice, bob])
    assert alice.context["pid"] != bob.context["pid"]
    assert alice.context["info"]["sessionId"] != bob.context["info"]["sessionId"]
    expected_types = {"chat.message", "block.interact", "block.break", "block.place", "entity.attack", "entity.damage",
                      "player.damage", "player.enter_lava", "player.join", "player.quit", "player.death", "player.respawn",
                      "projectile.shot", "projectile.hit"}
    assert {"events.type." + t for t in expected_types} <= set(alice.context["info"]["capabilities"])
    check("two-real-game-connections-and-two-source-python-processes-all-type-capabilities", {
        "python": [p.context for p in workers], "games": [g.evidence() for g in games], "types": sorted(expected_types)})

    # Real creative destruction/place packets; facade setBlock remains a programmatic edit.
    block(128, 209, 128, "COBBLESTONE"); block(128, 210, 130, "COBBLESTONE")
    region = {"world": world["uuid"], "min": [128, 210, 129], "max": [128, 210, 131]}
    alice.call("subscribe", label="break-filter", type="block.break", players="$self", region=region,
               blocks=["minecraft:cobblestone"], action=True)
    bob.call("subscribe", label="all-breaks", type="block.break")
    alice.call("startRun"); bob.call("startRun")
    before = marker(); alice_game.break_block((128, 210, 130))
    broken = native("block.break", lambda e: e["player"]["uuid"] == alice_game.uuid and e["position"] == [128.0, 210.0, 130.0], after=before)
    assert not broken["cancelled"]
    a_state, b_state = alice.call("waitRecords", label="break-filter", count=1), bob.call("waitRecords", label="all-breaks", count=1)
    action = next(r for r in a_state["records"] if r["label"] == "break-filter")
    assert action["thread"] == "i03-explicit-callback-consumer" and action["readback"] == 4 and action["gift"]["applied"] == 1
    break_event = action["event"]
    assert xyz(break_event["position"]) == [128, 210, 130] and break_event["block"]["key"] == "minecraft:cobblestone"
    assert any(r["event"]["eventId"] == break_event["eventId"] for r in b_state["records"])
    item(alice_game, "COBBLESTONE", 16); block(128, 209, 130, "STONE")
    before = marker(); alice_game.use_block((128, 209, 130), face=1)
    placed = native("block.place", lambda e: e["position"] == [128.0, 210.0, 130.0], after=before)
    placement = recent(alice, "block.place", lambda e: xyz(e["position"]) == [128, 210, 130])
    assert records(placement)[-1]["replacedBlock"]["key"] == "minecraft:air"
    break_before = ids(alice.call("recent", type="block.break")); place_before = ids(placement)
    alice.call("setBlock", position=[128, 210, 130], block="minecraft:air")
    tick()
    assert ids(alice.call("recent", type="block.break")) == break_before
    assert ids(alice.call("recent", type="block.place")) == place_before
    check("native-break-place-snapshots-filtered-callback-sync-rpc-and-programmatic-edit-is-not-player-action", {
        "nativeBreak": broken, "nativePlace": placed, "callback": action, "placement": placement})

    # Region/key intersections are server-side; history remains unfiltered.
    block(129, 210, 130, "COBBLESTONE"); before = marker(); alice_game.break_block((129, 210, 130))
    native("block.break", lambda e: e["position"] == [129.0, 210.0, 130.0], after=before)
    block(128, 210, 130, "DIRT"); before = marker(); alice_game.break_block((128, 210, 130))
    native("block.break", lambda e: e["key"] == "minecraft:dirt", after=before)
    bob.call("waitRecords", label="all-breaks", count=3)
    assert len([r for r in alice.call("state")["records"] if r["label"] == "break-filter"]) == 1
    full_history = recent(alice, "block.break", lambda e: e["block"]["key"] == "minecraft:dirt")
    assert len(records(full_history)) == 3
    # Cancelled result events disappear from history but native attempt audit remains.
    block(128, 210, 130, "COBBLESTONE"); cancel("block.break", True); before = marker()
    alice_game.break_block((128, 210, 130)); attempt = native("block.break", after=before)
    assert attempt["cancelled"]; cancel("block.break", False)
    assert ids(alice.call("recent", type="block.break")) == ids(full_history)
    block(128,210,130,"AIR"); cancel("block.place",True); before=marker(); alice_game.use_block((128,209,130))
    cancelled_place=native("block.place",after=before); assert cancelled_place["cancelled"]
    cancel("block.place",False)
    assert ids(alice.call("recent",type="block.place"))==place_before
    check("region-block-player-filter-intersection-and-cancelled-break-place-exclusion", {"history": full_history, "cancelledNative": attempt,"cancelledPlace":cancelled_place})

    # Real left-click followed by right-click for each hand. No heuristic dedup.
    item(alice_game, "AIR"); item(alice_game, "STICK", hand="OFF_HAND")
    block(128, 210, 130, "STONE"); cancel("block.interact", True)
    before = marker(); alice_game.break_block((128, 210, 130)); alice_game.use_block((128, 210, 130), hand=0); alice_game.use_block((128, 210, 130), hand=1)
    native("block.interact", lambda e: e["hand"] == "OFF_HAND", after=before)
    interactions = recent(alice, "block.interact", lambda e: e["hand"] == "OFF_HAND")
    assert {e["action"] for e in records(interactions)} >= {"LEFT_CLICK_BLOCK", "RIGHT_CLICK_BLOCK"}
    assert {e["hand"] for e in records(interactions)} >= {"HAND", "OFF_HAND"}
    assert any(e["cancelled"] for e in records(interactions))
    alias = alice.call("poll", type="block.interact", alias="pollBlockHits")
    assert ids(alias) == ids(interactions) and alice.call("poll", type="block.interact")["events"] == []
    cancel("block.interact", False)
    check("real-block-left-right-and-both-hands-cancelled-attempts-alias-cursor", interactions)

    # No damage is inferred from the PrePlayerAttack event.
    block(128, 210, 130, "AIR")
    target = observer.result(case, "i03Target", world["uuid"], 128.5, 210, 130.5, "ARMOR_STAND", "true")
    before = marker(); cancel("entity.attack", True); alice_game.attack(target["entityId"])
    attack_native = native("entity.attack", lambda e: e["target"]["uuid"] == target["uuid"], after=before)
    attack_history = recent(alice, "entity.attack", lambda e: e["target"]["uuid"] == target["uuid"])
    assert records(attack_history)[-1]["cancelled"] and attack_native["cancelled"]
    assert not any(e["victim"]["uuid"] == target["uuid"] for e in records(alice.call("recent", type="entity.damage")))
    cancel("entity.attack", False); observer.result(case, "i03Remove", target["uuid"])
    # Actual native damage from Player.damage; projection shares physical identity.
    setup_player(bob_game, x=144.5, mode="SURVIVAL", invulnerable=False)
    before = marker(); observer.result(case, "i03Damage", bob_game.name, 3, alice_game.name)
    damage_native = native("entity.damage", lambda e: e["victim"]["uuid"] == bob_game.uuid and not e["cancelled"], after=before)
    damage = recent(alice, "entity.damage", lambda e: e["victim"]["uuid"] == bob_game.uuid)
    projected = recent(alice, "player.damage", lambda e: e["victim"]["uuid"] == bob_game.uuid)
    canonical = next(e for e in reversed(records(damage)) if e["victim"]["uuid"] == bob_game.uuid)
    projection = next(e for e in reversed(records(projected)) if e["victim"]["uuid"] == bob_game.uuid)
    assert canonical["eventId"] == projection["eventId"] and canonical["sequence"] == projection["sequence"]
    assert projection["player"]["uuid"] == bob_game.uuid
    assert canonical["directSource"]["uuid"] == canonical["causingEntity"]["uuid"] == alice_game.uuid
    unchanged = ids(alice.call("recent", type="entity.damage")); cancel("entity.damage", True); before = marker()
    observer.result(case, "i03Damage", bob_game.name, 2, alice_game.name)
    assert native("entity.damage", after=before)["cancelled"]; cancel("entity.damage", False)
    assert ids(alice.call("recent", type="entity.damage")) == unchanged
    check("native-attack-without-damage-and-typed-player-damage-projection", {"attack": attack_history, "native": damage_native, "canonical": canonical, "projection": projection})

    # Projectiles originate from actual item-use packets, wall collision uses engine physics.
    setup_player(alice_game); setup_player(bob_game, x=144.5)
    observer.result(case, "i03Wall", world["uuid"], 136)
    shot_results = []
    for material, expected, charge in (("BOW", "minecraft:arrow", True), ("SNOWBALL", "minecraft:snowball", False), ("TRIDENT", "minecraft:trident", True), ("CROSSBOW", "minecraft:arrow", False)):
        print(json.dumps({"phase": "native-projectile", "material": material, "expected": expected, "charge": charge}), flush=True)
        item(alice_game, material, 1, "MULTISHOT" if material == "CROSSBOW" else "HAND")
        before = marker(); old_ids = {e["projectile"]["uuid"] for e in records(alice.call("recent", type="projectile.shot"))}
        alice_game.use_item()
        if charge:
            observer.await_value(case, "i03PlayerState", (alice_game.name,), lambda r: r["usingTicks"] >= 20)
            alice_game.release_item()
        native_shot = native("projectile.shot", lambda e: e["projectile"]["key"] == expected and not e["cancelled"], after=before)
        native_hit = native("projectile.hit", lambda e: e["projectile"]["uuid"] == native_shot["projectile"]["uuid"], after=before)
        shots = recent(alice, "projectile.shot", lambda e: e["projectile"]["uuid"] == native_shot["projectile"]["uuid"])
        new = [e for e in records(shots) if e["projectile"]["uuid"] not in old_ids]
        if material == "CROSSBOW":
            deadline = time.monotonic() + 10
            while len(new) < 3:
                assert time.monotonic() < deadline
                tick(2); shots = alice.call("recent", type="projectile.shot")
                new = [e for e in records(shots) if e["projectile"]["uuid"] not in old_ids]
            assert len(new) == len({e["projectile"]["uuid"] for e in new}) == 3
        else: assert len(new) == 1, (material, new)
        assert all(e["shooter"]["uuid"] == alice_game.uuid for e in new)
        if material in ("BOW", "CROSSBOW"):
            assert all(key(e["weapon"]) == "minecraft:" + material.lower() and e["force"] is not None for e in new), new
        else: assert all(e["weapon"] is None and e["force"] is None for e in new), new
        hits = recent(alice, "projectile.hit", lambda e: e["projectile"]["uuid"] == native_shot["projectile"]["uuid"])
        hit = next(e for e in records(hits) if e["projectile"]["uuid"] == native_shot["projectile"]["uuid"])
        assert hit["hitBlock"] is not None and hit["hitEntity"] is None
        shot_results.append({"item": material, "nativeShot": native_shot, "nativeHit": native_hit, "shots": new, "hit": hit})
        tick(3)
    check("native-bow-snowball-trident-crossbow-multishot-one-fact-per-projectile-uuid", shot_results)

    # Entity contact is distinct from guaranteed damage; cancellation status survives.
    target = observer.result(case, "i03Target", world["uuid"], 128.5, 210, 131.5, "ARMOR_STAND", "true")
    item(alice_game, "SNOWBALL", 8); cancel("projectile.hit", True); before = marker(); alice_game.use_item()
    hit_native = native("projectile.hit", lambda e: e["hitEntity"] is not None and e["hitEntity"]["uuid"] == target["uuid"], after=before)
    contact = recent(alice, "projectile.hit", lambda e: e["projectile"]["uuid"] == hit_native["projectile"]["uuid"])
    assert next(e for e in records(contact) if e["projectile"]["uuid"] == hit_native["projectile"]["uuid"])["cancelled"]
    cancel("projectile.hit", False); observer.result(case, "i03Remove", target["uuid"])
    # Launch cancellation is not a successful shot.
    before_ids = ids(alice.call("recent", type="projectile.shot")); cancel("projectile.shot", True); before = marker(); tick(5); alice_game.use_item()
    assert native("projectile.shot", after=before)["cancelled"]; cancel("projectile.shot", False)
    assert ids(alice.call("recent", type="projectile.shot")) == before_ids
    check("native-entity-projectile-contact-cancellation-and-cancelled-launch-exclusion", {"contact": contact, "native": hit_native})

    # Player-default subscription excludes dispenser actor; players=None includes it.
    alice.call("subscribe", label="all-shot-actors", type="projectile.shot", players=None)
    bob.call("subscribe", label="only-player-shots", type="projectile.shot")
    source = observer.result(case, "i03SourceShot", world["uuid"])
    native("projectile.shot", lambda e: e["projectile"]["uuid"] == source["uuid"])
    all_actors = alice.call("waitRecords", label="all-shot-actors", count=1)
    shot = next(r["event"] for r in all_actors["records"] if r["label"] == "all-shot-actors")
    assert shot["projectile"]["uuid"] == source["uuid"] and shot["shooter"] is None and shot["sourceBlock"] is not None
    tick(); assert not any(r["label"] == "only-player-shots" for r in bob.call("state")["records"])
    check("dispenser-source-is-null-player-with-explicit-source-block-and-player-filter", shot)

    # Dynamic ALL_PLAYERS includes a new connection, quit snapshots survive after departure.
    for event_type in ("player.join", "player.quit", "player.death", "player.respawn"):
        alice.call("subscribe", label=event_type, type=event_type)
    newcomer = GameClient(harness.game_port, "I03Guest", protocol); games.append(newcomer); newcomer.wait_ready()
    joined = alice.call("waitRecords", label="player.join", count=1)
    assert any(r["label"] == "player.join" and r["event"]["player"]["uuid"] == newcomer.uuid for r in joined["records"])
    newcomer.close(); quit_state = alice.call("waitRecords", label="player.quit", count=1)
    assert any(r["label"] == "player.quit" and r["event"]["player"]["uuid"] == newcomer.uuid for r in quit_state["records"])
    observer.result(case, "i03RespawnAt", bob_game.name, world["uuid"], 144.5, 210, 128.5)
    observer.result(case, "i03Death", bob_game.name); alice.call("waitRecords", label="player.death", count=1)
    bob_game.respawn(); respawned = alice.call("waitRecords", label="player.respawn", count=1)
    respawn = next(r["event"] for r in respawned["records"] if r["label"] == "player.respawn")
    native_respawn=native("player.respawn",lambda e:e["player"]["uuid"]==bob_game.uuid)
    assert respawn["reason"] == "DEATH" and xyz(respawn["respawnLocation"]["position"]) == native_respawn["position"]
    check("dynamic-join-quit-death-real-respawn-packet-and-reason-snapshots", {"join": joined, "quit": quit_state, "respawn": respawn})

    # Lava contact is sampled independently from damage, including stationary fluid entry.
    setup_player(bob_game, x=144.5); setup_player(alice_game, x=160.5)
    alice.call("subscribe", label="lava", type="player.enter_lava", players="$self")
    def lava_history(): return alice.call("recent", type="player.enter_lava")
    def lava_count(): return len([e for e in records(lava_history()) if e["player"]["uuid"] == alice_game.uuid])
    def contact(expected):
        return observer.await_value(case, "i03PlayerState", (alice_game.name,), lambda r: r["lava"] is expected)
    def next_lava(old):
        value = recent(alice, "player.enter_lava", lambda e: e["player"]["uuid"] == alice_game.uuid and e["sequence"] > old)
        return max(e["sequence"] for e in records(value) if e["player"]["uuid"] == alice_game.uuid)
    # Both pools exist before teleport; transition is confirmed by Paper isInLava, no feet-block inference.
    for x in (162, 164): block(x, 209, 128, "STONE"); block(x, 210, 128, "LAVA")
    tick(); assert lava_count() == 0
    setup_player(alice_game, x=162.5, mode="CREATIVE"); contact(True); seq = next_lava(0); first_count = lava_count()
    tick(12); assert lava_count() == first_count
    # New subscription while already immersed must not fabricate a new transition.
    bob.call("subscribe", label="already-in-lava", type="player.enter_lava", players=alice_game.name)
    tick(4); assert lava_count() == first_count
    assert not any(r["label"] == "already-in-lava" for r in bob.call("state")["records"])
    setup_player(alice_game, x=160.5); contact(False)
    setup_player(alice_game, x=162.5, mode="SURVIVAL", invulnerable=False); contact(True); seq = next_lava(seq)
    observer.result(case, "i03Resistance", alice_game.name, "true")
    setup_player(alice_game, x=160.5, mode="SURVIVAL", invulnerable=False); contact(False)
    setup_player(alice_game, x=162.5, mode="SURVIVAL", invulnerable=False); contact(True); seq = next_lava(seq)
    # Lava-to-lava teleport is a new confirmed contact even though sampled bool remains true.
    setup_player(alice_game, x=164.5, mode="SURVIVAL", invulnerable=False); contact(True); seq = next_lava(seq)
    check("lava-creative-survival-fire-resistance-one-per-contact-new-subscription-and-teleport", lava_history())

    setup_player(alice_game, x=174.5, mode="CREATIVE"); contact(False)
    for x in range(172, 177):
        for z in range(127, 130): block(x, 209, z, "STONE")
    for x,y,z in ((172,210,128),(173,210,127),(173,210,129)): block(x,y,z,"STONE")
    for x,y,z in ((173,210,128),(174,210,128),(175,210,128)): block(x,y,z,"AIR")
    tick(); before = marker(); block(173,210,128,"LAVA")
    flow = native("lava.flow", lambda e: e["to"] == [174.0, 210.0, 128.0], after=before, timeout=15)
    contact(True); seq = next_lava(seq)
    stationary = observer.result(case, "i03PlayerState", alice_game.name)
    assert stationary["position"] == [174.5, 210.0, 128.5]
    observer.result(case,"i03RespawnAt",alice_game.name,world["uuid"],162.5,210,128.5)
    observer.result(case,"i03Death",alice_game.name); alice_game.respawn()
    native("player.respawn",lambda e:e["player"]["uuid"]==alice_game.uuid)
    contact(True); seq = next_lava(seq)
    setup_player(alice_game,x=160.5); observer.result(case,"i03Resistance",alice_game.name,"false")
    check("stationary-player-fluid-flow-and-respawn-into-lava-create-contact", {"flow": flow, "stationary": stationary, "history": lava_history()})

    # Independent per-type cursors, independent processes, projection does not consume canonical.
    pull_damage = alice.call("poll", type="entity.damage", alias="pollDamageEvents")
    pull_player = alice.call("poll", type="player.damage")
    assert canonical["eventId"] in ids(pull_damage) and canonical["eventId"] in ids(pull_player)
    shot_pull = alice.call("poll", type="projectile.shot", alias="pollProjectileShots")
    bob_shots = bob.call("poll", type="projectile.shot")
    assert ids(shot_pull) == ids(bob_shots)
    assert len(records(shot_pull)) >= 7
    # Genuine native chat remains independent after generalizing the journal.
    alice_game.send_chat("i03-chat-with-projectile-history")
    chat = recent(alice, "chat.message", lambda e: e["message"] == "i03-chat-with-projectile-history")
    chat_pull = alice.call("poll", type="chat.message", alias="pollChatPosts")
    assert ids(chat_pull) == ids(chat)
    assert any(e["message"] == "i03-chat-with-projectile-history" for e in records(bob.call("poll", type="chat.message")))
    assert alice.call("poll", type="projectile.shot")["events"] == []
    assert ids(alice.call("recent", type="projectile.shot")) == ids(shot_pull)
    alice.call("clear", all=True)
    assert alice.call("poll", type="block.break")["events"] == []
    assert len(records(bob.call("poll", type="block.break"))) == 3
    assert ids(alice.call("recent", type="projectile.shot")) == ids(shot_pull)
    check("typed-cursors-projection-aliases-two-processes-and-clear-all-independence", {
        "damage": pull_damage, "playerDamage": pull_player, "shots": shot_pull, "nativeChat": chat_pull})

    for peer in workers: peer.close()
    final = observer.result(case, "i03State")
    assert all(e["primaryThread"] for e in final["events"])
    for game in games:
        assert not game.errors, game.evidence(); game.close()
    check("native-oracle-primary-thread-clean-close-and-no-python-thread-leaks", {"nativeEvents": len(final["events"]), "sequence": final["sequence"]})
