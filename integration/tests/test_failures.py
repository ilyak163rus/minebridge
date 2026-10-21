"""T10 F01/F02/F03/F05 with explicit faults and installed public clients.

Paper mutations are checked only through the independent Java observer. F05
uses a synthetic controlled TCP peer and makes no claim about Paper state.
The orchestrator owns F04 because stopping/restarting Paper changes its fixture.
"""

from __future__ import annotations

import time

from conftest import FacadeClient
from fault_proxy import ControlledPeer, FaultProxy
from t09_support import PaperAcceptance


class FaultAcceptance(PaperAcceptance):
    def positions(self, offset: int = 0) -> list[list[int]]:
        y = self.world["maxYExclusive"] - 8
        return [[49152 + offset, y, 49152], [-49152 - offset, y, 49152]]

    @staticmethod
    def request_events(trace: dict, session: str, rpc_id: int = 2) -> list[dict]:
        return [event for event in trace["events"]
                if event["sessionId"] == session and event["requestId"] == rpc_id]

    def expect_error(self, client: FacadeClient, command: str, error: str,
                     code: str, outcome: str, *, timeout: float = 10) -> dict:
        result = client.response(timeout=timeout)
        self.assertEqual(result, {"type": "result", "commandId": command, "ok": False,
                                  "error": error, "code": code, "outcome": outcome})
        return result

    def closed_write(self, client: FacadeClient, position: list[int]) -> dict:
        # This is an explicit second API call by the test, not a retry. It must
        # fail locally without producing another frame or opening a connection.
        command = client.set(position, "STONE")
        return self.expect_error(client, command, "ConnectionError", "CONNECTION_LOST", "not-applied")

    def one_application(self, case_id: str, client: FacadeClient,
                        position: list[int], key: str) -> dict:
        observed = self.read(case_id, position, key)
        trace = self.trace(case_id)
        events = self.request_events(trace, client.context["sessionId"])
        self.assertEqual([event["phase"] for event in events],
                         ["QUEUED", "APPLY_BEGIN", "APPLY_DONE", "ACK_ENQUEUED"])
        for event in events[1:]:
            self.assertTrue(event["primaryThread"])
            self.assertEqual(event["threadId"], observed["threadId"])
            self.assertEqual(event["caseId"], case_id)
            self.assertEqual(event["worldUuid"], self.world["uuid"])
            self.assertEqual([event["x"], event["y"], event["z"]], position)
        self.assertLess(events[1]["sequence"], events[2]["sequence"])
        self.assertLess(events[2]["sequence"], events[3]["sequence"])
        self.assertEqual(events[1]["applySequence"], events[2]["applySequence"])
        self.assertEqual(events[2]["applySequence"], events[3]["applySequence"])
        return {"snapshot": observed, "events": events}

    def one_proxy_request(self, proxy: FaultProxy, *, delivery: str | None = None) -> dict:
        evidence = proxy.snapshot()
        self.assertEqual(evidence["errors"], [])
        self.assertEqual(len(evidence["connections"]), 1)
        connection = evidence["connections"][0]
        self.assertTrue(connection["closed"])
        self.assertEqual(connection["mutationRequests"], 1)
        requests = [event for event in evidence["events"] if event["direction"] == "request"]
        self.assertEqual([event["frame"]["method"] for event in requests], ["system.hello", "blocks.set"])
        self.assertEqual([event["frame"]["id"] for event in requests], [1, 2])
        self.assertNotIn("token", requests[0]["frame"]["params"])
        if delivery is not None:
            self.assertEqual(evidence["target"]["delivery"], delivery)
        return evidence

    def test_F01_applied_reply_is_held_until_public_timeout_without_retry(self) -> None:
        case_id, position = self.case(), self.positions()[0]
        with self.prepared(case_id, [position]):
            evidence_file = self.harness.artifacts / "F01-proxy.json"
            with FaultProxy(token=self.harness.token, evidence=evidence_file) as proxy:
                with FacadeClient(self.harness, "F01-client", port=proxy.port, timeout=2.0) as client:
                    self.observer.result(case_id, "track", client.context["sessionId"], 2)
                    command = client.set(position, "COBBLESTONE")
                    captured = proxy.await_captured()
                    self.assertEqual(captured["frame"],
                                     {"jsonrpc": "2.0", "id": 2, "result": {"applied": True}})
                    self.assertEqual(captured["delivery"], "held")
                    applied = self.one_application(case_id, client, position, "minecraft:cobblestone")
                    failure = self.expect_error(client, command, "OperationTimeoutError", "TIMEOUT", "unknown")
                    self.assertTrue(proxy.wait_closed())
                    closed = self.closed_write(client, position)
                    # Closing the fixture cannot make a timeout undo an applied
                    # write. Re-read after the real client deadline as well.
                    after = self.read(case_id, position, "minecraft:cobblestone")
                    capture = self.one_proxy_request(proxy, delivery="closed-before-release")
                    self.record("F01", case_id, client=client.context, held=captured,
                                application=applied, failure=failure, closedWrite=closed,
                                afterTimeout=after, proxy=capture,
                                proxyEvidence=str(evidence_file), automaticRetries=0)

    def test_F02_close_gated_A_cancels_server_queue_while_B_continues(self) -> None:
        case_id, positions = self.case(), self.positions(64)
        with self.prepared(case_id, positions):
            with FacadeClient(self.harness, "F02-A") as a, FacadeClient(self.harness, "F02-B") as b:
                self.assertNotEqual(a.context["sessionId"], b.context["sessionId"])
                self.assertNotEqual(a.context["pid"], b.context["pid"])
                session = a.context["sessionId"]
                self.observer.result(case_id, "gateArm", session, 2)
                self.observer.result(case_id, "track", b.context["sessionId"], 2)
                command = a.set(positions[0], "COBBLESTONE")
                gated = self.observer.await_value(case_id, "gateStatus", (session, 2),
                                                  lambda value: value["state"] == "GATED")
                a.assert_pending()
                before = self.read(case_id, positions[0], "minecraft:air")
                completion = a.close()
                errors = [value for value in completion if value.get("commandId") == command]
                self.assertEqual(len(errors), 1)
                self.assertFalse(errors[0]["ok"])
                self.assertEqual(errors[0]["outcome"], "unknown")
                cancelled = self.observer.await_value(
                    case_id, "gateStatus", (session, 2),
                    lambda value: (value["state"] == "CANCELLED" and not value["sessionOpen"]
                                   and value["queuedRequests"] == 0))
                released = self.observer.result(case_id, "gateRelease", session, 2)
                self.assertEqual(released["state"], "CANCELLED")
                self.assertFalse(released["sessionOpen"])
                succeeded_b = b.success(b.set(positions[1], "STONE"))
                applied_b = self.assert_applied(case_id, b, 2, positions[1], "minecraft:stone")
                untouched = self.read(case_id, positions[0], "minecraft:air")
                self.assertGreater(untouched["tick"], before["tick"])
                trace = self.trace(case_id)
                a_events = self.request_events(trace, session)
                self.assertEqual([value["phase"] for value in a_events], ["QUEUED", "CANCELLED"])
                self.assertEqual(a_events[-1]["outcome"], "not-applied")
                wire = self.wire(a)
                self.assertEqual(sum(value["direction"] == "request"
                                     and value["frame"].get("id") == 2 for value in wire), 1)
                self.assertFalse(any(value["direction"] == "response"
                                     and value["frame"].get("id") == 2 for value in wire))
                self.record("F02", case_id, clients=[a.context, b.context], gated=gated,
                            close=completion, serverCancelled=cancelled, released=released,
                            survivorReturn=succeeded_b, survivorApplication=applied_b,
                            untouched=untouched, cancelledEvents=a_events, wireA=wire)

    def test_F03_drop_after_apply_before_ACK_preserves_unknown_and_no_replay(self) -> None:
        case_id, positions = self.case(), self.positions(128)
        with self.prepared(case_id, positions):
            evidence_file = self.harness.artifacts / "F03-proxy.json"
            with FaultProxy(token=self.harness.token, evidence=evidence_file) as proxy:
                with FacadeClient(self.harness, "F03-interrupted", port=proxy.port, timeout=10.0) as a:
                    session = a.context["sessionId"]
                    self.observer.result(case_id, "track", session, 2)
                    command = a.set(positions[0], "COBBLESTONE")
                    captured = proxy.await_captured()
                    self.assertEqual(captured["frame"],
                                     {"jsonrpc": "2.0", "id": 2, "result": {"applied": True}})
                    self.assertEqual(captured["delivery"], "held")
                    applied = self.one_application(case_id, a, positions[0], "minecraft:cobblestone")
                    a.assert_pending()
                    proxy.drop()
                    failure = self.expect_error(a, command, "ConnectionError", "CONNECTION_LOST", "unknown")
                    self.assertTrue(proxy.wait_closed())
                    closed = self.closed_write(a, positions[0])
                    capture = self.one_proxy_request(proxy, delivery="dropped")
                # A fresh public create is explicit. Before any fresh write,
                # verify the interrupted operation was neither cancelled nor
                # replayed by the new object.
                with FacadeClient(self.harness, "F03-fresh") as fresh:
                    self.assertNotEqual(fresh.context["sessionId"], session)
                    persisted = self.read(case_id, positions[0], "minecraft:cobblestone")
                    before_write = self.trace(case_id)
                    self.assertEqual(sum(event["phase"] == "APPLY_BEGIN"
                                         for event in self.request_events(before_write, session)), 1)
                    self.assertFalse(any(event["sessionId"] == fresh.context["sessionId"]
                                         and event["phase"] == "APPLY_BEGIN"
                                         for event in before_write["events"]))
                    self.observer.result(case_id, "track", fresh.context["sessionId"], 2)
                    fresh_return = fresh.success(fresh.set(positions[1], "STONE"))
                    fresh_application = self.assert_applied(case_id, fresh, 2, positions[1], "minecraft:stone")
                    self.record("F03", case_id, interruptedSession=session, held=captured,
                                application=applied, failure=failure, closedWrite=closed,
                                proxy=capture, proxyEvidence=str(evidence_file),
                                freshClient=fresh.context, persisted=persisted,
                                beforeFreshWrite=before_write, freshReturn=fresh_return,
                                freshApplication=fresh_application, automaticReplays=0)

    def test_F05_controlled_peer_replies_close_client_without_second_request(self) -> None:
        case_id = self.case()
        variants = []
        for mode in ("wrong-id", "malformed-false", "malformed-type", "late"):
            with self.subTest(mode=mode):
                evidence_file = self.harness.artifacts / ("F05-" + mode + "-peer.json")
                with ControlledPeer(token=self.harness.token, evidence=evidence_file, mode=mode) as peer:
                    with FacadeClient(self.harness, "F05-" + mode, port=peer.port, timeout=1.0) as client:
                        self.assertEqual(client.context["world"]["name"], "controlled-peer")
                        self.assertNotEqual(client.context["world"]["uuid"], self.world["uuid"])
                        command = client.set([0, 64, 0], "COBBLESTONE")
                        captured = peer.await_captured()
                        if mode == "late":
                            failure = self.expect_error(client, command, "OperationTimeoutError", "TIMEOUT", "unknown")
                            self.assertTrue(peer.wait_downstream_eof())
                            released_after_failure_ns = time.monotonic_ns()
                            peer.release()
                            self.assertTrue(peer.await_released())
                        else:
                            failure = self.expect_error(client, command, "ProtocolError", "PROTOCOL_ERROR", "unknown")
                            released_after_failure_ns = None
                        self.assertTrue(peer.wait_closed())
                        closed = self.closed_write(client, [0, 64, 0])
                        evidence = self.one_proxy_request(peer)
                        self.assertTrue(evidence["connections"][0]["downstreamEof"])
                        if mode == "late":
                            self.assertIn(evidence["target"]["delivery"],
                                          ("late-send-after-client-close", "late-send-rejected-after-client-close"))
                            self.assertGreaterEqual(evidence["target"]["deliveryMonotonicNs"],
                                                    released_after_failure_ns)
                        variants.append({"mode": mode, "client": client.context, "captured": captured,
                                         "failure": failure, "closedWrite": closed,
                                         "releasedAfterClientFailureNs": released_after_failure_ns,
                                         "peer": evidence, "evidenceFile": str(evidence_file)})
        self.record("F05", case_id, fixture="synthetic-controlled-peer-no-Paper-state-claim",
                    variants=variants, automaticRetries=0)
