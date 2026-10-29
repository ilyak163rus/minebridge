"""CHAT I02 over controlled real TCP: demux, caller dispatch and journal cursors.

These peers verify SDK protocol behavior; actual Paper capture is tested separately.
"""

from dataclasses import FrozenInstanceError
import threading
import time
import unittest
from uuid import UUID, uuid4

from minebridge import Minecraft, block, errors, events, selector
from minebridge._protocol import CodecError, decode_event, encode_frame, error_frame
from minebridge.models import ChatEvent, EventBatch
from test_handshake import hello_result
from test_transport import peer, read_request

WORLD = "11111111-1111-4111-8111-111111111111"
EPOCH = "22222222-2222-4222-8222-222222222222"
PLAYER = "33333333-3333-4333-8333-333333333333"
CAPABILITIES = ["events.subscribe", "events.unsubscribe", "events.pollEvents", "events.getRecent", "events.clearPending"]


def event_hello(*, max_events=512, start=10):
    value = hello_result()
    value["world"]["uuid"] = WORLD
    value["capabilities"] += CAPABILITIES
    value["eventHistory"] = {
        "epoch": EPOCH, "world": WORLD, "startSequence": start,
        "retention": {"maxRecords": 4096, "maxBytes": 4194304, "maxAgeTicks": 2400},
        "maxSubscriptions": 32, "maxLiveEvents": max_events,
    }
    return value


def cursor(sequence):
    return {"epoch": EPOCH, "world": WORLD, "sequence": sequence}


def record(sequence=11, message="привет"):
    return {
        "eventId": str(uuid4()), "serverEpoch": EPOCH, "sequence": sequence, "serverTick": 42,
        "eventType": "chat.message", "world": {"uuid": WORLD, "name": "world", "key": "minecraft:overworld"},
        "data": {"player": {"uuid": PLAYER, "name": "Alice", "entityId": 7},
                 "message": message, "cancelled": False, "truncated": False},
    }


def live(identity, sequence=11, delivery=1):
    return encode_frame({"jsonrpc": "2.0", "method": "events.event", "params": {
        "subscriptionId": identity, "deliverySequence": delivery, "event": record(sequence),
    }})


def ack(request, value):
    return encode_frame({"jsonrpc": "2.0", "id": request["id"], "result": value})


def subscription_ack(request):
    return ack(request, {"subscriptionId": request["params"]["subscriptionId"],
                         "eventType": "chat.message", "world": WORLD})


def batch(rows=(), *, next_sequence=10, upper=None, recent=False, available=1):
    upper = next_sequence if upper is None else upper
    value = {"events": list(rows), "nextCursor": cursor(next_sequence), "upperBound": upper,
             "availableFrom": available, "hasMore": next_sequence < upper}
    if recent:
        value.update(sessionStart=10, windowLimited=False)
    return value


def server_handler(action=None, *, metadata=None, requests=None):
    def handle(connection, stopping):
        hello = read_request(connection)
        if requests is not None:
            requests.append(hello)
        connection.sendall(ack(hello, metadata if metadata is not None else event_hello()))
        while not stopping.is_set():
            request = read_request(connection)
            if request is None:
                return
            if requests is not None:
                requests.append(request)
            if action is not None:
                handled = action(connection, request)
                if handled == "close":
                    return
                if handled:
                    continue
            method = request["method"]
            if method == "events.subscribe":
                connection.sendall(subscription_ack(request))
            elif method == "events.unsubscribe":
                connection.sendall(ack(request, {"subscriptionId": request["params"]["subscriptionId"], "unsubscribed": True}))
            elif method == "players.get":
                connection.sendall(ack(request, {"player": {"uuid": PLAYER, "name": "Alice", "entityId": 7}}))
            elif method in ("events.pollEvents", "events.getRecent"):
                connection.sendall(ack(request, batch(recent=method == "events.getRecent")))
            elif method == "events.clearPending":
                connection.sendall(ack(request, {"cursor": cursor(20)}))
            else:
                connection.sendall(ack(request, {"applied": True}))
    return handle


class EventTests(unittest.TestCase):
    def connect(self, server, **kwargs):
        mc = Minecraft.create("127.0.0.1", server.port, timeout=1, writeMode="sync", **kwargs)
        self.addCleanup(mc.close)
        return mc

    def start(self, call):
        done, failures = threading.Event(), []

        def invoke():
            try:
                call()
            except BaseException as failure:
                failures.append(failure)
            finally:
                done.set()
        thread = threading.Thread(target=invoke)
        thread.start()
        self.addCleanup(lambda: thread.join(2))
        return thread, done, failures

    def wait_consumer(self, mc):
        state = mc.events._state
        until = time.monotonic() + 1
        with state.condition:
            while not state._consumer and time.monotonic() < until:
                state.condition.wait(.01)
            self.assertTrue(state._consumer)

    def test_hello_metadata_optional_and_default_request_unchanged(self):
        requests = []
        with peer(server_handler(requests=requests)) as server:
            mc = self.connect(server)
            self.assertEqual(set(requests[0]["params"]), {"protocol", "token", "world", "coordinates"})
            metadata = mc._transport.context.event_history
            self.assertEqual(metadata.start_sequence, 10)
            with self.assertRaises(FrozenInstanceError):
                metadata.start_sequence = 11

    def test_old_server_rejected_locally_without_new_rpc(self):
        requests = []
        with peer(server_handler(metadata=hello_result(), requests=requests)) as server:
            mc = self.connect(server)
            for call in (lambda: mc.events.subscribe(events.CHAT_MESSAGE), mc.events.run,
                         mc.events.poll, mc.events.pollChatPosts, lambda: mc.events.getRecent(events.CHAT_MESSAGE),
                         mc.events.clearPending):
                with self.assertRaises(errors.UnsupportedFeatureError):
                    call()
            self.assertEqual(len(requests), 1)

    def test_ack_and_event_same_chunk_and_pending_zero_fragmented(self):
        send_next, sent = threading.Event(), threading.Event()

        def action(connection, request):
            if request["method"] != "events.subscribe":
                return False
            identity = request["params"]["subscriptionId"]
            notification = live(identity)
            connection.sendall(subscription_ack(request) + notification[:30])
            if not send_next.wait(1):
                raise AssertionError("client did not request remaining notification")
            connection.sendall(notification[30:])
            sent.set()
            return True
        with peer(server_handler(action)) as server:
            mc = self.connect(server)
            subscription = mc.events.subscribe(events.CHAT_MESSAGE)
            self.assertIsNone(mc.events.poll())
            send_next.set()
            event = mc.events.poll(timeout=1)
            self.assertTrue(sent.wait(1))
            self.assertIsInstance(event, ChatEvent)
            self.assertEqual((event.message, event.player.name, event.sequence, event.deliverySequence), ("привет", "Alice", 11, 1))
            self.assertEqual(event.subscriptionId, subscription.id)
            self.assertEqual(event.eventType, events.CHAT_MESSAGE)
            self.assertEqual(subscription.world, UUID(WORLD))
            with self.assertRaises(FrozenInstanceError):
                event.message = "changed"

    def test_callback_runs_on_caller_and_can_wait_for_sync_rpc(self):
        requests, thread_ids = [], []

        def action(connection, request):
            if request["method"] == "events.subscribe":
                connection.sendall(subscription_ack(request) + live(request["params"]["subscriptionId"]))
                return True
            return False
        with peer(server_handler(action, requests=requests)) as server:
            mc = self.connect(server)

            def on_chat(event):
                thread_ids.append(threading.get_ident())
                mc.setBlock(0, 80, 0, block.STONE)
                mc.events.stop()
            subscription = mc.events.subscribe(events.CHAT_MESSAGE, on_chat)
            self.assertEqual(thread_ids, [])
            mc.events.run()
            self.assertEqual(thread_ids, [threading.get_ident()])
            self.assertNotEqual(thread_ids[0], mc._transport._reader.ident)
            self.assertEqual(requests[-1]["method"], "blocks.set")
            subscription.unsubscribe()

    def test_callback_failure_propagates_and_consumer_released(self):
        def action(connection, request):
            if request["method"] == "events.subscribe":
                connection.sendall(subscription_ack(request) + live(request["params"]["subscriptionId"]))
                return True
            return False
        with peer(server_handler(action)) as server:
            mc = self.connect(server)
            def handler(event):
                raise ValueError("callback marker")
            mc.events.subscribe(events.CHAT_MESSAGE, handler)
            with self.assertRaisesRegex(ValueError, "callback marker"):
                mc.events.run()
            self.assertIsNone(mc.events.poll())
            self.assertFalse(mc._transport.closed)

    def test_missing_handler_rejected_but_manual_poll_allowed(self):
        with peer(server_handler()) as server:
            mc = self.connect(server)
            mc.events.subscribe(events.CHAT_MESSAGE)
            with self.assertRaises(ValueError):
                mc.events.run()
            self.assertIsNone(mc.events.poll())

    def test_shared_facade_consumer_stop_wakeup_and_restart(self):
        with peer(server_handler()) as server:
            mc = self.connect(server)
            facade = mc.withContext()
            self.assertIs(mc.events._state, facade.events._state)
            subscription = mc.events.subscribe(events.CHAT_MESSAGE, lambda e: None)
            for _ in range(2):
                thread, done, failures = self.start(mc.events.run)
                self.wait_consumer(mc)
                with self.assertRaises(RuntimeError):
                    facade.events.poll()
                facade.events.stop()
                self.assertTrue(done.wait(1))
                self.assertEqual(failures, [])
                thread.join(1)
            self.assertFalse(mc._transport.closed)
            subscription.unsubscribe()

    def test_local_close_wakes_idle_run_and_poll_normally(self):
        for consume in ("run", "poll"):
            with self.subTest(consume=consume), peer(server_handler()) as server:
                mc = self.connect(server)
                mc.events.subscribe(events.CHAT_MESSAGE, lambda e: None)
                thread, done, failures = self.start(mc.events.run if consume == "run" else lambda: mc.events.poll(None))
                self.wait_consumer(mc)
                mc.withContext().close()
                self.assertTrue(done.wait(1))
                self.assertEqual(failures, [])
                thread.join(1)

    def test_real_disconnect_wakes_idle_consumer_with_connection_error(self):
        disconnect = threading.Event()
        def action(connection, request):
            if request["method"] == "events.subscribe":
                connection.sendall(subscription_ack(request))
                disconnect.wait(2)
                return "close"
            return False
        with peer(server_handler(action)) as server:
            mc = self.connect(server)
            mc.events.subscribe(events.CHAT_MESSAGE, lambda e: None)
            thread, done, failures = self.start(mc.events.run)
            self.wait_consumer(mc)
            disconnect.set()
            self.assertTrue(done.wait(1))
            self.assertEqual(len(failures), 1)
            self.assertIsInstance(failures[0], errors.ConnectionError)
            thread.join(1)

    def test_callback_can_close_or_unsubscribe_itself(self):
        for close in (False, True):
            with self.subTest(close=close):
                def action(connection, request):
                    if request["method"] == "events.subscribe":
                        connection.sendall(subscription_ack(request) + live(request["params"]["subscriptionId"]))
                        return True
                    return False
                with peer(server_handler(action)) as server:
                    mc = self.connect(server)
                    def handler(event):
                        if close:
                            mc.close()
                        else:
                            subscription.unsubscribe()
                            mc.events.stop()
                    subscription = mc.events.subscribe(events.CHAT_MESSAGE, handler)
                    mc.events.run()
                    self.assertEqual(mc._transport.closed, close)

    def test_unsubscribe_drops_queued_and_tombstones_late_frames(self):
        requests = []
        def action(connection, request):
            if request["method"] == "events.subscribe":
                connection.sendall(subscription_ack(request) + live(request["params"]["subscriptionId"]))
                return True
            if request["method"] == "events.unsubscribe":
                identity = request["params"]["subscriptionId"]
                connection.sendall(live(identity, 12, 2) + ack(request, {"subscriptionId": identity, "unsubscribed": True}) + live(identity, 13, 3))
                return True
            return False
        with peer(server_handler(action, requests=requests)) as server:
            mc = self.connect(server)
            sub = mc.events.subscribe(events.CHAT_MESSAGE)
            sub.unsubscribe()
            sub.unsubscribe()
            self.assertIsNone(mc.events.poll())
            mc.setBlock(0, 80, 0, block.STONE)
            self.assertEqual([r["method"] for r in requests].count("events.unsubscribe"), 1)

    def test_delivery_gaps_unknown_subscription_and_event_before_ack_are_protocol_errors(self):
        for corruption in ("gap", "unknown", "before_ack", "world", "epoch"):
            with self.subTest(corruption=corruption):
                def action(connection, request):
                    if request["method"] != "events.subscribe":
                        return False
                    identity = request["params"]["subscriptionId"]
                    frame = live(str(uuid4()) if corruption == "unknown" else identity)
                    if corruption == "gap":
                        frame += live(identity, 12, 3)
                    if corruption in ("world", "epoch"):
                        value = record()
                        if corruption == "world":
                            value["world"]["uuid"] = str(uuid4())
                        else:
                            value["serverEpoch"] = str(uuid4())
                        frame = encode_frame({"jsonrpc": "2.0", "method": "events.event", "params": {
                            "subscriptionId": identity, "deliverySequence": 1, "event": value}})
                    connection.sendall(frame + subscription_ack(request) if corruption == "before_ack"
                                       else subscription_ack(request) + frame)
                    return True
                with peer(server_handler(action)) as server:
                    mc = self.connect(server)
                    with self.assertRaises(errors.ProtocolError):
                        mc.events.subscribe(events.CHAT_MESSAGE)
                    self.assertTrue(mc._transport.closed)

    def test_server_and_python_overflow_repeat_until_unsubscribe_without_breaking_rpc(self):
        for source in ("server", "capture", "python"):
            with self.subTest(source=source):
                def action(connection, request):
                    if request["method"] != "events.subscribe":
                        return False
                    identity = request["params"]["subscriptionId"]
                    notification = (live(identity) + live(identity, 12, 2) + live(identity, 13, 3)
                                    if source == "python" else encode_frame({"jsonrpc": "2.0", "method": "events.overflow", "params": {
                                        "subscriptionIds": [identity], "source": source, "lostCount": 2}}))
                    connection.sendall(subscription_ack(request) + notification)
                    return True
                with peer(server_handler(action, metadata=event_hello(max_events=2))) as server:
                    mc = self.connect(server)
                    sub = mc.events.subscribe(events.CHAT_MESSAGE)
                    for _ in range(2):
                        with self.assertRaises(errors.EventOverflowError) as caught:
                            mc.events.poll()
                        self.assertEqual(caught.exception.source, source)
                    mc.setBlock(0, 80, 0, block.STONE)
                    sub.unsubscribe()
                    self.assertIsNone(mc.events.poll())

    def test_filters_validate_before_rpc_and_self_binds_executor_uuid(self):
        requests = []
        with peer(server_handler(requests=requests)) as server:
            mc = self.connect(server)
            for options in ({"players": selector.SELF}, {"players": selector.RANDOM_PLAYER}, {"region": (0, 0, 0)},
                            {"blocks": [block.STONE]}, {"handler": 3}):
                with self.assertRaises((errors.MissingContextError, errors.InvalidSelectorError, ValueError, TypeError)):
                    mc.events.subscribe(events.CHAT_MESSAGE, **options)
            with self.assertRaises(errors.InvalidEventTypeError):
                mc.events.subscribe("future.unknown")
            self.assertEqual(len(requests), 1)
            facade = mc.withContext(player="Alice")
            sub = facade.events.subscribe(events.CHAT_MESSAGE, players=selector.SELF)
            self.assertEqual(requests[-1]["params"]["executor"], PLAYER)
            self.assertEqual(requests[-1]["params"]["players"], "@s")
            sub.unsubscribe()

    def test_history_alias_shared_cursor_and_live_independent(self):
        requests = []
        def action(connection, request):
            if request["method"] == "events.subscribe":
                connection.sendall(subscription_ack(request) + live(request["params"]["subscriptionId"]))
                return True
            if request["method"] == "events.pollEvents":
                sequence = request["params"]["cursor"]["sequence"]
                connection.sendall(ack(request, batch([record(11)] if sequence == 10 else [], next_sequence=11)))
                return True
            return False
        with peer(server_handler(action, requests=requests)) as server:
            mc = self.connect(server)
            mc.events.subscribe(events.CHAT_MESSAGE)
            first = mc.events.pollChatPosts()
            second = mc.withContext().events.pollEvents(events.CHAT_MESSAGE)
            self.assertIsInstance(first, EventBatch)
            self.assertEqual((len(first), len(second), first.nextCursor.sequence), (1, 0, 11))
            self.assertEqual([request["params"]["cursor"]["sequence"] for request in requests if request["method"] == "events.pollEvents"], [10, 11])
            self.assertEqual(mc.events.poll().message, "привет")
            self.assertIsNone(first[0].subscriptionId)
            with self.assertRaises(FrozenInstanceError):
                first.hasMore = False

    def test_history_error_preserves_cursor_and_does_not_break_live(self):
        attempts, cursors = [], []
        def action(connection, request):
            if request["method"] != "events.pollEvents":
                return False
            cursors.append(request["params"]["cursor"]["sequence"])
            attempts.append(True)
            connection.sendall(error_frame(request["id"], "EVENT_HISTORY_LOST") if len(attempts) == 1
                               else ack(request, batch([record()], next_sequence=11)))
            return True
        with peer(server_handler(action)) as server:
            mc = self.connect(server)
            with self.assertRaises(errors.EventHistoryLostError):
                mc.events.pollChatPosts()
            self.assertIsNone(mc.events.poll())
            self.assertEqual(len(mc.events.pollChatPosts()), 1)
            self.assertEqual(cursors, [10, 10])

    def test_wrong_history_correlation_never_commits_cursor(self):
        def action(connection, request):
            if request["method"] == "events.pollEvents":
                value = batch(next_sequence=11)
                value["nextCursor"]["world"] = str(uuid4())
                connection.sendall(ack(request, value))
                return True
            return False
        with peer(server_handler(action)) as server:
            mc = self.connect(server)
            with self.assertRaises(errors.ProtocolError):
                mc.events.pollChatPosts()
            self.assertEqual(mc.events._state.history_cursors, {})

    def test_recent_assembles_fixed_window_without_moving_poll_cursor(self):
        requests = []
        def action(connection, request):
            if request["method"] != "events.getRecent":
                return False
            params = request["params"]
            if params["cursor"] is None:
                value = batch([record(18)], next_sequence=18, upper=20, recent=True)
            else:
                self.assertEqual((params["cursor"]["sequence"], params["upperBound"], params["limit"]), (18, 20, 2))
                value = batch([record(19), record(20)], next_sequence=20, recent=True)
            connection.sendall(ack(request, value))
            return True
        with peer(server_handler(action, requests=requests)) as server:
            mc = self.connect(server)
            recent = mc.events.getRecent(events.CHAT_MESSAGE, limit=3)
            self.assertEqual([event.sequence for event in recent], [18, 19, 20])
            self.assertEqual(recent.upperBound, 20)
            mc.events.pollChatPosts()
            self.assertEqual(requests[-1]["params"]["cursor"]["sequence"], 10)

    def test_recent_retention_error_returns_no_partial_success(self):
        def action(connection, request):
            if request["method"] != "events.getRecent":
                return False
            connection.sendall(ack(request, batch([record(18)], next_sequence=18, upper=20, recent=True))
                               if request["params"]["cursor"] is None else error_frame(request["id"], "EVENT_HISTORY_LOST"))
            return True
        with peer(server_handler(action)) as server:
            mc = self.connect(server)
            with self.assertRaises(errors.EventHistoryLostError):
                mc.events.getRecent(events.CHAT_MESSAGE, limit=3)
            self.assertEqual(mc.events._state.history_cursors, {})

    def test_clear_all_advances_even_never_read_type_and_preserves_live(self):
        requests = []
        def action(connection, request):
            if request["method"] == "events.subscribe":
                connection.sendall(subscription_ack(request) + live(request["params"]["subscriptionId"]))
                return True
            if request["method"] == "events.pollEvents":
                connection.sendall(ack(request, batch(next_sequence=20)))
                return True
            return False
        with peer(server_handler(action, requests=requests)) as server:
            mc = self.connect(server)
            mc.events.subscribe(events.CHAT_MESSAGE)
            mc.withContext().events.clearAll()
            mc.events.pollChatPosts()
            self.assertEqual(requests[-1]["params"]["cursor"]["sequence"], 20)
            self.assertEqual(mc.events.poll().sequence, 11)

    def test_poll_timeout_and_local_parameter_validation(self):
        requests = []
        with peer(server_handler(requests=requests)) as server:
            mc = self.connect(server)
            for timeout in (True, -1, float("inf"), "1"):
                with self.assertRaises((TypeError, ValueError)):
                    mc.events.poll(timeout)
            for limit in (0, 1001, True, 1.5):
                with self.assertRaises((TypeError, ValueError)):
                    mc.events.pollChatPosts(limit=limit)
            self.assertIsNone(mc.events.poll(.01))
            self.assertEqual(len(requests), 1)

    def test_concurrent_history_calls_serialize_request_and_cursor_commit(self):
        received, release = threading.Event(), threading.Event()
        seen = []
        def action(connection, request):
            if request["method"] != "events.pollEvents":
                return False
            position = request["params"]["cursor"]["sequence"]
            seen.append(position)
            if len(seen) == 1:
                received.set()
                if not release.wait(2):
                    raise AssertionError("history test did not release first page")
            connection.sendall(ack(request, batch([record(position + 1)], next_sequence=position + 1)))
            return True
        with peer(server_handler(action)) as server:
            mc = self.connect(server)
            facade = mc.withContext()
            _, first_done, first_errors = self.start(mc.events.pollChatPosts)
            self.assertTrue(received.wait(1))
            _, second_done, second_errors = self.start(lambda: facade.events.pollEvents(events.CHAT_MESSAGE))
            release.set()
            self.assertTrue(first_done.wait(1))
            self.assertTrue(second_done.wait(1))
            self.assertEqual((first_errors, second_errors, seen), ([], [], [10, 11]))

    def test_history_reads_inside_callback_do_not_consume_live_queue(self):
        messages = []
        def action(connection, request):
            if request["method"] == "events.subscribe":
                identity = request["params"]["subscriptionId"]
                connection.sendall(subscription_ack(request) + live(identity) + live(identity, 12, 2))
                return True
            if request["method"] == "events.pollEvents":
                connection.sendall(ack(request, batch([record(11), record(12)], next_sequence=12)))
                return True
            return False
        with peer(server_handler(action)) as server:
            mc = self.connect(server)
            def handler(event):
                messages.append(event.sequence)
                if len(messages) == 1:
                    self.assertEqual(len(mc.events.pollChatPosts()), 2)
                    self.assertEqual(len(mc.events.getRecent(events.CHAT_MESSAGE, 3)), 0)
                mc.events.stop()
            mc.events.subscribe(events.CHAT_MESSAGE, handler)
            mc.events.run()
            self.assertEqual(messages, [11])
            mc.events.run()
            self.assertEqual(messages, [11, 12])

    def test_subscription_limit_and_close_release_registry(self):
        requests = []
        metadata = event_hello()
        metadata["eventHistory"]["maxSubscriptions"] = 2
        with peer(server_handler(requests=requests, metadata=metadata)) as server:
            mc = self.connect(server)
            subscriptions = [mc.events.subscribe(events.CHAT_MESSAGE) for _ in range(2)]
            with self.assertRaises(errors.LimitExceededError):
                mc.events.subscribe(events.CHAT_MESSAGE)
            self.assertEqual(len(requests), 3)
            mc.close()
            self.assertFalse(mc.events._state.subscriptions)
            self.assertFalse(mc.events._state.queue)
            for subscription in subscriptions:
                subscription.unsubscribe()
            self.assertEqual(len(requests), 3)

    def test_handlerless_subscription_added_to_running_loop_reports_error(self):
        with peer(server_handler()) as server:
            mc = self.connect(server)
            mc.events.subscribe(events.CHAT_MESSAGE, lambda event: None)
            _, done, failures = self.start(mc.events.run)
            self.wait_consumer(mc)
            mc.events.subscribe(events.CHAT_MESSAGE)
            self.assertTrue(done.wait(1))
            self.assertEqual(len(failures), 1)
            self.assertIsInstance(failures[0], ValueError)

    def test_overflow_before_ack_is_rejected(self):
        def action(connection, request):
            if request["method"] != "events.subscribe":
                return False
            connection.sendall(encode_frame({"jsonrpc": "2.0", "method": "events.overflow", "params": {
                "subscriptionIds": [request["params"]["subscriptionId"]], "source": "server", "lostCount": 1}}) + subscription_ack(request))
            return True
        with peer(server_handler(action)) as server:
            mc = self.connect(server)
            with self.assertRaises(errors.ProtocolError):
                mc.events.subscribe(events.CHAT_MESSAGE)

    def test_malformed_hello_event_metadata_is_rejected(self):
        for mutate in (
            lambda value: value.update(world=str(uuid4())),
            lambda value: value.update(startSequence=-1),
            lambda value: value.update(maxLiveEvents=0),
            lambda value: value["retention"].update(maxBytes=True),
        ):
            metadata = event_hello()
            mutate(metadata["eventHistory"])
            with self.subTest(metadata=metadata), peer(server_handler(metadata=metadata)) as server:
                with self.assertRaises(errors.ProtocolError):
                    self.connect(server)

    def test_codec_rejects_malformed_event_frames(self):
        for mutate in (
            lambda p: p.update(deliverySequence=0),
            lambda p: p["event"].update(sequence=True),
            lambda p: p["event"]["data"].update(message="x" * 4097),
            lambda p: p["event"]["data"].update(cancelled=True),
            lambda p: p.update(subscriptionId="bad"),
        ):
            params = {"subscriptionId": str(uuid4()), "deliverySequence": 1, "event": record()}
            mutate(params)
            with self.subTest(params=params), self.assertRaises(CodecError):
                decode_event(encode_frame({"jsonrpc": "2.0", "method": "events.event", "params": params})[:-1])


if __name__ == "__main__":
    unittest.main()
