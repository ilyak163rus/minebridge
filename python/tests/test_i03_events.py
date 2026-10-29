"""I03 typed snapshots, schema boundaries and independent per-type history over TCP."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import unittest
from uuid import UUID, uuid4

from minebridge import Minecraft, block, damageCause, errors, events
from minebridge._event_models import event_from_wire
from minebridge._protocol import CodecError, EVENT_TYPES, decode_event, decode_request, encode_frame
from minebridge.models import (
    Event, EventPosition, Region, BlockBreakEvent, BlockPlaceEvent, BlockInteractEvent,
    EntityAttackEvent, EntityDamageEvent, PlayerDamageEvent, LavaEnterEvent,
    PlayerJoinEvent, PlayerQuitEvent, PlayerDeathEvent, PlayerRespawnEvent,
    ProjectileShotEvent, ProjectileHitEvent, PlayerRef, LivingEntityRef,
)
from test_events_v03 import WORLD, PLAYER, EPOCH, ack, batch, cursor, event_hello, record, server_handler
from test_transport import peer


OTHER = "44444444-4444-4444-8444-444444444444"
PROJECTILE = "55555555-5555-4555-8555-555555555555"


def player():
    return {"uuid": PLAYER, "entityId": 7, "key": "minecraft:player", "living": True, "name": "Alice"}


def entity(key="minecraft:zombie", *, living=True):
    return {"uuid": OTHER, "entityId": 9, "key": key, "living": living, "name": None}


def projectile():
    return {"uuid": PROJECTILE, "entityId": 11, "key": "minecraft:arrow", "living": False, "name": None}


def data_for(kind):
    solid = {"key": "minecraft:stone", "states": {}}
    if kind == "chat.message": return record()["data"]
    if kind == "block.break": return {"player": player(), "position": [1, 80, -1], "block": solid, "cancelled": False}
    if kind == "block.place": return dict(data_for("block.break"), replacedBlock={"key": "minecraft:air", "states": {}})
    if kind == "block.interact":
        return dict(data_for("block.break"), face="UP", action="RIGHT_CLICK_BLOCK", hand="OFF_HAND",
                    item="minecraft:stick", useInteractedBlock="DENY", useItemInHand="DEFAULT", cancelled=True)
    if kind == "entity.attack": return {"player": player(), "target": entity(), "willAttack": False, "cancelled": True}
    if kind in ("entity.damage", "player.damage"):
        return {"victim": player(), "directSource": projectile(), "causingEntity": entity(), "cause": "PROJECTILE",
                "rawDamage": 4.5, "finalDamage": 2.25, "cancelled": False}
    if kind in ("player.enter_lava", "player.death"): return {"player": player(), "position": [1.25, 80.5, -.75]}
    if kind in ("player.join", "player.quit"): return {"player": player()}
    if kind == "player.respawn":
        return {"player": player(), "reason": "END_PORTAL", "respawnLocation": {
            "world": {"uuid": WORLD, "name": "world", "key": "minecraft:overworld"},
            "position": [1.5, 80.0, 2.5], "yaw": 25.5, "pitch": -7.0}}
    if kind == "projectile.shot":
        return {"projectile": projectile(), "shooter": player(), "sourceBlock": None, "position": [0.5, 80.5, .5],
                "velocity": [.1, -.2, .3], "weapon": "minecraft:crossbow", "hand": "HAND", "force": 1.0, "cancelled": False}
    if kind == "projectile.hit":
        return {"projectile": projectile(), "shooter": None, "sourceBlock": {"position": [0, 80, 0], "block": solid},
                "position": [1.25, 81.5, 2.25], "hitEntity": None,
                "hitBlock": {"position": [1, 81, 2], "block": solid}, "hitFace": "NORTH", "cancelled": True}
    raise AssertionError(kind)


def typed_record(kind, sequence=11, *, identity=None):
    value = record(sequence)
    value.update(eventType=kind, data=data_for(kind))
    if identity: value["eventId"] = identity
    return value


def typed_hello():
    value = event_hello()
    value["capabilities"] += ["events.type." + kind for kind in EVENT_TYPES]
    return value


def decode_snapshot(value):
    frame = encode_frame({"jsonrpc": "2.0", "method": "events.event", "params": {
        "subscriptionId": OTHER, "deliverySequence": 1, "event": value}})
    notification = decode_event(frame[:-1])
    return event_from_wire(notification[1]["event"])


class I03EventTests(unittest.TestCase):
    def connect(self, server):
        mc = Minecraft.create("127.0.0.1", server.port, timeout=1, writeMode="sync")
        self.addCleanup(mc.close)
        return mc

    def test_every_catalog_entry_decodes_to_concrete_immutable_model(self):
        expected = {
            "block.break": BlockBreakEvent, "block.place": BlockPlaceEvent, "block.interact": BlockInteractEvent,
            "entity.attack": EntityAttackEvent, "entity.damage": EntityDamageEvent, "player.damage": PlayerDamageEvent,
            "player.enter_lava": LavaEnterEvent, "player.join": PlayerJoinEvent, "player.quit": PlayerQuitEvent,
            "player.death": PlayerDeathEvent, "player.respawn": PlayerRespawnEvent,
            "projectile.shot": ProjectileShotEvent, "projectile.hit": ProjectileHitEvent,
        }
        for kind, cls in expected.items():
            with self.subTest(kind=kind):
                event = decode_snapshot(typed_record(kind))
                self.assertIs(type(event), cls)
                self.assertEqual(event.eventType.key, kind)
                with self.assertRaises(FrozenInstanceError): event.serverTick = 0
        self.assertIs(events.BLOCK_HIT, events.BLOCK_INTERACT)
        self.assertEqual(len(EVENT_TYPES), 14)

    def test_nested_snapshots_keep_item_block_entity_and_position_types(self):
        event = decode_snapshot(typed_record("block.interact"))
        self.assertIsInstance(event.player, PlayerRef)
        self.assertEqual(tuple(event.position), (1, 80, -1))
        self.assertIs(type(event.position.x), int)
        self.assertEqual(event.item.key, "minecraft:stick")
        with self.assertRaises(TypeError): event.block.states["axis"] = "x"
        attack = decode_snapshot(typed_record("entity.attack"))
        self.assertIsInstance(attack.target, LivingEntityRef)
        self.assertFalse(attack.willAttack)
        self.assertTrue(attack.cancelled)
        hit = decode_snapshot(typed_record("projectile.hit"))
        self.assertIsNone(hit.shooter)
        self.assertEqual(hit.sourceBlock.position.y, 80)
        self.assertEqual(hit.hitBlock.block.key, "minecraft:stone")
        self.assertEqual(hit.hitFace, "NORTH")

    def test_damage_projection_preserves_fact_and_exposes_same_player(self):
        identity = str(uuid4())
        canonical = decode_snapshot(typed_record("entity.damage", identity=identity))
        projected = decode_snapshot(typed_record("player.damage", identity=identity))
        self.assertEqual(canonical.eventId, projected.eventId)
        self.assertEqual(canonical.sequence, projected.sequence)
        self.assertEqual(canonical.victim, projected.player)
        self.assertIs(projected.player, projected.victim)
        self.assertEqual(projected.cause, damageCause.PROJECTILE)
        self.assertEqual(projected.directSource.uuid, UUID(PROJECTILE))
        self.assertEqual(projected.causingEntity.uuid, UUID(OTHER))
        self.assertEqual((projected.rawDamage, projected.finalDamage), (4.5, 2.25))

    def test_respawn_has_its_observed_location_and_forward_native_reason(self):
        row = typed_record("player.respawn")
        row["data"]["reason"] = "FUTURE_NATIVE_REASON"
        event = decode_snapshot(row)
        self.assertEqual(event.respawnLocation.world.uuid, UUID(WORLD))
        self.assertEqual(tuple(event.respawnLocation.position), (1.5, 80.0, 2.5))
        self.assertEqual(event.respawnLocation.pitch, -7)
        self.assertEqual(event.reason, "FUTURE_NATIVE_REASON")

    def test_schema_rejects_invalid_projection_entity_and_resultive_cancellation(self):
        invalid = []
        value = typed_record("player.damage"); value["data"]["victim"] = entity(); invalid.append(value)
        value = typed_record("block.break"); value["data"]["cancelled"] = True; invalid.append(value)
        value = typed_record("entity.damage"); value["data"]["finalDamage"] = -1; invalid.append(value)
        value = typed_record("player.join"); value["data"]["player"]["living"] = False; invalid.append(value)
        value = typed_record("projectile.shot"); value["data"]["force"] = True; invalid.append(value)
        value = typed_record("block.interact"); value["data"]["position"][0] = .5; invalid.append(value)
        value = typed_record("projectile.hit"); value["data"]["hitBlock"]["block"]["key"] = "invalid"; invalid.append(value)
        for value in invalid:
            with self.subTest(value=value["eventType"]):
                with self.assertRaises(CodecError): decode_snapshot(value)

    def test_unknown_payload_fields_are_not_silently_dropped(self):
        for kind in EVENT_TYPES:
            row = typed_record(kind)
            row["data"]["unexpected"] = 1
            with self.subTest(kind=kind):
                with self.assertRaises(CodecError): decode_snapshot(row)

    def test_region_normalizes_inclusive_integer_corners_and_is_immutable(self):
        region = Region(WORLD, (10, 80, -10), (-10, 60, 10))
        self.assertEqual(region.min, (-10, 60, -10))
        self.assertEqual(region.max, (10, 80, 10))
        with self.assertRaises(FrozenInstanceError): region.world = UUID(OTHER)
        for corner in [(0, False, 0), (0, .5, 0), (0, 1), (0, 0, 2147483648)]:
            with self.subTest(corner=corner):
                with self.assertRaises((TypeError, ValueError)): Region(WORLD, corner, (0, 0, 0))

    def test_new_types_fail_locally_on_i02_server_but_chat_still_works(self):
        requests = []
        with peer(server_handler(requests=requests)) as server:
            mc = self.connect(server)
            for call in (lambda: mc.events.subscribe(events.BLOCK_BREAK), mc.events.pollBlockHits,
                         lambda: mc.events.getRecent(events.PLAYER_DAMAGE),
                         lambda: mc.events.clearPending(events.PROJECTILE_HIT)):
                with self.assertRaises(errors.UnsupportedFeatureError): call()
            self.assertEqual(len(requests), 1)
            sub = mc.events.subscribe(events.CHAT_MESSAGE)
            self.assertEqual(set(requests[-1]["params"]), {"subscriptionId", "eventType", "world", "executor", "players"})
            sub.unsubscribe()

    def test_subscribe_filters_send_normalized_keys_and_optional_wire_only(self):
        requests = []
        def action(connection, request):
            if request["method"] == "events.subscribe":
                connection.sendall(ack(request, {"subscriptionId": request["params"]["subscriptionId"],
                    "eventType": request["params"]["eventType"], "world": WORLD}))
                return True
        with peer(server_handler(action, metadata=typed_hello(), requests=requests)) as server:
            mc = self.connect(server)
            region = Region(WORLD, (5, 90, 5), (0, 60, 0))
            sub = mc.events.subscribe(events.BLOCK_BREAK, players=None, region=region,
                                      blocks=[block.STONE, block.STONE.withStates(axis="x"), "minecraft:dirt"])
            params = requests[-1]["params"]
            self.assertEqual(params["players"], None)
            self.assertEqual(params["region"], {"world": WORLD, "min": [0, 60, 0], "max": [5, 90, 5]})
            self.assertEqual(params["blocks"], ["minecraft:stone", "minecraft:dirt"])
            sub.unsubscribe()
            before = len(requests)
            for kind, kwargs in [(events.PLAYER_JOIN, {"region": region}), (events.ENTITY_DAMAGE, {"blocks": [block.STONE]}),
                                 (events.BLOCK_PLACE, {"region": Region(OTHER, (0, 0, 0), (5, 5, 5))}),
                                 (events.BLOCK_BREAK, {"region": (0, 0, 0)})]:
                with self.assertRaises((ValueError, TypeError)): mc.events.subscribe(kind, **kwargs)
            self.assertEqual(len(requests), before)

    def test_region_wire_rejects_null_reversed_world_and_nonblock_blocks(self):
        params = {"subscriptionId": OTHER, "eventType": "block.break", "world": "world", "executor": None, "players": "@a"}
        bad = [dict(params, region=None), dict(params, region={"world": WORLD, "min": [5, 0, 0], "max": [0, 5, 5]}),
               dict(params, region={"world": "invalid", "min": [0, 0, 0], "max": [5, 5, 5]}),
               dict(params, eventType="entity.attack", blocks=["minecraft:stone"])]
        for value in bad:
            frame = encode_frame({"jsonrpc": "2.0", "id": 1, "method": "events.subscribe", "params": value})
            with self.assertRaises(CodecError): decode_request(frame[:-1])

    def test_history_types_projection_and_alias_have_independent_cursors(self):
        requests, counts = [], {}
        identity = str(uuid4())
        rows = {"block.interact": typed_record("block.interact", 11), "projectile.shot": typed_record("projectile.shot", 12),
                "entity.damage": typed_record("entity.damage", 13, identity=identity),
                "player.damage": typed_record("player.damage", 13, identity=identity)}
        def action(connection, request):
            if request["method"] == "events.pollEvents":
                key = request["params"]["eventType"]
                counts[key] = counts.get(key, 0) + 1
                self.assertEqual(request["params"]["cursor"]["sequence"], 10 if counts[key] == 1 else 13)
                connection.sendall(ack(request, batch([rows[key]] if counts[key] == 1 else [], next_sequence=13)))
                return True
        with peer(server_handler(action, metadata=typed_hello(), requests=requests)) as server:
            mc = self.connect(server)
            hit = mc.events.pollBlockHits()
            self.assertIsInstance(hit[0], BlockInteractEvent)
            self.assertEqual(len(mc.events.pollEvents(events.BLOCK_HIT)), 0)
            shot = mc.events.pollProjectileShots()
            self.assertEqual(shot[0].projectile.uuid, UUID(PROJECTILE))
            damage = mc.events.pollDamageEvents()
            player_damage = mc.events.pollEvents(events.PLAYER_DAMAGE)
            self.assertEqual(damage[0].eventId, player_damage[0].eventId)
            self.assertIsInstance(player_damage[0], PlayerDamageEvent)
            self.assertEqual(len(mc.events.pollEvents(events.ENTITY_DAMAGE)), 0)

    def test_clear_all_advances_unread_types_but_type_clear_is_independent(self):
        requests = []
        def action(connection, request):
            if request["method"] == "events.pollEvents":
                connection.sendall(ack(request, batch(next_sequence=20)))
                return True
        with peer(server_handler(action, metadata=typed_hello(), requests=requests)) as server:
            mc = self.connect(server)
            mc.events.clearPending(events.CHAT_MESSAGE)
            mc.events.pollProjectileShots()
            self.assertEqual(requests[-1]["params"]["cursor"]["sequence"], 10)
            mc.events.clearAll()
            mc.events.pollEvents(events.PLAYER_ENTER_LAVA)
            self.assertEqual(requests[-1]["params"]["cursor"]["sequence"], 20)

    def test_live_subscriptions_deliver_concrete_types_and_sync_rpc_remains_usable(self):
        def action(connection, request):
            if request["method"] == "events.subscribe":
                key, identity = request["params"]["eventType"], request["params"]["subscriptionId"]
                frame = encode_frame({"jsonrpc": "2.0", "method": "events.event", "params": {
                    "subscriptionId": identity, "deliverySequence": 1, "event": typed_record(key)}})
                connection.sendall(ack(request, {"subscriptionId": identity, "eventType": key, "world": WORLD}) + frame)
                return True
        with peer(server_handler(action, metadata=typed_hello())) as server:
            mc = self.connect(server)
            sub = mc.events.subscribe(events.ENTITY_ATTACK)
            event = mc.events.poll(timeout=1)
            self.assertIsInstance(event, EntityAttackEvent)
            self.assertEqual(event.subscriptionId, sub.id)
            self.assertFalse(event.willAttack)
            mc.setBlock(0, 80, 0, block.STONE)
            sub.unsubscribe()

    def test_damage_catalog_is_pinned_static_and_unknown_future_cause_is_preserved(self):
        snapshot = json.loads((Path(__file__).resolve().parents[2] / "catalogs/paper-26.2-build133-damage-causes.json").read_text())
        self.assertEqual([value.value for value in damageCause.DamageCause], snapshot["values"])
        self.assertEqual(len(damageCause.DamageCause), 33)
        self.assertEqual(damageCause.LAVA, "LAVA")
        row = typed_record("entity.damage"); row["data"]["cause"] = "FUTURE_CAUSE"
        self.assertEqual(decode_snapshot(row).cause, "FUTURE_CAUSE")


if __name__ == "__main__": unittest.main()
