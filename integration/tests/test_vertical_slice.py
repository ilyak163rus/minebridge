"""T09 V01–V07: installed public Python API against the pinned real Paper.

The runner supplies a fresh server, an independent observer and a wire tap.
Discovery alone does not start a server or accept the Minecraft EULA.
"""

from __future__ import annotations

from conftest import FacadeClient
from t09_support import PaperAcceptance


class VerticalSliceAcceptance(PaperAcceptance):
    def test_01_v01_create_completes_hello_without_online_players(self) -> None:
        case_id = self.case()
        no_players = self.assert_no_players()
        with FacadeClient(self.harness, "v01-create") as client:
            context = client.context
            self.assertEqual(context["protocol"], {"major": 1, "minor": 0})
            self.assertEqual(context["world"], self.world)
            self.assertEqual(context["coordinates"], "absolute")
            self.assertEqual(context["chunkPolicy"], "loaded-only")
            self.assertIs(context["applyPhysics"], True)
            self.assertEqual(context["capabilities"], ["blocks.set"])
            self.assertEqual(context["limits"], {
                "maxFrameBytes": 65536, "maxJsonDepth": 16, "maxSessions": 8,
                "maxQueuedRequests": 8, "maxOutputFrames": 8,
                "handshakeTimeoutSeconds": 5, "frameAssemblyTimeoutSeconds": 5,
                "writeTimeoutSeconds": 5, "maxOperationsPerTick": 32,
                "maxOperationsPerSessionPerTick": 4, "executorBudgetMillis": 2,
            })
            status = self.observer.result(case_id, "status")
            matching = [session for session in status["sessions"]
                        if session["sessionId"] == context["sessionId"]]
            self.assertEqual(len(matching), 1)
            self.assertTrue(matching[0]["ready"])
            self.assertTrue(matching[0]["open"])
            self.assertEqual(matching[0]["queuedRequests"], 0)
            wire = self.wire(client)
            requests = [event for event in wire if event["direction"] == "request"]
            responses = [event for event in wire if event["direction"] == "response"]
            self.assertEqual(len(requests), 1)
            self.assertEqual(len(responses), 1)
            hello, reply = requests[0]["frame"], responses[0]["frame"]
            self.assertEqual(hello["id"], 1)
            self.assertEqual(hello["method"], "system.hello")
            self.assertEqual(hello["params"]["protocol"], {"major": 1, "minor": 0})
            self.assertIsNone(hello["params"]["world"])
            self.assertEqual(hello["params"]["coordinates"], "absolute")
            self.assertNotIn("token", hello["params"])
            self.assertEqual(reply["id"], 1)
            self.assertEqual(reply["result"]["sessionId"], context["sessionId"])
            for key in ("protocol", "world", "coordinates", "chunkPolicy",
                        "applyPhysics", "capabilities", "limits"):
                self.assertEqual(reply["result"][key], context[key])
            self.assertLess(requests[0]["sequence"], responses[0]["sequence"])
            self.record("V01", case_id, context=context, noPlayers=no_players,
                        tokenSource="MINEBRIDGE_TOKEN environment; create omitted token",
                        status=status, wire=wire)

    def test_02_v02_root_accepts_four_supported_block_forms(self) -> None:
        case_id = self.case()
        y = self.world["maxYExclusive"] - 8
        positions = [[16384 + offset, y, 16384] for offset in range(4)]
        forms = [("numeric", 4), ("legacy", 4),
                 ("constant", "COBBLESTONE"), ("modern", "minecraft:cobblestone")]
        operations = []
        with self.prepared(case_id, positions):
            with FacadeClient(self.harness, "v02-root-forms") as client:
                for request_id in range(2, 6):
                    self.observer.result(case_id, "track", client.context["sessionId"], request_id)
                for request_id, position, (form, material) in zip(range(2, 6), positions, forms):
                    returned = client.success(client.set(position, material, form=form))
                    applied = self.assert_applied(case_id, client, request_id, position,
                                                  "minecraft:cobblestone")
                    operations.append({"form": form, "material": material,
                                       "publicResult": returned, **applied})
                requests = [event["frame"] for event in self.wire(client)
                            if event["direction"] == "request"]
                self.assertEqual([request["id"] for request in requests], [1, 2, 3, 4, 5])
                self.assertEqual([request["method"] for request in requests],
                                 ["system.hello"] + ["blocks.set"] * 4)
                self.record("V02", case_id, context=client.context, operations=operations,
                            wire=self.wire(client))

    def test_03_v03_namespace_has_same_wire_contract_and_no_hidden_reads(self) -> None:
        case_id = self.case()
        y = self.world["maxYExclusive"] - 8
        positions = [[-16384 - offset, y, 16384] for offset in range(4)]
        forms = [("numeric", 4), ("legacy", 4),
                 ("constant", "COBBLESTONE"), ("modern", "minecraft:cobblestone")]
        operations = []
        with self.prepared(case_id, positions):
            with FacadeClient(self.harness, "v03-blocks-forms") as client:
                for request_id in range(2, 8):
                    self.observer.result(case_id, "track", client.context["sessionId"], request_id)
                # An actual root call gives this independent case a wire reference.
                root_result = client.success(client.set(positions[0], "COBBLESTONE"))
                root = self.assert_applied(case_id, client, 2, positions[0],
                                          "minecraft:cobblestone")
                for request_id, position, (form, material) in zip(range(3, 7), positions, forms):
                    returned = client.success(client.set(position, material, route="blocks", form=form))
                    applied = self.assert_applied(case_id, client, request_id, position,
                                                  "minecraft:cobblestone")
                    expected = {"world": self.world["name"], "position": position,
                                "block": {"key": "minecraft:cobblestone", "states": {}}}
                    self.assertEqual(applied["request"]["frame"]["params"], expected)
                    if request_id == 3:
                        self.assertEqual(applied["request"]["frame"]["params"],
                                         root["request"]["frame"]["params"])
                    operations.append({"form": form, "publicResult": returned, **applied})
                repeated_result = client.success(client.set(positions[-1], "COBBLESTONE", route="blocks"))
                repeated = self.assert_applied(case_id, client, 7, positions[-1],
                                              "minecraft:cobblestone")
                self.assertEqual(repeated["request"]["frame"]["params"],
                                 operations[-1]["request"]["frame"]["params"])
                wire = self.wire(client)
                requests = [event["frame"] for event in wire if event["direction"] == "request"]
                responses = [event["frame"] for event in wire if event["direction"] == "response"]
                self.assertEqual([request["id"] for request in requests], list(range(1, 8)))
                self.assertEqual([request["method"] for request in requests],
                                 ["system.hello"] + ["blocks.set"] * 6)
                self.assertEqual([response["id"] for response in responses], list(range(1, 8)))
                self.record("V03", case_id, context=client.context,
                            rootReference={"publicResult": root_result, **root},
                            operations=operations,
                            repeated={"publicResult": repeated_result, **repeated}, wire=wire)

    def test_04_v04_floor_and_actual_world_height_boundaries(self) -> None:
        case_id = self.case()
        y = self.world["maxYExclusive"] - 8
        negative, zero = [-1, y, 16384], [0, y, 16384]
        positive = [16384, y, 16384]
        bottom = [-16384, self.world["minY"], 16384]
        top = [16385, self.world["maxYExclusive"] - 1, 16384]
        below_rejected = [16386, self.world["maxYExclusive"] - 1, 16384]
        positions = [negative, zero, positive, bottom, top, below_rejected]
        valid = [([-0.2, y, 16384], negative),
                 ([16384.8, y + 0.75, 16384.4], positive),
                 (bottom, bottom), (top, top)]
        operations = []
        with self.prepared(case_id, positions):
            with FacadeClient(self.harness, "v04-coordinate-boundaries") as client:
                for request_id in range(2, 7):
                    self.observer.result(case_id, "track", client.context["sessionId"], request_id)
                for request_id, (supplied, normalized) in zip(range(2, 6), valid):
                    returned = client.success(client.set(supplied, "COBBLESTONE"))
                    applied = self.assert_applied(case_id, client, request_id, normalized,
                                                  "minecraft:cobblestone")
                    self.assertEqual(applied["request"]["frame"]["params"]["position"], normalized)
                    operations.append({"inputPosition": supplied, "publicResult": returned, **applied})
                zero_unchanged = self.read(case_id, zero, "minecraft:air")
                rejected_position = [below_rejected[0], self.world["maxYExclusive"], below_rejected[2]]
                command_id = client.set(rejected_position, "COBBLESTONE")
                failed = client.response()
                self.assertEqual(failed["type"], "result")
                self.assertEqual(failed["commandId"], command_id)
                self.assertIs(failed["ok"], False)
                self.assertEqual(failed["error"], "CoordinateOutOfBoundsError")
                self.assertEqual(failed["code"], "COORDINATE_OUT_OF_BOUNDS")
                self.assertEqual(failed["outcome"], "not-applied")
                trace = self.trace(case_id)
                rejected_events = [event for event in trace["events"]
                                   if event["caseId"] == case_id
                                   and event["sessionId"] == client.context["sessionId"]
                                   and event["requestId"] == 6]
                self.assertEqual([event["phase"] for event in rejected_events], ["QUEUED", "ERROR"])
                self.assertEqual(rejected_events[-1]["errorCode"], "COORDINATE_OUT_OF_BOUNDS")
                self.assertEqual(rejected_events[-1]["outcome"], "not-applied")
                unchanged = [self.read(case_id, position, "minecraft:cobblestone")
                             for _, position in valid]
                unchanged.extend([self.read(case_id, zero, "minecraft:air"),
                                  self.read(case_id, below_rejected, "minecraft:air")])
                wire = self.wire(client)
                rejected_requests = [event["frame"] for event in wire
                                     if event["direction"] == "request" and event["frame"]["id"] == 6]
                rejected_responses = [event["frame"] for event in wire
                                      if event["direction"] == "response" and event["frame"]["id"] == 6]
                self.assertEqual(len(rejected_requests), 1)
                self.assertEqual(rejected_requests[0]["params"]["position"], rejected_position)
                self.assertEqual(len(rejected_responses), 1)
                self.assertEqual(rejected_responses[0]["error"]["data"],
                                 {"code": "COORDINATE_OUT_OF_BOUNDS", "outcome": "not-applied"})
                self.record("V04", case_id, context=client.context, operations=operations,
                            zeroUnchanged=zero_unchanged, rejection=failed,
                            rejectedPosition=rejected_position, rejectedEvents=rejected_events,
                            unchangedAfterRejection=unchanged, wire=wire)

    def test_05_v05_ack_follows_apply_and_gate_does_not_block_ticks(self) -> None:
        case_id = self.case()
        position = [16448, self.world["maxYExclusive"] - 8, 16384]
        with self.prepared(case_id, [position]):
            with FacadeClient(self.harness, "v05-ack-gate") as client:
                session = client.context["sessionId"]
                self.observer.result(case_id, "gateArm", session, 2)
                command_id = client.set(position, "COBBLESTONE")
                gated = self.observer.await_value(case_id, "gateStatus", (session, 2),
                                                  lambda value: value["state"] == "GATED")
                self.assertTrue(gated["sessionOpen"])
                self.assertEqual(gated["queuedRequests"], 1)
                before = self.read(case_id, position, "minecraft:air")
                client.assert_pending()
                self.observer.await_value(case_id, "status", (),
                                          lambda _: self.observer.envelopes[-1]["tick"] > before["tick"])
                advanced = self.observer.envelopes[-1]
                still_gated = self.observer.result(case_id, "gateStatus", session, 2)
                self.assertEqual(still_gated["state"], "GATED")
                self.read(case_id, position, "minecraft:air")
                client.assert_pending()
                pending_trace = self.trace(case_id)
                pending_events = [event for event in pending_trace["events"]
                                  if event["caseId"] == case_id and event["sessionId"] == session
                                  and event["requestId"] == 2]
                self.assertEqual([event["phase"] for event in pending_events], ["QUEUED"])
                pending_wire = self.wire(client)
                self.assertEqual(sum(event["direction"] == "request"
                                     and event["frame"].get("id") == 2 for event in pending_wire), 1)
                self.assertFalse(any(event["direction"] == "response"
                                     and event["frame"].get("id") == 2 for event in pending_wire))
                release = self.observer.result(case_id, "gateRelease", session, 2)
                self.assertEqual(release["state"], "RELEASED")
                returned = client.success(command_id)
                applied = self.assert_applied(case_id, client, 2, position, "minecraft:cobblestone")
                self.assertGreater(advanced["tick"], before["tick"])
                self.record("V05", case_id, context=client.context, gated=gated,
                            beforeRelease=before, tickAdvanced=advanced, pendingEvents=pending_events,
                            pendingWire=pending_wire, release=release, publicResult=returned, **applied)

    def test_06_v06_sequential_public_writes_preserve_apply_order(self) -> None:
        case_id = self.case()
        position = [-16448, self.world["maxYExclusive"] - 8, 16384]
        with self.prepared(case_id, [position]):
            with FacadeClient(self.harness, "v06-sequential-writes") as client:
                for request_id in (2, 3):
                    self.observer.result(case_id, "track", client.context["sessionId"], request_id)
                first_result = client.success(client.set(position, "STONE"))
                first = self.assert_applied(case_id, client, 2, position, "minecraft:stone")
                first_wire = self.wire(client)
                self.assertFalse(any(event["direction"] == "request" and event["frame"].get("id") == 3
                                     for event in first_wire))
                second_result = client.success(client.set(position, "COBBLESTONE"))
                second = self.assert_applied(case_id, client, 3, position, "minecraft:cobblestone")
                first_done = next(event for event in first["events"] if event["phase"] == "APPLY_DONE")
                second_done = next(event for event in second["events"] if event["phase"] == "APPLY_DONE")
                self.assertLess(first_done["applySequence"], second_done["applySequence"])
                self.assertLess(first_done["sequence"], second_done["sequence"])
                wire = self.wire(client)
                first_reply = next(event for event in wire
                                   if event["direction"] == "response" and event["frame"]["id"] == 2)
                second_request = next(event for event in wire
                                      if event["direction"] == "request" and event["frame"]["id"] == 3)
                self.assertLess(first_reply["sequence"], second_request["sequence"])
                self.record("V06", case_id, context=client.context,
                            first={"publicResult": first_result, **first},
                            second={"publicResult": second_result, **second}, wire=wire)

    def test_07_v07_close_is_idempotent_and_new_create_has_new_session(self) -> None:
        case_id = self.case()
        y = self.world["maxYExclusive"] - 8
        completed_position, new_position = [16512, y, 16384], [16513, y, 16384]
        with self.prepared(case_id, [completed_position, new_position]):
            with FacadeClient(self.harness, "v07-close-and-recreate") as client:
                old_context = dict(client.context)
                self.observer.result(case_id, "track", old_context["sessionId"], 2)
                completed_result = client.success(client.set(completed_position, "COBBLESTONE"))
                completed = self.assert_applied(case_id, client, 2, completed_position,
                                               "minecraft:cobblestone")
                old_wire = self.wire(client)
                reopened = client.reopen(completed_position)
                self.assertEqual(reopened["type"], "reopened")
                self.assertEqual(reopened["oldSessionId"], old_context["sessionId"])
                self.assertIs(reopened["oldClosed"], True)
                self.assertEqual(reopened["closedWrite"], {
                    "error": "ConnectionError", "code": "CONNECTION_LOST", "outcome": "not-applied"})
                self.assertEqual(client.context["pid"], old_context["pid"])
                self.assertNotEqual(client.context["sessionId"], old_context["sessionId"])
                self.assertEqual(client.context["world"], old_context["world"])

                def old_removed_and_new_ready(status: dict) -> bool:
                    sessions = status["sessions"]
                    return (not any(session["sessionId"] == old_context["sessionId"] for session in sessions)
                            and any(session["sessionId"] == client.context["sessionId"]
                                    and session["ready"] and session["open"]
                                    and session["queuedRequests"] == 0 for session in sessions))

                active = self.observer.await_value(case_id, "status", (), old_removed_and_new_ready)
                self.assertEqual(self.harness.wiretap.frames_for_session(old_context["sessionId"]), old_wire)
                persisted = self.read(case_id, completed_position, "minecraft:cobblestone")
                self.read(case_id, new_position, "minecraft:air")
                self.observer.result(case_id, "track", client.context["sessionId"], 2)
                new_result = client.success(client.set(new_position, "STONE"))
                new_applied = self.assert_applied(case_id, client, 2, new_position, "minecraft:stone")
                self.read(case_id, completed_position, "minecraft:cobblestone")
                new_wire = self.wire(client)
                self.assertEqual([event["frame"]["id"] for event in new_wire
                                  if event["direction"] == "request"], [1, 2])
                self.record("V07", case_id, oldContext=old_context, newContext=client.context,
                            completed={"publicResult": completed_result, **completed},
                            reopened=reopened, activeSessions=active, persisted=persisted,
                            newWrite={"publicResult": new_result, **new_applied},
                            oldWire=old_wire, newWire=new_wire)
