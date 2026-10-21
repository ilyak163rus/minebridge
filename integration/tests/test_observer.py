"""T08 observer and nonblocking gate acceptance on a real pinned Paper server.

Run through tools/smoke_t08.py. Discovery without explicitly supplied fixtures
skips the server suite instead of starting Java or accepting EULA implicitly.
These cases do not claim the complete T09/T10 vertical/fault matrix.
"""

from __future__ import annotations

from contextlib import contextmanager
import time
import unittest
import uuid

from conftest import FacadeClient
from observer_client import ObserverError


class ObserverAcceptance(unittest.TestCase):
    harness = paper = observer = world = None
    evidence: list[dict] = []

    @classmethod
    def setUpClass(cls) -> None:
        if cls.harness is None:
            raise unittest.SkipTest("Explicit real-server fixtures required: tools/smoke_t08.py")

    def case(self) -> str:
        return self.observer.case_id()

    def positions(self, offset: int = 0) -> list[list[int]]:
        y = self.world["maxYExclusive"] - 8
        return [[16384 + offset, y, 16384], [-16384 - offset, y, 16384]]

    @contextmanager
    def prepared(self, case_id: str, positions: list[list[int]]):
        prepared = self.observer.result(case_id, "setup", self.world["uuid"],
                                        *("%d,%d,%d" % tuple(at) for at in positions))
        try:
            yield prepared
        finally:
            deadline = time.monotonic() + 5
            while True:
                try:
                    self.observer.result(case_id, "cleanup")
                    break
                except ObserverError as failure:
                    # A child close interrupts its own socket immediately;
                    # the server reactor still needs to observe that EOF.
                    if failure.code != "CASE_BUSY" or time.monotonic() >= deadline:
                        raise
                    time.sleep(.02)

    def read(self, case_id: str, position: list[int], key: str | None = None) -> dict:
        envelope = self.observer.call(case_id, "read", self.world["uuid"], *position)
        snapshot = envelope["result"]
        self.assertEqual(snapshot["world"], self.world["uuid"])
        self.assertEqual([snapshot["x"], snapshot["y"], snapshot["z"]], position)
        self.assertIsInstance(snapshot["properties"], dict)
        self.assertTrue(envelope["primaryThread"])
        if key is not None:
            self.assertEqual(snapshot["key"], key)
            self.assertEqual(snapshot["properties"], {})
            self.assertEqual(snapshot["blockData"], key)
        return envelope

    def test_01_oracle_preparation_read_correlation_and_cleanup(self) -> None:
        case_id, positions = self.case(), self.positions()
        self.assertTrue(self.observer.result(case_id, "status")["controlEnabled"])
        # Change a bottom-of-world terrain position as well as an
        # air position, so restoration is checked on data that setup changed.
        positions[0][1] = self.world["minY"]
        preparation = self.observer.result(case_id, "setup", self.world["uuid"],
                                            *("%d,%d,%d" % tuple(at) for at in positions))
        try:
            self.assertEqual(len(preparation["snapshots"]), 2)
            self.assertEqual(len(preparation["originals"]), 2)
            self.assertTrue(any(original["key"] != "minecraft:air"
                                for original in preparation["originals"]))
            self.assertEqual(len(preparation["chunks"]), 2)
            for snapshot, position in zip(preparation["snapshots"], positions):
                self.assertEqual(snapshot["world"], self.world["uuid"])
                self.assertEqual([snapshot["x"], snapshot["y"], snapshot["z"]], position)
                self.assertEqual(snapshot["key"], "minecraft:air")
                self.read(case_id, position, "minecraft:air")
            for chunk in preparation["chunks"]:
                self.assertTrue(chunk["loaded"])
                self.assertTrue(chunk["ticketHeld"])
            for position, key in zip(positions, ("minecraft:stone", "minecraft:cobblestone")):
                self.observer.result(case_id, "seed", self.world["uuid"], *position, key)
                self.read(case_id, position, key)
            self.observer.call(case_id, "read", str(uuid.uuid4()), *positions[0],
                               expected_error="WORLD_NOT_FOUND")
        finally:
            cleanup = self.observer.result(case_id, "cleanup")
        self.assertEqual(cleanup["restoredBlocks"], 2)
        self.assertEqual(cleanup["releasedChunks"], 2)
        self.assertEqual(cleanup["remainingCases"], 0)
        for position in positions:
            chunk = self.observer.result(case_id, "checkChunk", self.world["uuid"],
                                          position[0] // 16, position[2] // 16)
            self.assertFalse(chunk["ticketHeld"])
        # Reload explicitly through a new fixture before comparing restored
        # originals. A read after ticket release must never load a chunk itself.
        verification_case = self.case()
        with self.prepared(verification_case, positions) as verification:
            self.assertEqual(verification["originals"], preparation["originals"])
        self.evidence.append({"case": "oracle-self-test", "caseId": case_id, "passed": True})

    def test_02_explicit_load_unload_has_observed_completion(self) -> None:
        case_id = self.case()
        position = [32768, self.world["maxYExclusive"] - 8, 32768]
        with self.prepared(case_id, [position]):
            chunk_args = (self.world["uuid"], position[0] // 16, position[2] // 16)
            loaded = self.observer.result(case_id, "checkChunk", *chunk_args)
            self.assertTrue(loaded["loaded"])
            self.assertTrue(loaded["ticketHeld"])
            unloaded = self.observer.result(case_id, "unload", *chunk_args, 200, timeout=20)
            self.assertFalse(unloaded["loaded"])
            self.assertFalse(unloaded["ticketHeld"])
            observed = self.observer.result(case_id, "checkChunk", *chunk_args)
            self.assertFalse(observed["loaded"])
            self.assertFalse(observed["ticketHeld"])
        self.evidence.append({"case": "observer-load-unload", "caseId": case_id, "passed": True})

    def test_03_gate_defers_apply_without_blocking_ticks_or_other_session(self) -> None:
        case_id, positions = self.case(), self.positions(64)
        with self.prepared(case_id, positions):
            with FacadeClient(self.harness, "gate-A") as a, FacadeClient(self.harness, "gate-B") as b:
                self.assertNotEqual(a.context["pid"], b.context["pid"])
                self.assertNotEqual(a.context["sessionId"], b.context["sessionId"])
                self.assertEqual(a.context["world"], self.world)
                self.assertEqual(b.context["world"], self.world)
                session = a.context["sessionId"]
                self.observer.result(case_id, "gateArm", session, 2)
                self.observer.result(case_id, "track", b.context["sessionId"], 2)
                command = a.set(positions[0], "COBBLESTONE")
                self.observer.await_value(case_id, "gateStatus", (session, 2),
                                          lambda value: value["state"] == "GATED")
                before = self.read(case_id, positions[0], "minecraft:air")
                a.assert_pending()
                # Cleanup must check the pending-operation guard before it
                # restores any block or releases any fixture ticket.
                self.observer.call(case_id, "cleanup", expected_error="CASE_BUSY")
                still_held = self.observer.result(case_id, "gateStatus", session, 2)
                self.assertEqual(still_held["state"], "GATED")
                self.read(case_id, positions[0], "minecraft:air")
                chunk = self.observer.result(case_id, "checkChunk", self.world["uuid"],
                                              positions[0][0] // 16, positions[0][2] // 16)
                self.assertTrue(chunk["loaded"])
                self.assertTrue(chunk["ticketHeld"])
                a.assert_pending()
                b.success(b.set(positions[1], "STONE", route="blocks"))
                self.read(case_id, positions[1], "minecraft:stone")
                self.observer.await_value(
                    case_id, "checkChunk", (self.world["uuid"], positions[0][0] // 16, positions[0][2] // 16),
                    lambda _: self.observer.envelopes[-1]["tick"] > before["tick"])
                a.assert_pending()
                before_trace = self.observer.result(case_id, "trace", 0)
                pending_events = self.events(before_trace, session, 2)
                self.assertIn("QUEUED", [item["phase"] for item in pending_events])
                self.assertNotIn("APPLY_BEGIN", [item["phase"] for item in pending_events])
                released = self.observer.result(case_id, "gateRelease", session, 2)
                self.assertEqual(released["state"], "RELEASED")
                a.success(command)
                self.read(case_id, positions[0], "minecraft:cobblestone")
                trace = self.observer.result(case_id, "trace", 0)
                self.assertEqual(trace["droppedEvents"], 0)
                self.assertEqual(trace["evictedEvents"], 0)
                for client, position in ((a, positions[0]), (b, positions[1])):
                    events = self.events(trace, client.context["sessionId"], 2)
                    phases = {item["phase"]: item for item in events}
                    for phase in ("APPLY_BEGIN", "APPLY_DONE", "ACK_ENQUEUED"):
                        self.assertEqual(sum(event["phase"] == phase for event in events), 1)
                        self.assertTrue(phases[phase]["primaryThread"])
                        self.assertEqual(phases[phase]["threadId"], before["threadId"])
                        self.assertEqual(phases[phase]["caseId"], case_id)
                        self.assertEqual(phases[phase]["worldUuid"], self.world["uuid"])
                        self.assertEqual([phases[phase]["x"], phases[phase]["y"], phases[phase]["z"]], position)
                    self.assertLess(phases["APPLY_BEGIN"]["sequence"], phases["APPLY_DONE"]["sequence"])
                    self.assertLess(phases["APPLY_DONE"]["sequence"], phases["ACK_ENQUEUED"]["sequence"])
                    self.assertEqual(phases["APPLY_BEGIN"]["applySequence"], phases["APPLY_DONE"]["applySequence"])
                self.evidence.append({"case": "gate-progress-release-order", "caseId": case_id,
                                      "passed": True, "processes": [a.context, b.context], "trace": trace})

    @staticmethod
    def events(trace: dict, session: str, request_id: int) -> list[dict]:
        return [event for event in trace["events"]
                if event["sessionId"] == session and event["requestId"] == request_id]

    def test_04_close_held_request_cancels_before_any_setter(self) -> None:
        case_id, positions = self.case(), self.positions(128)
        with self.prepared(case_id, positions):
            with FacadeClient(self.harness, "cancel-A") as a, FacadeClient(self.harness, "cancel-B") as b:
                session = a.context["sessionId"]
                self.observer.result(case_id, "gateArm", session, 2)
                command = a.set(positions[0], "COBBLESTONE")
                self.observer.await_value(case_id, "gateStatus", (session, 2),
                                          lambda value: value["state"] == "GATED")
                a.assert_pending()
                completion = a.close()
                failed = next(event for event in completion if event.get("commandId") == command)
                self.assertFalse(failed["ok"])
                self.assertEqual(failed["outcome"], "unknown")
                cancelled = self.observer.await_value(
                    case_id, "gateStatus", (session, 2),
                    lambda value: value["state"] == "CANCELLED" and value["sessionOpen"] is False)
                self.observer.result(case_id, "gateRelease", session, 2)
                b.success(b.set(positions[1], "STONE"))
                self.read(case_id, positions[1], "minecraft:stone")
                self.read(case_id, positions[0], "minecraft:air")
                trace = self.observer.result(case_id, "trace", 0)
                phases = [event["phase"] for event in self.events(trace, session, 2)]
                self.assertIn("CANCELLED", phases)
                self.assertNotIn("APPLY_BEGIN", phases)
                self.assertNotIn("APPLY_DONE", phases)
                self.assertNotIn("ACK_ENQUEUED", phases)
                self.evidence.append({"case": "gate-close-cancellation-barrier", "caseId": case_id,
                                      "passed": True, "cancelled": cancelled, "trace": trace})


class ControlDisabledAcceptance(ObserverAcceptance):
    """Uses the identical production artifact restarted without the opt-in flag."""

    def test_01_oracle_preparation_read_correlation_and_cleanup(self) -> None:
        case_id, positions = self.case(), self.positions(256)
        status = self.observer.result(case_id, "status")
        self.assertFalse(status["controlEnabled"])
        with self.prepared(case_id, [positions[0]]):
            with FacadeClient(self.harness, "control-disabled-client") as client:
                self.observer.call(case_id, "gateArm", client.context["sessionId"], 2,
                                   expected_error="CONTROL_DISABLED")
                client.success(client.set(positions[0], "COBBLESTONE"))
                self.read(case_id, positions[0], "minecraft:cobblestone")
        self.evidence.append({"case": "same-production-JAR-control-disabled", "caseId": case_id, "passed": True})

    # Suppress inherited enabled-mode scenarios from unittest discovery.
    test_02_explicit_load_unload_has_observed_completion = None
    test_03_gate_defers_apply_without_blocking_ticks_or_other_session = None
    test_04_close_held_request_cancels_before_any_setter = None
