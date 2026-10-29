"""Real player-chat I02 scenarios, with independent Paper audit/inventory reads."""

import time
from game_client import GameClient
from observer_client import ObserverClient


def event_ids(batch): return [row["eventId"] for row in batch["events"]]
def messages(batch): return [row["message"] for row in batch["events"]]


def acceptance(harness, paper, Worker, games, workers, check):
    observer = ObserverClient(paper, harness.artifacts / "observer.json")
    case = observer.case_id()
    world = next(row for row in observer.result(case, "worlds")["worlds"] if row["name"] == harness.world_name)
    protocol = observer.result(case, "gameProtocol")
    for index, name in enumerate(("I02Alice", "I02Bob")):
        game = GameClient(harness.game_port, name, protocol); games.append(game); game.wait_ready()
        observer.result(case, "playerPlace", name, world["uuid"], 128 + 32 * index, 210, 128)
        # Dedicated disposable fixture identities may chat quickly during the
        # bounded scenarios; the production event path remains unchanged.
        paper.command("op " + name)
    observer.result(case, "inventoryFixture", games[0].name, "empty")

    def send(game, message, *, cancelled=False):
        game.send_chat(message)
        state = observer.await_value(case, "chatState", (), lambda result: any(
            row["message"] == message and row["playerUuid"] == game.uuid for row in result["events"]))
        row = next(row for row in state["events"] if row["message"] == message)
        assert row["cancelled"] is cancelled and row["asynchronous"] is True, row
        if not cancelled:
            for recipient in games: recipient.wait_chat(message)
        return row

    send(games[0], "i02-before-connect")
    alice = Worker(harness, games[0].name); workers.append(alice)
    bob = Worker(harness, games[1].name); workers.append(bob)
    assert alice.context["pid"] != bob.context["pid"]
    assert alice.context["info"]["sessionId"] != bob.context["info"]["sessionId"]
    for peer in (alice, bob):
        assert peer.context["tokenEnvironmentAbsent"] and peer.context["info"]["world"]["uuid"] == world["uuid"]
        assert "events.subscribe" in peer.context["info"]["capabilities"]
        assert peer.call("recent")["events"] == []
    check("two-native-game-clients-and-independent-source-python-processes", {
        "games": [game.evidence() for game in games], "python": [peer.context for peer in workers]})

    def recent_with(peer, message):
        deadline = time.monotonic() + 10
        while True:
            value = peer.call("recent", limit=100)
            if message in messages(value): return value
            assert time.monotonic() < deadline, "Chat journal normalization deadline"
            time.sleep(.02)

    alice.call("setBlock")
    subscriptions = [alice.call("subscribe", label="action", mode="action", players="$self",
                     actionMessage="i02-gift", ackMessage="i02-python-ack"),
                     bob.call("subscribe", label="record")]
    alice.call("startRun"); bob.call("startRun")
    native = send(games[0], "i02-gift")
    a_state, b_state = alice.call("waitRecords", count=1), bob.call("waitRecords", count=1)
    action = a_state["records"][0]
    assert action["threadName"] == "i02-explicit-callback-consumer" and action["block"] == 4
    assert action["acknowledged"] and action["gift"]["applied"] == 1
    assert action["gift"]["targets"][0]["given"] == 1
    event = action["event"]
    assert event["message"] == "i02-gift" and event["player"]["uuid"] == games[0].uuid
    assert b_state["records"][0]["event"]["eventId"] == event["eventId"]
    busy = alice.call("pollLive", error="RuntimeError")
    for game in games: game.wait_chat("i02-python-ack")
    inventory = observer.result(case, "inventory", games[0].name)
    diamonds = sum(row["item"]["amount"] for row in inventory["slots"]
                   if row["item"] is not None and row["item"]["key"] == "minecraft:diamond")
    assert diamonds == 1, inventory
    check("native-async-chat-callback-sync-rpc-gift-and-game-visible-ack", {
        "native": native, "subscriptions": subscriptions, "action": action, "inventory": inventory,
        "secondConsumerRejected": busy})

    a_pull, b_pull = alice.call("poll"), bob.call("poll")
    assert event_ids(a_pull) == event_ids(b_pull) == [event["eventId"]]
    assert alice.call("genericPoll")["events"] == [] and bob.call("derivedPoll", player=games[0].name)["events"] == []
    recent1, recent2 = alice.call("recent"), alice.call("recent")
    assert event_ids(recent1) == event_ids(recent2) == [event["eventId"]]
    assert "i02-before-connect" not in messages(recent1) and "i02-python-ack" not in messages(recent1)
    check("first-poll-captures-since-hello-aliases-share-cursor-history-is-repeatable", {
        "alice": a_pull, "bob": b_pull, "recent1": recent1, "recent2": recent2})

    send(games[1], "i02-clear-unread")
    # Alice is SELF-filtered: Bob's event still enters history but not her live callback.
    bob.call("waitRecords", count=2); recent_with(alice, "i02-clear-unread")
    alice.call("clear", all=True)
    assert alice.call("poll")["events"] == []
    b_unread = bob.call("poll"); assert messages(b_unread) == ["i02-clear-unread"]
    assert "i02-clear-unread" in messages(alice.call("recent"))
    assert len(alice.call("state")["records"]) == 1
    check("clear-only-own-pull-history-and-other-live-consumers-survive", b_unread)

    bob.call("stopRun"); bob.call("unsubscribe", label="record")
    bob.call("subscribe", label="manual", mode="manual")
    send(games[0], "i02-manual-\u041f\u0440\u0438\u0432\u0435\u0442")
    manual = bob.call("pollLive", timeout=10)
    assert manual["message"] == "i02-manual-\u041f\u0440\u0438\u0432\u0435\u0442"
    assert len(bob.call("state")["records"]) == 2
    manual_pull = bob.call("genericPoll"); assert messages(manual_pull) == ["i02-manual-\u041f\u0440\u0438\u0432\u0435\u0442"]
    assert manual_pull["events"][0]["eventId"] == manual["eventId"]
    alice.call("waitRecords", count=2)
    bob.call("unsubscribe", label="manual")
    check("manual-live-poll-does-not-run-handler-or-consume-pull", {"live": manual, "pull": manual_pull})

    observer.result(case, "chatCancel", "i02-cancelled")
    cancelled = send(games[1], "i02-cancelled", cancelled=True)
    send(games[0], "i02-after-cancel")
    alice.call("waitRecords", count=3)
    history = recent_with(bob, "i02-after-cancel")
    assert "i02-cancelled" not in messages(history) and "i02-python-ack" not in messages(history)
    audit = observer.result(case, "chatState")
    assert not any(row["message"] == "i02-python-ack" for row in audit["events"])
    observer.result(case, "chatCancel", "$reset")
    check("cancelled-native-chat-is-excluded-and-postToChat-has-no-event-feedback", {
        "cancelled": cancelled, "history": history, "audit": audit})

    alice.call("stopRun"); alice.call("unsubscribe", label="action")
    send(games[1], "i02-after-unsubscribe")
    recent_with(alice, "i02-after-unsubscribe")
    assert len(alice.call("state")["records"]) == 3
    alice.call("subscribe", label="raise", mode="raise")
    alice.call("startRun")
    send(games[1], "i02-handler-error")
    alice.call("waitRecords", count=4)
    failed_run = alice.call("waitRunEnd")
    assert failed_run["runErrors"][-1]["type"] == "ValueError" and not failed_run["runAlive"]
    assert alice.call("getBlock") == 4
    alice.call("unsubscribe", label="raise")
    check("unsubscribe-fence-and-handler-exception-with-rpc-still-usable", failed_run)

    alice.call("subscribe", label="self-stop", mode="stop")
    alice.call("startRun")
    send(games[0], "i02-self-stop")
    stopped = alice.call("waitRunEnd")
    assert not stopped["runAlive"] and len(stopped["records"]) == 5
    alice.call("unsubscribe", label="self-stop")
    alice.call("subscribe", label="idle", mode="record")
    alice.call("startRun"); assert alice.call("state")["runAlive"]
    idle_stop = alice.call("stopRun"); assert not idle_stop["runAlive"]
    alice.call("startRun"); assert alice.call("state")["runAlive"]
    closed = alice.close()
    assert closed["remainingThreads"] == [] and not closed["state"]["runAlive"]
    assert bob.call("getBlock") == 4
    check("callback-stop-idle-stop-and-close-wake-with-no-thread-leaks", {"selfStop": stopped, "idleStop": idle_stop, "close": closed})

    reconnected = Worker(harness, games[0].name); workers.append(reconnected)
    assert reconnected.context["info"]["sessionId"] != alice.context["info"]["sessionId"]
    assert reconnected.call("recent")["events"] == []
    reconnected.call("subscribe", label="fresh")
    reconnected.call("startRun")
    send(games[1], "i02-fresh-session")
    fresh = reconnected.call("waitRecords", count=1)
    fresh_history = reconnected.call("recent")
    assert messages(fresh_history) == ["i02-fresh-session"]
    # This connection has never used pull: clearAll must still move its initial
    # per-type cursor, without eating the live callback or retained history.
    reconnected.call("clear", all=True)
    assert reconnected.call("poll")["events"] == []
    assert messages(reconnected.call("recent")) == ["i02-fresh-session"]
    assert "i02-fresh-session" in messages(bob.call("poll"))
    reconnected.close(); bob.close()
    check("reconnect-resets-session-baseline-with-other-process-independent", {
        "fresh": fresh, "history": fresh_history, "context": reconnected.context})
    for game in games:
        assert not game.errors, game.evidence()
        game.close()
