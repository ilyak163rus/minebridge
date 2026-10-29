"""I04 inventory acceptance using independent native Paper inventory reads."""

from game_client import GameClient
from observer_client import ObserverClient


def material(item):
    if item is None: return None
    value = item["key"]
    return value["key"] if isinstance(value, dict) else value


def at(snapshot, slot): return next(row["item"] for row in snapshot["slots"] if row["slot"] == slot)
def contents(result): return {row["slot"]: row["item"] for row in result["entries"]}


def acceptance(harness, paper, Worker, games, workers, check):
    observer = ObserverClient(paper, harness.artifacts / "observer.json"); case = observer.case_id()
    world = next(row for row in observer.result(case, "worlds")["worlds"] if row["name"] == harness.world_name)
    protocol = observer.result(case, "gameProtocol")
    for index, name in enumerate(("I04Alice", "I04Bob")):
        game = GameClient(harness.game_port, name, protocol); games.append(game); game.wait_ready()
        paper.command("op " + name)
        observer.result(case, "playerPlace", name, world["uuid"], 128 + 32 * index, 210, 128)
        observer.result(case, "i04EmptyPlayer", name)
    alice_game, bob_game = games
    alice, bob = Worker(harness, alice_game.name), Worker(harness, bob_game.name); workers.extend((alice, bob))
    assert alice.context["pid"] != bob.context["pid"]
    assert alice.context["info"]["sessionId"] != bob.context["info"]["sessionId"]
    caps = {"inventories.ofBlock", "inventories.ofPlayer", "inventories.getItem", "inventories.getContents",
            "inventories.setItem", "inventories.clear", "players.setItem"}
    assert caps <= set(alice.context["info"]["capabilities"])
    a_ref, b_ref = alice.call("openPlayer", label="self"), bob.call("openPlayer", label="self")
    assert a_ref["player"] == alice_game.uuid and b_ref["player"] == bob_game.uuid
    assert a_ref["size"] == b_ref["size"] == 41
    assert a_ref["slots"] == list(range(36)) + ["head", "chest", "legs", "feet", "off_hand"]
    assert alice.call("openPlayer", label="derived", context=bob_game.name)["player"] == bob_game.uuid
    alice.call("openPlayer", label="many", target="@a", error="InvalidTargetError")
    check("two-native-players-two-source-processes-pinned-player-refs-and-public-slot-metadata", {
        "alice": alice.context, "bob": bob.context, "playerRefs": [a_ref, b_ref]})

    assert alice.call("getItem", label="self", slot=0) is None
    first = alice.call("setItem", label="self", slot=0, item="minecraft:diamond", amount=16)
    assert first["applied"] and first["previous"] is None and first["current"]["amount"] == 16
    second = alice.call("setItem", label="self", slot=0, item="minecraft:emerald", amount=3)
    assert material(second["previous"]) == "minecraft:diamond" and second["previous"]["amount"] == 16
    assert material(second["current"]) == "minecraft:emerald" and second["current"]["amount"] == 3
    bob.call("setItem", label="self", slot=0, item="minecraft:iron_ingot", amount=7)
    a_native, b_native = observer.result(case, "i04Player", alice_game.name), observer.result(case, "i04Player", bob_game.name)
    assert material(at(a_native, 0)) == "minecraft:emerald" and at(a_native, 0)["amount"] == 3
    assert material(at(b_native, 0)) == "minecraft:iron_ingot" and at(b_native, 0)["amount"] == 7
    empty = alice.call("contents", label="self")
    assert len(empty["entries"]) == 41 and list(contents(empty)) == a_ref["slots"]
    assert contents(empty)[1] is None
    check("exact-replacement-previous-current-empty-slots-and-independent-player-inventories", {"first": first, "replacement": second, "native": [a_native, b_native]})

    before = at(a_native, 0)["sha256"]
    alice.call("setItem", label="self", slot=0, item="minecraft:iron_sword", amount=64, error="InvalidItemAmountError")
    alice.call("setItem", label="self", slot=0, item="minecraft:diamond", amount=0, error=("ValueError", "InvalidItemAmountError"))
    alice.call("setItem", label="self", slot=36, item="minecraft:diamond", amount=1, error=("ValueError", "InvalidSlotError"))
    alice.call("getItem", label="self", slot=True, error=("TypeError", "InvalidSlotError"))
    assert at(observer.result(case, "i04Player", alice_game.name), 0)["sha256"] == before
    alice.call("setItem", label="self", slot="head", item="minecraft:diamond_helmet", amount=1)
    alice.call("setItem", label="self", slot="off_hand", item="minecraft:shield", amount=1)
    alice.call("setItem", label="self", slot="head", item="minecraft:diamond", amount=2, error="InvalidItemAmountError")
    equipment = observer.result(case, "i04Player", alice_game.name)
    assert material(at(equipment, "head")) == "minecraft:diamond_helmet" and material(at(equipment, "off_hand")) == "minecraft:shield"
    hidden = observer.result(case, "i04Hidden", alice_game.name)
    native_before_clear = observer.result(case, "i04Player", alice_game.name)
    cleared = alice.call("clear", label="self")
    assert cleared["applied"] and cleared["slots"] == a_ref["slots"]
    native_after_clear = observer.result(case, "i04Player", alice_game.name)
    assert all(row["item"] is None for row in native_after_clear["slots"])
    assert native_after_clear["hidden"] == native_before_clear["hidden"]
    assert at(observer.result(case, "i04Player", bob_game.name), 0)["amount"] == 7
    check("stack-limits-invalid-slots-zero-no-mutation-equipment-and-public-only-clear", {"equipment": equipment, "hiddenSetup": hidden, "clear": cleared, "after": native_after_clear})

    # Source plain supported fields remain distinct from lossy views.
    named = alice.call("setItem", label="self", slot=2, item="minecraft:diamond", amount=4, name="Course prize", lore=["One", "Two"])
    assert named["current"]["name"] == "Course prize" and named["current"]["lore"] == ["One", "Two"]
    assert not named["current"]["hasAdditionalData"] and not named["current"]["truncated"]
    alice.call("copyView", label="self", source=2, slot=3, error="TypeError")
    assert alice.call("getItem", label="self", slot=3) is None
    check("supported-item-text-and-read-view-is-not-lossless-setter-input", named)

    # Buffered block creation followed by open/read is a synchronous barrier.
    for peer, label, position in ((alice, "own", [200, 210, 128]), (bob, "own", [204, 210, 128])):
        peer.call("setBlock", position=position, block="minecraft:chest")
        info = peer.call("openChest", label=label, position=position)
        assert info["size"] == 27 and info["world"] == world["uuid"] and info["position"] == position
    alice.call("setItem", label="own", slot=0, item="minecraft:diamond", amount=12)
    bob.call("setItem", label="own", slot=0, item="minecraft:emerald", amount=9)
    chest_a = observer.result(case, "i04ReadChest", world["uuid"], 200, 210, 128, "false")
    chest_b = observer.result(case, "i04ReadChest", world["uuid"], 204, 210, 128, "false")
    assert material(at(chest_a, 0)) == "minecraft:diamond" and at(chest_a, 0)["amount"] == 12
    assert material(at(chest_b, 0)) == "minecraft:emerald" and at(chest_b, 0)["amount"] == 9
    single_combined = alice.call("openChest", label="single-combined", position=[200, 210, 128], combined=True)
    assert single_combined["size"] == 27 and single_combined["combined"]
    other_world = next(row for row in observer.result(case, "worlds")["worlds"] if row["uuid"] != world["uuid"])
    observer.result(case, "i04Chest", other_world["uuid"], 700, 70, 700, "CHEST", "false")
    other_ref = alice.call("openChest", label="other-world", position=[700, 70, 700], world=other_world["name"])
    assert other_ref["world"] == other_world["uuid"]
    alice.call("setItem", label="other-world", slot=1, item="minecraft:emerald", amount=2)
    other_native = observer.result(case, "i04ReadChest", other_world["uuid"], 700, 70, 700, "false")
    assert at(other_native, 1)["amount"] == 2
    check("two-independent-chests-buffered-barrier-and-single-combined-view", {"alice": chest_a, "bob": chest_b, "combined": single_combined, "otherWorld": other_ref, "otherNative": other_native})

    double_pos = [511, 210, 128]
    oracle = observer.result(case, "i04Chest", world["uuid"], *double_pos, "CHEST", "true")
    assert oracle["size"] == 54
    left = alice.call("openChest", label="half-a", position=double_pos)
    right = alice.call("openChest", label="half-b", position=[512, 210, 128])
    joined = alice.call("openChest", label="double", position=double_pos, combined=True)
    assert left["size"] == right["size"] == 27 and joined["size"] == 54
    assert joined["layout"] == oracle["layout"]
    alice.call("setItem", label="half-a", slot=0, item="minecraft:gold_ingot", amount=11)
    alice.call("setItem", label="half-b", slot=0, item="minecraft:lapis_lazuli", amount=13)
    full = contents(alice.call("contents", label="double"))
    for part in joined["layout"]:
        expected = "minecraft:gold_ingot" if part["position"] == double_pos else "minecraft:lapis_lazuli"
        assert material(full[part["offset"]]) == expected
    alice.call("setItem", label="double", slot=53, item="minecraft:redstone", amount=5)
    oracle = observer.result(case, "i04ReadChest", world["uuid"], *double_pos, "true")
    assert material(at(oracle, 53)) == "minecraft:redstone"
    check("double-chest-physical-halves-and-native-left-right-layout-across-chunk-boundary", {"metadata": joined, "native": oracle})

    observer.result(case, "i04Split", world["uuid"], *double_pos)
    alice.call("getItem", label="double", slot=0, error="InventoryChangedError")
    assert material(alice.call("getItem", label="half-a", slot=0)) == "minecraft:gold_ingot"
    split = alice.call("openChest", label="split", position=double_pos, combined=True)
    assert split["size"] == 27
    observer.result(case, "i04Merge", world["uuid"], *double_pos)
    alice.call("getItem", label="split", slot=0, error="InventoryChangedError")
    assert material(alice.call("getItem", label="half-a", slot=0)) == "minecraft:gold_ingot"
    observer.result(case, "i04Chest", world["uuid"], 600, 210, 128, "TRAPPED_CHEST", "false")
    trapped = alice.call("openChest", label="trapped", position=[600, 210, 128])
    assert trapped["layout"][0]["key"] == "minecraft:trapped_chest"
    alice.call("setItem", label="trapped", slot=26, item="minecraft:apple", amount=2)
    assert at(observer.result(case, "i04ReadChest", world["uuid"], 600, 210, 128, "false"), 26)["amount"] == 2
    check("split-merge-invalidates-only-combined-layout-and-trapped-chest-is-supported", {"split": split, "trapped": trapped})

    token = f"C:{world['uuid']}:200:210:128:false"
    views = []
    for index, kind in enumerate(("plain", "enchanted", "rich", "shulker", "long")):
        native = observer.result(case, "i04Fixture", token, index, kind)
        first_view = alice.call("getItem", label="own", slot=index)
        repeated = alice.call("getItem", label="own", slot=index)
        after = observer.result(case, "i04ReadChest", world["uuid"], 200, 210, 128, "false")
        assert first_view == repeated and at(after, index)["sha256"] == native["item"]["sha256"]
        if kind == "plain": assert not first_view["hasAdditionalData"] and not first_view["truncated"]
        if kind in ("enchanted", "rich", "shulker"): assert first_view["hasAdditionalData"]
        if kind == "long":
            assert first_view["truncated"] and len(first_view["name"]) == 256
            assert len(first_view["lore"]) == 16 and all(len(line) == 256 for line in first_view["lore"])
        views.append({"kind": kind, "native": native, "view": first_view})
    replaced = alice.call("setItem", label="own", slot=4, item="minecraft:stone", amount=1)
    assert replaced["previous"]["truncated"] and material(replaced["current"]) == "minecraft:stone"
    check("complex-item-views-additional-components-truncation-read-is-nondestructive", {"views": views, "replacement": replaced})

    # Worst-case escaped lore forces real byte pagination; layout change after
    # the first validated network page must not return a partial success dict.
    observer.result(case, "i04Chest", world["uuid"], *double_pos, "CHEST", "true")
    alice.call("openChest", label="pages", position=double_pos, combined=True)
    observer.result(case, "i04FillLong", f"C:{world['uuid']}:511:210:128:true")
    page_result = alice.call("contents", label="pages")
    assert len(page_result["entries"]) == 54 and page_result["pages"] > 1
    assert [row["slot"] for row in page_result["entries"]] == list(range(54))
    assert all(row["item"]["truncated"] for row in page_result["entries"])
    def split_after_page(row):
        assert row["phase"] == "first-page"
        observer.result(case, "i04Split", world["uuid"], *double_pos)
    changed = alice.call("contents", label="pages", hook=True, on_hook=split_after_page, error="InventoryChangedError")
    clear_oracle = observer.result(case, "i04Chest", world["uuid"], *double_pos, "CHEST", "true")
    alice.call("openChest", label="clear-double", position=double_pos, combined=True)
    alice.call("openChest", label="clear-half", position=double_pos)
    for part in clear_oracle["layout"]:
        alice.call("setItem", label="clear-double", slot=part["offset"], item="minecraft:diamond", amount=3)
    half_clear = alice.call("clear", label="clear-half")
    remaining = observer.result(case, "i04ReadChest", world["uuid"], *double_pos, "true")
    own_part = next(part for part in clear_oracle["layout"] if part["position"] == double_pos)
    other_part = next(part for part in clear_oracle["layout"] if part["position"] != double_pos)
    assert at(remaining, own_part["offset"]) is None and at(remaining, other_part["offset"])["amount"] == 3
    all_clear = alice.call("clear", label="clear-double")
    assert all_clear["slots"] == list(range(54))
    assert all(row["item"] is None for row in observer.result(case, "i04ReadChest", world["uuid"], *double_pos, "true")["slots"])
    check("byte-paged-54-slot-contents-and-layout-race-never-returns-partial-dict", {"pages": page_result["pages"], "slots": len(page_result["entries"]), "raceError": changed, "physicalClear": half_clear, "combinedClear": all_clear})

    far = [20000, 210, 20000]; cx, cz = far[0] // 16, far[2] // 16
    observer.result(case, "i04Chest", world["uuid"], *far, "CHEST", "false")
    observer.await_value(case, "i04Unload", (world["uuid"], cx, cz), lambda r: not r["loaded"], timeout=15)
    assert not observer.result(case, "i04Chunk", world["uuid"], cx, cz)["loaded"]
    remote = alice.call("openChest", label="remote", position=far)
    alice.call("setItem", label="remote", slot=0, item="minecraft:diamond", amount=5)
    persisted = observer.result(case, "i04ReadChest", world["uuid"], *far, "false")
    assert at(persisted, 0)["amount"] == 5
    observer.await_value(case, "i04Unload", (world["uuid"], cx, cz), lambda r: not r["loaded"], timeout=15)
    read_reloaded = alice.call("getItem", label="remote", slot=0)
    assert material(read_reloaded) == "minecraft:diamond" and read_reloaded["amount"] == 5
    check("unloaded-persisted-chest-async-chunk-reload-on-open-and-every-rpc", {"metadata": remote, "native": persisted, "reloaded": read_reloaded})

    alice.call("setItem", label="self", slot=5, item="minecraft:diamond", amount=2)
    bob.call("setItem", label="self", slot=5, item="minecraft:emerald", amount=3)
    before_bulk = [observer.result(case, "i04Player", game.name) for game in games]
    alice.call("bulk", slot=5, item="minecraft:iron_sword", amount=64, error="InvalidItemAmountError")
    after_bulk = [observer.result(case, "i04Player", game.name) for game in games]
    assert [at(value, 5)["sha256"] for value in before_bulk] == [at(value, 5)["sha256"] for value in after_bulk]
    bulk = alice.call("bulk", slot=5, item="minecraft:compass", amount=1)
    assert bulk["matched"] == bulk["applied"] == 2
    assert {row["uuid"] for row in bulk["targets"]} == {game.uuid for game in games}
    for game in games: assert material(at(observer.result(case, "i04Player", game.name), 5)) == "minecraft:compass"
    clear_one = alice.call("clear", label="self", slot=5)
    assert clear_one["slots"] == [5] and alice.call("getItem", label="self", slot=5) is None
    assert material(at(observer.result(case, "i04Player", bob_game.name), 5)) == "minecraft:compass"
    check("bulk-selector-resolved-once-prevalidation-no-partial-write-and-targeted-clear", {"bulk": bulk, "clearOne": clear_one})

    alice.call("openPlayer", label="bob", target=bob_game.name)
    alice.call("snapshotPlayer", label="alice", target=alice_game.name)
    alice.call("snapshotPlayer", label="bob", target=bob_game.name)
    bob.close(); bob_game.close()
    observer.await_value(case, "players", (), lambda r: all(p["uuid"] != bob_game.uuid for p in r["players"]))
    alice.call("getItem", label="bob", slot=0, error="PlayerNotFoundError")
    alice.call("setItem", label="self", slot=6, item="minecraft:diamond", amount=1)
    alice.call("bulk", targets=["alice", "bob"], slot=6, item="minecraft:emerald", amount=1, error="PlayerNotFoundError")
    assert material(alice.call("getItem", label="self", slot=6)) == "minecraft:diamond"
    check("offline-uuid-reference-and-bulk-prevalidation-preserve-online-target", {"offlineUuid": bob_game.uuid})

    final = alice.close(); assert not final["remainingThreads"]
    assert final["metadataAfterClose"]["self"] == a_ref
    for game in games:
        assert not game.errors, game.evidence(); game.close()
    check("metadata-remains-local-after-close-and-no-sdk-thread-leaks", {"metadata": final["metadataAfterClose"]["self"], "threads": final["remainingThreads"]})
