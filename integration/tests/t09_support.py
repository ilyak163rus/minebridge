"""Independent T09 assertions shared by the V and D real-server suites."""

from __future__ import annotations

from contextlib import contextmanager
import re
import time
import unittest

from observer_client import ObserverError


class PaperAcceptance(unittest.TestCase):
    harness = paper = observer = world = None
    evidence: list[dict] = []

    @classmethod
    def setUpClass(cls) -> None:
        if cls.harness is None:
            raise unittest.SkipTest("Explicit real-server fixtures required: tools/smoke_t09.py")

    def case(self) -> str:
        case_id = self.observer.case_id()
        if self.harness.stage == "T10":
            self.harness.trace_offsets[case_id] = self.observer.result(case_id, "trace", 0)["latestSequence"]
        return case_id

    @contextmanager
    def prepared(self, case_id: str, positions: list[list[int]]):
        result = self.observer.result(case_id, "setup", self.world["uuid"],
                                      *("%d,%d,%d" % tuple(position) for position in positions))
        self.assertEqual(len(result["snapshots"]), len(positions))
        try:
            for position in positions:
                self.read(case_id, position, "minecraft:air")
            self.assertTrue(all(chunk["loaded"] and chunk["ticketHeld"] for chunk in result["chunks"]))
            yield result
        finally:
            deadline = time.monotonic() + 5
            while True:
                try:
                    cleaned = self.observer.result(case_id, "cleanup")
                    self.assertEqual(cleaned["restoredBlocks"], len(positions))
                    break
                except ObserverError as failure:
                    if failure.code != "CASE_BUSY" or time.monotonic() >= deadline:
                        raise
                    time.sleep(.02)  # Observe cancellation/completion, never infer it from elapsed time.

    def read(self, case_id: str, position: list[int], key: str | None = None) -> dict:
        envelope = self.observer.call(case_id, "read", self.world["uuid"], *position)
        value = envelope["result"]
        self.assertEqual(value["world"], self.world["uuid"])
        self.assertEqual([value["x"], value["y"], value["z"]], position)
        self.assertTrue(envelope["primaryThread"])
        if key is not None:
            self.assertEqual(value["key"], key)
            self.assertEqual(value["properties"], {})
            self.assertEqual(value["blockData"], key)
        return envelope

    def trace(self, case_id: str) -> dict:
        after = self.harness.trace_offsets.get(case_id, 0)
        snapshot = self.observer.result(case_id, "trace", after)
        self.assertEqual(snapshot["droppedEvents"], 0)
        if self.harness.stage == "T10":
            # Historical eviction is expected over the complete matrix; the
            # current case must still fit entirely after its checkpoint.
            self.assertLessEqual(snapshot["oldestSequence"], after + 1)
        else:
            self.assertEqual(snapshot["evictedEvents"], 0)
        return snapshot

    def wire(self, client) -> list[dict]:
        return self.harness.wiretap.frames_for_session(client.context["sessionId"])

    def assert_applied(self, case_id: str, client, rpc_id: int,
                       position: list[int], key: str) -> dict:
        snapshot = self.read(case_id, position, key)
        trace = self.trace(case_id)
        events = [item for item in trace["events"]
                  if item["sessionId"] == client.context["sessionId"] and item["requestId"] == rpc_id]
        phases = {item["phase"]: item for item in events}
        self.assertEqual([item["phase"] for item in events],
                         ["QUEUED", "APPLY_BEGIN", "APPLY_DONE", "ACK_ENQUEUED"])
        for phase in ("APPLY_BEGIN", "APPLY_DONE", "ACK_ENQUEUED"):
            event = phases[phase]
            self.assertTrue(event["primaryThread"])
            self.assertEqual(event["threadId"], snapshot["threadId"])
            self.assertEqual(event["caseId"], case_id)
            self.assertEqual(event["worldName"], self.world["name"])
            self.assertEqual(event["worldUuid"], self.world["uuid"])
            self.assertEqual([event["x"], event["y"], event["z"]], position)
        self.assertLess(phases["APPLY_BEGIN"]["sequence"], phases["APPLY_DONE"]["sequence"])
        self.assertLess(phases["APPLY_DONE"]["sequence"], phases["ACK_ENQUEUED"]["sequence"])
        self.assertEqual(phases["APPLY_BEGIN"]["applySequence"], phases["APPLY_DONE"]["applySequence"])
        self.assertEqual(phases["APPLY_DONE"]["applySequence"], phases["ACK_ENQUEUED"]["applySequence"])
        wire = [item for item in self.wire(client) if item["frame"].get("id") == rpc_id]
        requests = [item for item in wire if item["direction"] == "request"]
        responses = [item for item in wire if item["direction"] == "response"]
        self.assertEqual(len(requests), 1)
        self.assertEqual(len(responses), 1)
        request, response = requests[0], responses[0]
        self.assertEqual(request["frame"], {
            "jsonrpc": "2.0", "id": rpc_id, "method": "blocks.set",
            "params": {"world": self.world["name"], "position": position,
                       "block": {"key": key, "states": {}}},
        })
        self.assertEqual(response["frame"], {"jsonrpc": "2.0", "id": rpc_id, "result": {"applied": True}})
        self.assertLess(request["sequence"], response["sequence"])
        return {"snapshot": snapshot, "events": events, "request": request, "response": response}

    def assert_no_players(self) -> dict:
        start = len(self.paper.lines)
        self.paper.command("list")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            for line in self.paper.lines[start:]:
                match = re.search(r"There are (\d+) of a max of (\d+) players online", line)
                if match:
                    self.assertEqual(int(match[1]), 0)
                    return {"online": int(match[1]), "maximum": int(match[2]), "observed": match[0]}
            if self.paper.process.poll() is not None:
                break
            time.sleep(.02)
        self.fail("The Paper console did not confirm the online player count")

    def record(self, scenario_id: str, case_id: str, **details) -> None:
        self.evidence.append({"id": scenario_id, "caseId": case_id, "passed": True, **details})
