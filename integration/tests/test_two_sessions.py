"""T09 D01–D04 acceptance with two installed clients and real Paper state.

The explicit orchestrator supplies the server, independent observer and passive
wire capture. No test starts Paper, downloads artifacts or accepts EULA itself.
"""

from __future__ import annotations

from conftest import FacadeClient
from t09_support import PaperAcceptance


class TwoSessionAcceptance(PaperAcceptance):
    def positions(self, offset: int) -> list[list[int]]:
        y = self.world["maxYExclusive"] - 8
        return [[16384 + offset, y, 16384],
                [-16384 - offset, y, 16384],
                [-16384 - offset, y, -16384]]

    @staticmethod
    def request_events(trace: dict, session_id: str, rpc_id: int) -> list[dict]:
        return [event for event in trace["events"]
                if event["sessionId"] == session_id and event["requestId"] == rpc_id]

    def wire_pair(self, client: FacadeClient, rpc_id: int, method: str) -> dict:
        events = [event for event in self.wire(client)
                  if event["frame"].get("id") == rpc_id]
        requests = [event for event in events if event["direction"] == "request"]
        responses = [event for event in events if event["direction"] == "response"]
        self.assertEqual(len(requests), 1)
        self.assertEqual(len(responses), 1)
        request, response = requests[0], responses[0]
        self.assertEqual(request["frame"]["method"], method)
        self.assertEqual(request["connectionId"], response["connectionId"])
        self.assertLess(request["sequence"], response["sequence"])
        self.assertIn("result", response["frame"])
        self.assertNotIn("error", response["frame"])
        return {"request": request, "response": response}

    def both_ready(self, case_id: str, a: FacadeClient, b: FacadeClient) -> dict:
        self.assertNotEqual(a.context["pid"], b.context["pid"])
        self.assertNotEqual(a.context["sessionId"], b.context["sessionId"])
        self.assertEqual(a.context["world"], self.world)
        self.assertEqual(b.context["world"], self.world)
        self.assertIsNone(a.process.poll())
        self.assertIsNone(b.process.poll())
        status = self.observer.result(case_id, "status")
        self.assertTrue(status["controlEnabled"])
        sessions = {session["sessionId"]: session for session in status["sessions"]}
        for client in (a, b):
            session = sessions[client.context["sessionId"]]
            self.assertTrue(session["open"])
            self.assertTrue(session["ready"])
        return status

    def test_D01_overlapping_ready_sessions_have_independent_hello_ids(self) -> None:
        case_id = self.case()
        with FacadeClient(self.harness, "D01-A") as a, FacadeClient(self.harness, "D01-B") as b:
            # The worker control pipes keep both clients open until this shared
            # status barrier; starting B after A has closed cannot pass it.
            status = self.both_ready(case_id, a, b)
            handshakes = [self.wire_pair(client, 1, "system.hello") for client in (a, b)]
            connections = [pair["request"]["connectionId"] for pair in handshakes]
            self.assertNotEqual(*connections)
            for client, pair in zip((a, b), handshakes):
                self.assertEqual(pair["response"]["frame"]["result"]["sessionId"],
                                 client.context["sessionId"])
            self.record("D01", case_id, paperPid=self.paper.process.pid,
                        clients=[a.context, b.context], simultaneousReady=status,
                        handshakes=handshakes)

    def test_D02_same_request_id_is_correlated_per_live_session(self) -> None:
        case_id, positions = self.case(), self.positions(512)
        with self.prepared(case_id, positions[:2]):
            with FacadeClient(self.harness, "D02-A") as a, FacadeClient(self.harness, "D02-B") as b:
                ready = self.both_ready(case_id, a, b)
                session = a.context["sessionId"]
                self.observer.result(case_id, "gateArm", session, 2)
                self.observer.result(case_id, "track", b.context["sessionId"], 2)
                # Dispatch both public calls before awaiting either response.
                command_a = a.set(positions[0], "COBBLESTONE")
                command_b = b.set(positions[1], "STONE", route="blocks")
                gated = self.observer.await_value(
                    case_id, "gateStatus", (session, 2),
                    lambda value: value["state"] == "GATED")
                self.assertTrue(gated["sessionOpen"])
                self.assertEqual(gated["queuedRequests"], 1)
                before = self.read(case_id, positions[0], "minecraft:air")
                a.assert_pending()
                returned_b = b.success(command_b)
                applied_b = self.assert_applied(case_id, b, 2, positions[1], "minecraft:stone")
                # B has completed while A is still held. Advance only by an
                # observed tick barrier, never by a guessed sleep interval.
                progressed = self.observer.await_value(
                    case_id, "status", (),
                    lambda _: self.observer.envelopes[-1]["tick"] > before["tick"])
                self.read(case_id, positions[0], "minecraft:air")
                a.assert_pending()
                pending_trace = self.trace(case_id)
                phases = [event["phase"] for event in self.request_events(pending_trace, session, 2)]
                self.assertIn("QUEUED", phases)
                self.assertNotIn("APPLY_BEGIN", phases)
                self.assertNotIn("APPLY_DONE", phases)
                self.assertNotIn("ACK_ENQUEUED", phases)
                released = self.observer.result(case_id, "gateRelease", session, 2)
                self.assertEqual(released["state"], "RELEASED")
                returned_a = a.success(command_a)
                applied_a = self.assert_applied(case_id, a, 2, positions[0], "minecraft:cobblestone")
                pairs = [self.wire_pair(client, 2, "blocks.set") for client in (a, b)]
                self.assertNotEqual(pairs[0]["request"]["connectionId"],
                                    pairs[1]["request"]["connectionId"])
                self.record("D02", case_id, clients=[a.context, b.context],
                            simultaneousReady=ready, gated=gated, progressStatus=progressed,
                            pendingTrace=pending_trace, released=released,
                            returns=[returned_a, returned_b], applications=[applied_a, applied_b],
                            requestPairs=pairs)

    def test_D03_shared_position_follows_actual_apply_sequence(self) -> None:
        case_id, position = self.case(), self.positions(576)[0]
        with self.prepared(case_id, [position]):
            with FacadeClient(self.harness, "D03-A") as a, FacadeClient(self.harness, "D03-B") as b:
                ready = self.both_ready(case_id, a, b)
                session = a.context["sessionId"]
                self.observer.result(case_id, "gateArm", session, 2)
                self.observer.result(case_id, "track", b.context["sessionId"], 2)
                command_a = a.set(position, "COBBLESTONE")
                command_b = b.set(position, "STONE")
                gated = self.observer.await_value(
                    case_id, "gateStatus", (session, 2),
                    lambda value: value["state"] == "GATED")
                a.assert_pending()
                returned_b = b.success(command_b)
                applied_b = self.assert_applied(case_id, b, 2, position, "minecraft:stone")
                a.assert_pending()
                self.observer.result(case_id, "gateRelease", session, 2)
                returned_a = a.success(command_a)
                applied_a = self.assert_applied(case_id, a, 2, position, "minecraft:cobblestone")
                trace = self.trace(case_id)
                actual_applications = []
                for client, key in ((a, "minecraft:cobblestone"), (b, "minecraft:stone")):
                    done = [event for event in self.request_events(trace, client.context["sessionId"], 2)
                            if event["phase"] == "APPLY_DONE"]
                    self.assertEqual(len(done), 1)
                    actual_applications.append({"sessionId": client.context["sessionId"],
                                                "key": key,
                                                "applySequence": done[0]["applySequence"]})
                self.assertNotEqual(actual_applications[0]["applySequence"],
                                    actual_applications[1]["applySequence"])
                # Derive the expected final value from execution evidence,
                # rather than choosing a winner from the clients' names.
                last = max(actual_applications, key=lambda item: item["applySequence"])
                final = self.read(case_id, position, last["key"])
                pairs = [self.wire_pair(client, 2, "blocks.set") for client in (a, b)]
                self.assertNotEqual(pairs[0]["request"]["connectionId"],
                                    pairs[1]["request"]["connectionId"])
                self.record("D03", case_id, clients=[a.context, b.context],
                            simultaneousReady=ready, gated=gated,
                            returns=[returned_a, returned_b], applications=[applied_a, applied_b],
                            actualApplyOrder=sorted(actual_applications,
                                                    key=lambda item: item["applySequence"]),
                            final=final, trace=trace, requestPairs=pairs)

    def test_D04_disconnect_cancels_A_without_interrupting_ready_B(self) -> None:
        case_id, positions = self.case(), self.positions(640)
        with self.prepared(case_id, positions):
            with FacadeClient(self.harness, "D04-A") as a, FacadeClient(self.harness, "D04-B") as b:
                ready = self.both_ready(case_id, a, b)
                session = a.context["sessionId"]
                self.observer.result(case_id, "gateArm", session, 2)
                self.observer.result(case_id, "track", b.context["sessionId"], 2)
                command_a = a.set(positions[0], "COBBLESTONE")
                self.observer.await_value(case_id, "gateStatus", (session, 2),
                                          lambda value: value["state"] == "GATED")
                a.assert_pending()
                before_close_b = b.success(b.set(positions[1], "STONE"))
                applied_before = self.assert_applied(case_id, b, 2, positions[1], "minecraft:stone")
                self.read(case_id, positions[0], "minecraft:air")
                completion = a.close()
                failures = [event for event in completion if event.get("commandId") == command_a]
                self.assertEqual(len(failures), 1)
                self.assertFalse(failures[0]["ok"])
                # A transport interruption cannot tell the public client that
                # the server's unexecuted queue entry was definitely cancelled.
                self.assertEqual(failures[0]["outcome"], "unknown")
                cancelled = self.observer.await_value(
                    case_id, "gateStatus", (session, 2),
                    lambda value: (value["state"] == "CANCELLED"
                                   and value["sessionOpen"] is False
                                   and value["queuedRequests"] == 0))
                released = self.observer.result(case_id, "gateRelease", session, 2)
                self.assertEqual(released["state"], "CANCELLED")
                self.assertFalse(released["sessionOpen"])
                status = self.observer.result(case_id, "status")
                live_b = next(item for item in status["sessions"]
                              if item["sessionId"] == b.context["sessionId"])
                self.assertTrue(live_b["ready"])
                self.assertTrue(live_b["open"])
                self.observer.result(case_id, "track", b.context["sessionId"], 3)
                after_close_b = b.success(b.set(positions[2], "COBBLESTONE", route="blocks"))
                applied_after = self.assert_applied(case_id, b, 3, positions[2], "minecraft:cobblestone")
                untouched = self.read(case_id, positions[0], "minecraft:air")
                self.read(case_id, positions[1], "minecraft:stone")
                trace = self.trace(case_id)
                a_events = self.request_events(trace, session, 2)
                phases = [event["phase"] for event in a_events]
                self.assertIn("QUEUED", phases)
                self.assertEqual(phases.count("CANCELLED"), 1)
                self.assertNotIn("APPLY_BEGIN", phases)
                self.assertNotIn("APPLY_DONE", phases)
                self.assertNotIn("ACK_ENQUEUED", phases)
                self.assertNotIn("ERROR", phases)
                self.assertEqual(next(event for event in a_events if event["phase"] == "CANCELLED")
                                 ["outcome"], "not-applied")
                b_pairs = [self.wire_pair(b, rpc_id, "blocks.set") for rpc_id in (2, 3)]
                self.assertEqual(b_pairs[0]["request"]["connectionId"],
                                 b_pairs[1]["request"]["connectionId"])
                wire_a = self.wire(a)
                self.assertEqual(sum(event["direction"] == "request"
                                     and event["frame"].get("id") == 2 for event in wire_a), 1)
                self.assertFalse(any(event["direction"] == "response"
                                     and event["frame"].get("id") == 2 for event in wire_a))
                self.record("D04", case_id, variant="public-close-during-gated-request",
                            clients=[a.context, b.context], simultaneousReady=ready,
                            clientClose=completion, cancelled=cancelled, releaseAfterClose=released,
                            survivingSession=live_b, untouched=untouched,
                            returnsB=[before_close_b, after_close_b],
                            applicationsB=[applied_before, applied_after],
                            trace=trace, wireA=wire_a, requestPairsB=b_pairs)
