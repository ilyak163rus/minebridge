"""Combined final-wheel scenarios; observer is independent of the production bridge."""

from pathlib import Path
import json
import os
import statistics
import subprocess
import time
from game_client import GameClient
from observer_client import ObserverClient

ROOT = Path(__file__).resolve().parents[2]


def event_ids(batch): return [row["eventId"] for row in batch["events"]]


def acceptance(harness, paper, Worker, games, workers, check):
    observer = ObserverClient(paper, harness.artifacts / "observer.json"); case = observer.case_id()
    world = next(row for row in observer.result(case, "worlds")["worlds"] if row["name"] == harness.world_name)
    protocol = observer.result(case, "gameProtocol")

    def tick(n=3):
        start = observer.result(case, "releaseBurstStatus")["tick"]
        return observer.await_value(case, "releaseBurstStatus", (), lambda row: row["tick"] >= start+n)

    def place(game, x, *, mode="CREATIVE", invulnerable=True):
        result = observer.result(case, "i03Player", game.name, world["uuid"], x, 210, 128.5, 0, 0, mode, str(invulnerable).lower())
        tick(2); return result

    for name in ("I05Alice", "I05Bob"):
        game = GameClient(harness.game_port, name, protocol); games.append(game); game.wait_ready(); paper.command("op " + name)
    a_game, b_game = games
    for game, x in ((a_game, 128.5), (b_game, 160.5)):
        observer.result(case, "i03Block", world["uuid"], int(x), 209, 128, "COBBLESTONE")
        place(game, x); observer.result(case, "i04EmptyPlayer", game.name)
    alice, bob = Worker(harness, a_game.name), Worker(harness, b_game.name)
    workers.extend((alice, bob))
    assert alice.context["pid"] != bob.context["pid"]
    assert alice.context["info"]["sessionId"] != bob.context["info"]["sessionId"]
    assert all(p.context["version"] == "0.3.0" and p.context["isolated"] for p in (alice,bob))
    check("two-real-players-and-independent-final-installed-wheel-processes", {"python": [p.context for p in (alice,bob)], "games": [g.evidence() for g in games]})

    controls = alice.call("controls")
    assert controls["mode"] == "creative" and controls["weather"] == "clear" and controls["rule"] is True
    # Native observer independently checks the actual effect amplifier.
    actual = observer.result(case, "controlPlayer", a_game.name)
    assert actual["gameMode"] == "creative", actual
    speed=next(effect for effect in actual["effects"] if effect["key"]=="minecraft:speed")
    assert speed["amplifier"]==199 and 0<speed["durationTicks"]<=2000,speed
    check("final-controls-position-effects-and-world-settings", {"api": controls,"native":actual})

    alice.call("setBlock", position=[200,210,128], block="minecraft:chest")
    bob.call("setBlock", position=[204,210,128], block="minecraft:chest")
    alice.call("openChest", position=[200,210,128]); bob.call("openChest", position=[204,210,128])
    alice.call("subscribe", label="chat", type="chat.message", mode="chat-action", message="i05-reward", players="$self")
    bob.call("subscribe", label="chat", type="chat.message")
    alice.call("subscribe", label="break", type="block.break", mode="block-action", players="$self")
    alice.call("subscribe", label="lava", type="player.enter_lava", mode="lava-action", players="$self")
    alice.call("startRun"); bob.call("startRun")
    a_game.send_chat("i05-reward")
    action = alice.call("waitCount", label="chat", count=1)
    peer = bob.call("waitCount", label="chat", count=1)
    assert action["latest"]["chat"]["event"]["eventId"] == peer["latest"]["chat"]["event"]["eventId"]
    assert action["latest"]["chat"]["thread"] == "i05-explicit-event-consumer"
    assert action["latest"]["chat"]["slot"]["current"]["amount"] == 4
    for game in games: game.wait_chat("i05-reward-ack")
    native_inventory = observer.result(case, "i04Player", a_game.name)
    assert next(row["item"] for row in native_inventory["slots"] if row["slot"]==2)["amount"] == 4
    native_chest = observer.result(case, "i04ReadChest",world["uuid"],200,210,128,"false")
    assert native_chest["slots"][0]["item"]["amount"] == 3
    observer.result(case,"i03Block",world["uuid"],128,210,130,"COBBLESTONE")
    a_game.break_block((128,210,130)); alice.call("waitCount",label="break",count=1)
    assert alice.call("getSlot",slot=3)["key"]["key"] == "minecraft:compass"
    observer.result(case,"i03Block",world["uuid"],130,209,128,"STONE")
    observer.result(case,"i03Block",world["uuid"],130,210,128,"LAVA")
    place(a_game,130.5)
    rescued=alice.call("waitCount",label="lava",count=1)
    assert rescued["latest"]["lava"]["teleport"]["applied"]==1
    assert alice.call("getSlot",slot=4)["key"]["key"]=="minecraft:emerald"
    observer.result(case,"i03Block",world["uuid"],130,210,128,"AIR")
    check("native-chat-break-lava-callbacks-call-exact-inventory-slots-and-sync-rpc", {"chat":action["latest"]["chat"],"nativeInventory":native_inventory,"nativeChest":native_chest,"lava":rescued["latest"]["lava"]})

    a_chat,b_chat=alice.call("poll",alias="chat"),bob.call("poll",alias="chat")
    assert event_ids(a_chat)==event_ids(b_chat) and len(a_chat["events"])==1
    assert alice.call("poll",context=b_game.name)["events"]==[]
    assert event_ids(alice.call("recent"))==event_ids(a_chat)
    assert alice.call("poll",type="block.break")["events"]
    a_game.send_chat("i05-own-clear")
    bob.call("waitCount",label="chat",count=2)
    alice.call("clear",all=True)
    assert alice.call("poll")["events"]==[]
    assert any(e["message"]=="i05-own-clear" for e in bob.call("poll")["events"])
    assert any(e["message"]=="i05-own-clear" for e in alice.call("recent")["events"])
    check("per-type-alias-withContext-and-per-process-history-independent-of-live", {"initial":a_chat,"other":b_chat})

    alice.call("stopRun")
    for label in ("chat","break","lava"): alice.call("unsubscribe",label=label)
    alice.call("subscribe",label="blocked",mode="blocked",message="i05-blocked")
    alice.call("startRun"); a_game.send_chat("i05-blocked")
    blocked=alice.call("waitCount",label="blocked",count=1); assert blocked["handlerBlocked"]
    assert bob.call("getBlock")==4 and alice.call("getBlock")==4
    b_game.send_chat("i05-peer-progress"); bob.call("waitCount",label="chat",count=4)
    assert alice.call("stopRun",join=False)["handlerBlocked"]
    alice.call("release"); alice.call("waitRunEnd"); alice.call("unsubscribe",label="blocked")
    alice.call("subscribe",label="failing",mode="raise",message="i05-failing")
    alice.call("startRun"); a_game.send_chat("i05-failing")
    failed=alice.call("waitRunEnd"); assert failed["runErrors"][-1]["type"]=="ValueError"
    assert failed["counts"]["failing"]==1
    assert alice.call("getBlock")==bob.call("getBlock")==4
    alice.call("unsubscribe",label="failing")
    check("blocked-and-failing-handler-do-not-block-peer-or-rpc", {"blocked":blocked,"failed":failed})

    # Bounded native event load, independent oracle counter, no synthetic capture.
    place(b_game,160.5,mode="SURVIVAL",invulnerable=False)
    observer.result(case,"i03Cancel","entity.damage","false")
    def burst(name,count):
        started=time.perf_counter()
        observer.result(case,"releaseBurst",name,b_game.name,a_game.name,count,32)
        result=observer.await_value(case,"releaseBurstStatus",(),lambda row:not row["active"],timeout=50)
        assert result["error"] is None and result["produced"]==result["observedNative"]==count,result
        return {**result,"wallSeconds":time.perf_counter()-started}
    alice.call("subscribe",label="slow-python",type="entity.damage",mode="manual",players=None)
    bob.call("subscribe",label="damage",type="entity.damage",players=None)
    python_load=burst("python-overflow",600)
    python_overflow=alice.call("pollLive",error="EventOverflowError"); assert python_overflow["source"]=="python"
    assert alice.call("pollLive",error="EventOverflowError")["source"]=="python"
    assert alice.call("getBlock")==bob.call("getBlock")==4
    bob.call("waitCount",label="damage",count=600)
    alice.call("unsubscribe",label="slow-python")
    check("python-live-overflow-visible-repeated-rpc-and-peer-continue", {"load":python_load,"error":python_overflow})

    alice.call("subscribe",label="slow-server",type="entity.damage",mode="manual",players=None)
    sid=alice.context["info"]["sessionId"]
    observer.result(case,"writerPause",sid)
    observer.result(case,"releaseBurst","server-overflow",b_game.name,a_game.name,600,32)
    alice.start("setBlock",position=[128,209,128])
    assert bob.call("getBlock")==4
    server_load=observer.await_value(case,"releaseBurstStatus",(),lambda row:not row["active"],timeout=15)
    assert server_load["observedNative"]==600
    stats=observer.result(case,"sessionStats",sid); assert stats["open"] and stats["writerPaused"]
    observer.result(case,"writerResume",sid)
    assert alice.result()["acknowledged"]
    server_overflow=alice.call("pollLive",error="EventOverflowError"); assert server_overflow["source"]=="server"
    assert alice.call("pollLive",error="EventOverflowError")["source"]=="server"
    alice.call("unsubscribe",label="slow-server")
    bob.call("waitCount",label="damage",count=1200)
    bob.call("stopRun"); bob.call("unsubscribe",label="damage"); bob.call("unsubscribe",label="chat")
    check("server-live-overflow-preserves-rpc-ack-and-other-session-progress", {"load":server_load,"stats":stats,"error":server_overflow})

    alice.call("clear",all=True); bob.call("clear",all=True)
    history_load=burst("history-retention",4300)
    lost=alice.call("poll",type="entity.damage",error="EventHistoryLostError")
    # The public Python exception exposes code/outcome, not optional wire data.
    # This bounded run produces 4300 native events against the 4096-record ring;
    # repeated typed loss and the recent window below prove retention separately.
    assert lost.get("code")=="EVENT_HISTORY_LOST" and lost.get("outcome")=="not-applied",lost
    alice.call("poll",type="entity.damage",error="EventHistoryLostError")
    window=alice.call("recent",type="entity.damage",limit=10)
    assert len(window["events"])==10 and window["metadata"]["windowLimited"]
    assert bob.call("poll",type="projectile.shot")["events"]==[]
    assert bob.call("poll",type="chat.message")["events"]==[]
    alice.call("clear",type="entity.damage")
    assert alice.call("poll",type="entity.damage")["events"]==[] and alice.call("getBlock")==4
    check("ram-history-loss-distinct-from-live-overflow-type-aware-clear-and-recent", {"load":history_load,"error":lost,"window":window["metadata"]})

    # Final benchmark is deliberately outside event load and logging.
    benchmark_hold=observer.result(case,"setup",world["uuid"],"256,209,128","272,209,128","256,209,144","272,209,144")
    final_timings=alice.call("benchmark",counts=[100,1000],repeats=3)
    check("buffered-block-timings-final-plugin-and-final-wheel-no-flood-no-logging", final_timings)
    from v03_i05_probe_support import probe, short_exit, legacy_example
    old_python=ROOT/".venv-v021-314/Scripts/python.exe"
    alice.call("clearEffects")
    old=probe(harness,old_python,"legacy",version="0.2.1",marker="i05-old-client")
    assert old["block"]==4 and old["runtimeId"]==a_game.entity_id and old["giftApplied"]==old["effectApplied"]==1
    a_game.wait_chat("i05-old-client")
    # Fresh processes on the same held/warmed chunks, balanced SDK order.
    paired=[]
    for python,version in ((harness.python,"0.3.0"),(old_python,"0.2.1"),
                           (old_python,"0.2.1"),(harness.python,"0.3.0")):
        paired.append(probe(harness,python,"benchmark",version=version))
    old_on_new=paired[1]
    check("old-0-2-1-client-legacy-imports-and-public-domains-on-final-plugin", old)
    check("old-client-on-new-plugin-buffered-block-measurements", old_on_new)
    benchmark_native=observer.result(case,"read",world["uuid"],263,210,159)
    assert benchmark_native["key"]=="minecraft:cobblestone"
    check("paired-fresh-installed-sdk-buffered-benchmarks-with-identical-warmup",
          {"runs":paired,"heldChunks":benchmark_hold["chunks"],"native":benchmark_native})
    observer.result(case,"cleanup")
    example_results=[legacy_example(harness,python) for python in (harness.python,old_python)]
    check("existing-0-2-buffered-blocks-example-runs-with-both-installed-clients",example_results)
    normal_exit=short_exit(harness,paper,observer,case,a_game)
    check("two-argument-create-and-normal-exit-drains-without-close",normal_exit)

    quiet=Worker(harness,None); logged=Worker(harness,None,logging=True)
    workers.extend((quiet,logged))
    for peer in (quiet,logged): peer.call("setBlock",position=[138,210,128]); assert peer.call("getBlock",position=[138,210,128])==4
    tick(5)
    quiet_lines=[line for line in paper.lines if "ACTION session="+quiet.context["info"]["sessionId"] in line]
    logged_lines=[line for line in paper.lines if "ACTION session="+logged.context["info"]["sessionId"] in line]
    assert not quiet_lines and any("method=blocks.set" in line and "phase=completed" in line for line in logged_lines)
    check("logging-opt-in-session-local-with-identical-game-results",{"quiet":quiet.context,"logged":logged.context,"lines":logged_lines})
    quiet.close(); logged.close()

    bob.close(); alice.close()
    watch=Worker(harness,a_game.name); workers.append(watch)
    watch.call("subscribe",label="restart",type="chat.message"); watch.call("startRun")
    for game in games: assert not game.errors,game.evidence();game.close()
    check("final-game-clients-clean-and-restart-watch-armed", {"games":[g.evidence() for g in games],"watch":watch.context})
    return {"world":world,"watch":watch,"finalTimings":final_timings,"oldClientOnNew":old_on_new["measurements"],"pairedFresh":paired}
