"""T10 N07–N10: real reactor framing, protocol profile and bounded resources.

Raw peers bypass Python validation.  Independent console snapshots, actual
queue counters and terminal socket events supply barriers; elapsed sleeps do
not stand in for proof that a frame was received or a queue was full.
"""

from __future__ import annotations

from contextlib import ExitStack
import json
import socket

from conftest import FacadeClient
from raw_peer import RawPeer
from t09_support import PaperAcceptance


class ProtocolEdgesAcceptance(PaperAcceptance):
    def positions(self, offset: int) -> list[list[int]]:
        y = self.world["maxYExclusive"] - 8
        return [[24576 + offset, y, 24576], [24577 + offset, y, 24576]]

    def request(self, rpc_id: int, position: list[int], key: str = "minecraft:cobblestone") -> dict:
        return {"jsonrpc": "2.0", "id": rpc_id, "method": "blocks.set",
                "params": {"world": self.world["name"], "position": position,
                           "block": {"key": key, "states": {}}}}

    @staticmethod
    def encoded(frame: object) -> bytes:
        return json.dumps(frame, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"

    def error(self, frame: dict, rpc_id: int | None, code: str, numeric: int) -> None:
        self.assertEqual(frame.get("jsonrpc"), "2.0")
        self.assertEqual(frame.get("id"), rpc_id)
        self.assertNotIn("result", frame)
        self.assertEqual(frame["error"]["code"], numeric)
        self.assertEqual(frame["error"]["data"], {"code": code, "outcome": "not-applied"})

    def raw_applied(self, case_id: str, peer: RawPeer, rpc_id: int) -> list[dict]:
        events = [event for event in self.trace(case_id)["events"]
                  if event["sessionId"] == peer.session_id and event["requestId"] == rpc_id]
        self.assertEqual([event["phase"] for event in events],
                         ["QUEUED", "APPLY_BEGIN", "APPLY_DONE", "ACK_ENQUEUED"])
        for event in events[1:]:
            self.assertTrue(event["primaryThread"])
            self.assertEqual(event["caseId"], case_id)
        self.assertLess(events[2]["sequence"], events[3]["sequence"])
        return events

    def track(self, case_id: str, peer: RawPeer, *ids: int, gate: bool = False) -> None:
        for rpc_id in ids:
            self.observer.result(case_id, "gateArm" if gate else "track", peer.session_id, rpc_id)

    def stats(self, case_id: str, peer: RawPeer, predicate=lambda value: True) -> dict:
        return self.observer.await_value(case_id, "sessionStats", (peer.session_id,), predicate)

    def assert_ack(self, peer: RawPeer, rpc_id: int) -> dict:
        result = peer.receive()
        self.assertEqual(result, {"jsonrpc": "2.0", "id": rpc_id, "result": {"applied": True}})
        return result

    def test_01_n07_fragmented_frame_is_not_queued_until_lf(self) -> None:
        case_id, positions = self.case(), self.positions(0)
        with self.prepared(case_id, positions[:1]):
            with RawPeer(token=self.harness.token) as peer:
                peer.hello()
                self.track(case_id, peer, 2)
                payload = self.encoded(self.request(2, positions[0]))
                cut = len(payload) // 2
                partial = []
                for piece, expected_size in ((payload[:cut], cut), (payload[cut:-1], len(payload) - 1)):
                    peer.send_bytes(piece)
                    value = self.stats(case_id, peer,
                                       lambda item: item["partialFrameBytes"] == expected_size)
                    self.assertEqual(value["receivedFrames"], 1)  # hello only
                    self.assertEqual(value["queuedRequests"], 0)
                    self.assertFalse(any(event["sessionId"] == peer.session_id and event["requestId"] == 2
                                         for event in self.trace(case_id)["events"]))
                    self.read(case_id, positions[0], "minecraft:air")
                    partial.append(value)
                peer.send_bytes(b"\n")
                response = self.assert_ack(peer, 2)
                completed = self.stats(case_id, peer, lambda value: value["receivedFrames"] == 2)
                self.assertEqual(completed["partialFrameBytes"], 0)
                observed = self.read(case_id, positions[0], "minecraft:cobblestone")
                events = self.raw_applied(case_id, peer, 2)
                self.record("N07", case_id, subcase="partial", context=peer.context, partial=partial,
                            completed=completed, response=response, snapshot=observed,
                            events=events, raw=peer.events)

    def test_02_n07_coalesced_queued_requests_preserve_fifo(self) -> None:
        case_id, positions = self.case(), self.positions(16)
        with self.prepared(case_id, positions[:1]):
            with RawPeer(token=self.harness.token) as peer:
                peer.hello()
                self.track(case_id, peer, 2, gate=True)
                self.track(case_id, peer, 3)
                peer.send_bytes(self.encoded(self.request(2, positions[0], "minecraft:stone"))
                                + self.encoded(self.request(3, positions[0])))
                gated = self.observer.await_value(case_id, "gateStatus", (peer.session_id, 2),
                                                  lambda value: value["state"] == "GATED"
                                                  and value["queuedRequests"] == 2)
                pending = [event for event in self.trace(case_id)["events"]
                           if event["sessionId"] == peer.session_id and event["requestId"] in (2, 3)]
                self.assertEqual([(event["requestId"], event["phase"]) for event in pending],
                                 [(2, "QUEUED"), (3, "QUEUED")])
                self.read(case_id, positions[0], "minecraft:air")
                self.observer.result(case_id, "gateRelease", peer.session_id, 2)
                responses = [self.assert_ack(peer, rpc_id) for rpc_id in (2, 3)]
                first, second = self.raw_applied(case_id, peer, 2), self.raw_applied(case_id, peer, 3)
                self.assertLess(first[2]["applySequence"], second[1]["applySequence"])
                observed = self.read(case_id, positions[0], "minecraft:cobblestone")
                self.record("N07", case_id, subcase="fifo", context=peer.context, gated=gated, pending=pending,
                            responses=responses, first=first, second=second, snapshot=observed, raw=peer.events)

    def test_03_n08_malformed_frames_close_without_mutation_and_b_keeps_working(self) -> None:
        case_id, positions = self.case(), self.positions(32)
        valid = self.encoded(self.request(2, positions[0]))
        duplicate = valid.replace(b'"id":2', b'"id":2,"id":2', 1)
        deep = self.request(2, positions[0])
        nested: object = 0
        for _ in range(17):
            nested = [nested]
        deep["unused"] = nested
        variants = [("invalid-json", valid[:-2] + b"\n", "PARSE_ERROR"),
                    ("invalid-utf8", valid[:-2] + b"\xff}\n", None),
                    ("duplicate-key", duplicate, "PARSE_ERROR"),
                    ("oversized", valid[:-1] + b" " * 65537 + b"\n", None),
                    ("deep", self.encoded(deep), None),
                    ("incomplete-eof", valid[:-1], None)]
        evidence = []
        with self.prepared(case_id, positions):
            with FacadeClient(self.harness, "N08-independent-B") as b:
                for index, (name, payload, expected) in enumerate(variants):
                    with self.subTest(name=name), RawPeer(token=self.harness.token) as peer:
                        peer.hello()
                        self.track(case_id, peer, 2)
                        peer.send_bytes(payload)
                        if name == "incomplete-eof":
                            peer.socket.shutdown(socket.SHUT_WR)
                        frames = peer.expect_eof()
                        if expected:
                            self.assertEqual(len(frames), 1)
                            self.error(frames[0], None, expected, -32700)
                        else:
                            self.assertEqual(frames, [])
                        unchanged = self.read(case_id, positions[0], "minecraft:air")
                        invalid_events = [event for event in self.trace(case_id)["events"]
                                          if event["sessionId"] == peer.session_id
                                          and event["requestId"] == 2]
                        self.assertEqual(invalid_events, [])
                        rpc_id = index + 2
                        self.observer.result(case_id, "track", b.context["sessionId"], rpc_id)
                        material = "STONE" if index % 2 == 0 else "COBBLESTONE"
                        result = b.success(b.set(positions[1], material))
                        applied = self.assert_applied(case_id, b, rpc_id, positions[1],
                                                      "minecraft:" + material.lower())
                        evidence.append({"variant": name, "context": peer.context,
                                         "frames": frames, "raw": peer.events, "unchanged": unchanged,
                                         "invalidEvents": invalid_events, "bResult": result, "bApplied": applied})
                self.record("N08", case_id, variants=evidence, independentClient=b.context)

    def test_04_n09_profile_rejections_are_exact_and_nonclosing_errors_keep_ready(self) -> None:
        case_id, positions = self.case(), self.positions(48)
        valid = self.request(2, positions[0])
        notification = dict(valid)
        del notification["id"]
        positional = dict(valid, params=list(valid["params"].values()))
        variants = [("batch", [valid], None, "INVALID_REQUEST"),
                    ("notification", notification, None, None),
                    ("null-id", dict(valid, id=None), None, "INVALID_REQUEST"),
                    ("string-id", dict(valid, id="2"), None, "INVALID_REQUEST"),
                    ("fraction-id", dict(valid, id=2.5), None, "INVALID_REQUEST"),
                    ("positional", positional, 2, "INVALID_REQUEST"),
                    ("repeated-id", dict(valid, id=1), 1, "INVALID_REQUEST")]
        rejected = []
        with self.prepared(case_id, positions[:1]):
            for name, payload, expected_id, expected in variants:
                with self.subTest(name=name), RawPeer(token=self.harness.token) as peer:
                    peer.hello()
                    self.track(case_id, peer, 2)
                    peer.send_bytes(self.encoded(payload))
                    frames = peer.expect_eof()
                    if expected is None:
                        self.assertEqual(frames, [])
                    else:
                        self.assertEqual(len(frames), 1)
                        self.error(frames[0], expected_id, expected, -32600)
                    self.read(case_id, positions[0], "minecraft:air")
                    invalid = [event for event in self.trace(case_id)["events"]
                               if event["sessionId"] == peer.session_id and event["phase"].startswith("APPLY_")]
                    self.assertEqual(invalid, [])
                    rejected.append({"variant": name, "context": peer.context, "frames": frames,
                                     "raw": peer.events, "applyEvents": invalid})
            with RawPeer(token=self.harness.token) as peer:
                peer.hello()
                self.track(case_id, peer, 2, 3, 4)
                peer.send({"jsonrpc": "2.0", "id": 2, "method": "future.method", "params": {}})
                unknown = peer.receive()
                self.error(unknown, 2, "METHOD_NOT_FOUND", -32601)
                extra = self.request(3, positions[0])
                extra["params"]["typo"] = 1
                peer.send(extra)
                invalid_params = peer.receive()
                self.error(invalid_params, 3, "INVALID_PARAMS", -32602)
                self.read(case_id, positions[0], "minecraft:air")
                for rpc_id in (2, 3):
                    self.assertFalse(any(event["sessionId"] == peer.session_id
                                         and event["requestId"] == rpc_id
                                         and event["phase"].startswith("APPLY_")
                                         for event in self.trace(case_id)["events"]))
                ready = self.stats(case_id, peer)
                self.assertTrue(ready["ready"] and ready["open"])
                peer.send(self.request(4, positions[0]))
                ack = self.assert_ack(peer, 4)
                events = self.raw_applied(case_id, peer, 4)
                observed = self.read(case_id, positions[0], "minecraft:cobblestone")
                self.record("N09", case_id, rejected=rejected, continued={"context": peer.context,
                            "unknown": unknown, "invalidParams": invalid_params, "ready": ready,
                            "ack": ack, "events": events, "snapshot": observed, "raw": peer.events})

    def test_05_n10_session_capacity_counts_unready_and_recovers(self) -> None:
        case_id = self.case()
        self.observer.await_value(case_id, "status", (), lambda value: len(value["sessions"]) == 0)
        with ExitStack() as stack:
            peers = [stack.enter_context(RawPeer(token=self.harness.token)) for _ in range(8)]
            # Seven READY plus one deliberately unready connection must consume all eight slots.
            for peer in peers[:7]:
                peer.hello()
            full = self.observer.await_value(case_id, "status", (), lambda value: len(value["sessions"]) == 8)
            self.assertEqual(sum(session["ready"] for session in full["sessions"]), 7)
            unready = [session["sessionId"] for session in full["sessions"] if not session["ready"]]
            self.assertEqual(len(unready), 1)
            with RawPeer(token=self.harness.token) as ninth:
                self.assertEqual(ninth.expect_eof(), [])
                rejected = list(ninth.events)
            still_full = self.observer.result(case_id, "status")
            self.assertEqual(len(still_full["sessions"]), 8)
            self.assertEqual({session["sessionId"] for session in still_full["sessions"]},
                             {session["sessionId"] for session in full["sessions"]})
            peers[-1].close()
            released = self.observer.await_value(case_id, "status", (), lambda value: len(value["sessions"]) == 7)
            with RawPeer(token=self.harness.token) as recovered:
                recovered.hello()
                ready = self.observer.await_value(case_id, "status", (), lambda value: len(value["sessions"]) == 8
                                                  and all(session["ready"] for session in value["sessions"]))
                self.assertNotIn(recovered.session_id, unready)
                self.record("N10", case_id, subcase="sessions", full=full, ninth=rejected, stillFull=still_full,
                            released=released, recovered=recovered.context, ready=ready)

    def test_06_n10_input_queue_eight_then_ninth_rejected_without_early_apply(self) -> None:
        case_id, positions = self.case(), self.positions(80)
        with self.prepared(case_id, positions):
            with RawPeer(token=self.harness.token) as peer, FacadeClient(self.harness, "N10-input-B") as b:
                peer.hello()
                self.track(case_id, peer, 2, gate=True)
                self.track(case_id, peer, *range(3, 11))
                payload = b"".join(self.encoded(self.request(rpc_id, positions[0],
                                  "minecraft:cobblestone" if rpc_id == 9 else "minecraft:stone"))
                                   for rpc_id in range(2, 11))
                peer.send_bytes(payload)
                overflow = peer.receive()
                self.error(overflow, 10, "LIMIT_EXCEEDED", -32010)
                gated = self.observer.await_value(case_id, "gateStatus", (peer.session_id, 2),
                                                  lambda value: value["state"] == "GATED"
                                                  and value["queuedRequests"] == 8)
                full = self.stats(case_id, peer)
                self.assertEqual(full["queuedRequests"], 8)
                self.assertEqual(full["requestHighWater"], 8)
                self.assertLessEqual(full["outputHighWater"], 8)
                pending = [event for event in self.trace(case_id)["events"]
                           if event["sessionId"] == peer.session_id and 2 <= event["requestId"] <= 10]
                self.assertEqual([(event["requestId"], event["phase"]) for event in pending],
                                 [(rpc_id, "QUEUED") for rpc_id in range(2, 10)])
                before = self.read(case_id, positions[0], "minecraft:air")
                self.observer.result(case_id, "track", b.context["sessionId"], 2)
                b_result = b.success(b.set(positions[1], "COBBLESTONE"))
                b_applied = self.assert_applied(case_id, b, 2, positions[1], "minecraft:cobblestone")
                self.assertGreater(b_applied["snapshot"]["tick"], before["tick"])
                self.assertEqual(self.stats(case_id, peer)["queuedRequests"], 8)
                self.read(case_id, positions[0], "minecraft:air")
                self.observer.result(case_id, "gateRelease", peer.session_id, 2)
                acks = [self.assert_ack(peer, rpc_id) for rpc_id in range(2, 10)]
                applied = [self.raw_applied(case_id, peer, rpc_id) for rpc_id in range(2, 10)]
                sequences = [events[2]["applySequence"] for events in applied]
                self.assertEqual(sequences, sorted(set(sequences)))
                self.read(case_id, positions[0], "minecraft:cobblestone")
                after = self.stats(case_id, peer)
                self.assertEqual(after["queuedRequests"], 0)
                self.assertTrue(after["open"])
                self.assertEqual(after["requestHighWater"], 8)
                self.assertLessEqual(after["outputHighWater"], 8)
                self.record("N10", case_id, subcase="input", context=peer.context, overflow=overflow, gated=gated,
                            full=full, pending=pending, before=before, bResult=b_result, bApplied=b_applied,
                            acks=acks, applied=applied, after=after, raw=peer.events)

    def test_07_n10_output_queue_eight_then_ninth_closes_and_capacity_recovers(self) -> None:
        case_id, positions = self.case(), self.positions(96)
        with self.prepared(case_id, positions):
            with RawPeer(token=self.harness.token) as peer, FacadeClient(self.harness, "N10-output-B") as b:
                peer.hello()
                paused = self.observer.result(case_id, "writerPause", peer.session_id)
                self.assertTrue(paused["writerPaused"])
                self.assertEqual(paused["outputFrames"], 0)
                self.track(case_id, peer, *range(2, 11))
                fill = []
                for count, rpc_id in enumerate(range(2, 10), 1):
                    peer.send({"jsonrpc": "2.0", "id": rpc_id, "method": "future.method", "params": {}})
                    value = self.stats(case_id, peer, lambda item: item["outputFrames"] == count)
                    self.assertTrue(value["open"])
                    self.assertEqual(value["outputHighWater"], count)
                    self.assertLessEqual(value["requestHighWater"], 1)
                    fill.append(value)
                before = self.read(case_id, positions[0], "minecraft:air")
                self.observer.result(case_id, "track", b.context["sessionId"], 2)
                b_result = b.success(b.set(positions[1], "STONE"))
                b_applied = self.assert_applied(case_id, b, 2, positions[1], "minecraft:stone")
                self.assertGreater(b_applied["snapshot"]["tick"], before["tick"])
                still_full = self.stats(case_id, peer)
                self.assertEqual(still_full["outputFrames"], 8)
                peer.send({"jsonrpc": "2.0", "id": 10, "method": "future.method", "params": {}})
                frames = peer.expect_eof()
                self.assertEqual(frames, [])  # Paused queue is discarded atomically on overflow.
                closed = self.stats(case_id, peer, lambda value: not value["open"])
                self.assertEqual(closed["outputHighWater"], 8)
                self.assertEqual(closed["outputFrames"], 0)
                self.assertEqual(closed["queuedRequests"], 0)
                self.assertLessEqual(closed["requestHighWater"], 1)
                self.read(case_id, positions[0], "minecraft:air")
                with RawPeer(token=self.harness.token) as recovered:
                    recovered.hello()
                    self.track(case_id, recovered, 2)
                    recovered.send(self.request(2, positions[0]))
                    ack = self.assert_ack(recovered, 2)
                    applied = self.raw_applied(case_id, recovered, 2)
                    observed = self.read(case_id, positions[0], "minecraft:cobblestone")
                    self.record("N10", case_id, subcase="output", context=peer.context, paused=paused, fill=fill,
                                stillFull=still_full, closed=closed, bResult=b_result, bApplied=b_applied,
                                recovered={"context": recovered.context, "ack": ack, "events": applied,
                                           "snapshot": observed}, raw=peer.events)

    def test_08_n10_stalled_writer_deadline_closes_without_blocking_other_session(self) -> None:
        case_id, positions = self.case(), self.positions(112)
        with self.prepared(case_id, positions):
            with RawPeer(token=self.harness.token) as peer, FacadeClient(self.harness, "N10-stalled-B") as b:
                peer.hello()
                self.observer.result(case_id, "writerPause", peer.session_id)
                self.track(case_id, peer, 2)
                peer.send({"jsonrpc": "2.0", "id": 2, "method": "future.method", "params": {}})
                queued = self.stats(case_id, peer, lambda value: value["outputFrames"] == 1)
                before = self.read(case_id, positions[0], "minecraft:air")
                self.observer.result(case_id, "track", b.context["sessionId"], 2)
                b_result = b.success(b.set(positions[1], "STONE"))
                b_applied = self.assert_applied(case_id, b, 2, positions[1], "minecraft:stone")
                self.assertGreater(b_applied["snapshot"]["tick"], before["tick"])
                self.assertEqual(peer.expect_eof(timeout=8), [])
                closed = self.stats(case_id, peer, lambda value: not value["open"])
                self.assertEqual(closed["outputHighWater"], 1)
                self.assertEqual(closed["outputFrames"], 0)
                self.read(case_id, positions[0], "minecraft:air")
                self.observer.result(case_id, "track", b.context["sessionId"], 3)
                b_second = b.success(b.set(positions[1], "COBBLESTONE"))
                continued = self.assert_applied(case_id, b, 3, positions[1], "minecraft:cobblestone")
                self.record("N10", case_id, subcase="stalled-writer", context=peer.context, queued=queued, closed=closed,
                            bResult=b_result, bApplied=b_applied, bSecond=b_second, bContinued=continued,
                            raw=peer.events, simulation="Local writer pause; production 5-second deadline unchanged")
