"""T10 N01--N06: actual Paper rejects unsafe input without invoking a setter."""

from __future__ import annotations

import json
import os
import subprocess
import uuid

from conftest import FacadeClient
from raw_peer import RawPeer
from t09_support import PaperAcceptance


ERROR_NUMBERS = {
    "AUTH_FAILED": -32001, "PROTOCOL_VERSION": -32002, "NOT_READY": -32003,
    "INVALID_STATE": -32004, "INVALID_PARAMS": -32602,
    "WORLD_NOT_FOUND": -32020, "PERMISSION_DENIED": -32021,
    "COORDINATE_OUT_OF_BOUNDS": -32022, "CHUNK_NOT_LOADED": -32023,
    "INVALID_BLOCK": -32024, "UNSUPPORTED_FEATURE": -32025,
    "METHOD_NOT_FOUND": -32601,
}


class ValidationAcceptance(PaperAcceptance):
    def position(self, offset: int = 0) -> list[int]:
        return [65536 + offset, self.world["maxYExclusive"] - 8, 65536]

    def request(self, request_id: int, position, *, world=None, block=None) -> dict:
        return {"jsonrpc": "2.0", "id": request_id, "method": "blocks.set",
                "params": {"world": self.world["name"] if world is None else world,
                           "position": position,
                           "block": {"key": "minecraft:cobblestone", "states": {}}
                           if block is None else block}}

    def reject(self, peer: RawPeer, frame: dict, code: str, *, close=False) -> dict:
        peer.send(frame)
        reply = peer.receive()
        self.assertEqual(reply.get("jsonrpc"), "2.0")
        self.assertEqual(reply.get("id"), frame["id"])
        self.assertNotIn("result", reply)
        self.assertEqual(reply["error"]["code"], ERROR_NUMBERS[code])
        self.assertEqual(reply["error"]["data"], {"code": code, "outcome": "not-applied"})
        if close:
            self.assertEqual(peer.expect_eof(), [])
        return reply

    def checkpoint(self, case_id: str) -> dict:
        return self.observer.result(case_id, "trace", 0)

    def request_events(self, case_id: str, peer: RawPeer, request_id: int,
                       checkpoint: dict, *, error: str | None = None) -> list[dict]:
        trace = self.observer.result(case_id, "trace", checkpoint["latestSequence"])
        self.assertEqual(trace["droppedEvents"], checkpoint["droppedEvents"])
        # History may have evicted older unrelated cases. The current small
        # request's complete interval must still be retained.
        self.assertLessEqual(trace["oldestSequence"], checkpoint["latestSequence"] + 1)
        events = [event for event in trace["events"]
                  if event["sessionId"] == peer.session_id and event["requestId"] == request_id]
        self.assertTrue(events)
        self.assertTrue(all(event["caseId"] == case_id for event in events))
        if error is not None:
            self.assertEqual([event["phase"] for event in events], ["QUEUED", "ERROR"])
            self.assertEqual(events[-1]["errorCode"], error)
            self.assertEqual(events[-1]["outcome"], "not-applied")
            self.assertTrue(events[-1]["primaryThread"])
        return events

    def ready(self, case_id: str, peer: RawPeer) -> dict:
        status = self.observer.result(case_id, "status")
        matching = [entry for entry in status["sessions"] if entry["sessionId"] == peer.session_id]
        self.assertEqual(len(matching), 1)
        self.assertTrue(matching[0]["ready"] and matching[0]["open"])
        self.assertEqual(matching[0]["queuedRequests"], 0)
        return matching[0]

    def test_01_n01_authentication_precedes_any_world_mutation(self) -> None:
        case_id, position = self.case(), self.position()
        with self.prepared(case_id, [position]):
            # This runs the installed wheel in an isolated interpreter. A DNS
            # sentinel additionally proves that absence of env fails locally.
            script = '''import json,socket
from minebridge import Minecraft
from minebridge.errors import AuthenticationError
calls=[]
def forbidden(*args, **kwargs):
    calls.append(True)
    raise AssertionError("DNS must not run before local token validation")
socket.getaddrinfo=forbidden
try:
    Minecraft.create("missing-token.invalid",4711)
except AuthenticationError as failure:
    assert not calls
    print(json.dumps({"error":type(failure).__name__,"code":failure.code,"outcome":failure.outcome,"dnsCalls":len(calls)}))
else:
    raise AssertionError("Missing lesson token unexpectedly accepted")
'''
            environment = os.environ.copy()
            environment.pop("MINEBRIDGE_TOKEN", None)
            local = subprocess.run([str(self.harness.python), "-I", "-c", script], env=environment,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                   encoding="utf-8", timeout=15,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.assertEqual(local.returncode, 0, "Isolated local token validation failed")
            self.assertEqual(local.stderr, "")
            local_proof = json.loads(local.stdout)
            self.assertEqual(local_proof, {"error": "AuthenticationError", "code": "AUTH_FAILED",
                                           "outcome": "not-applied", "dnsCalls": 0})
            with RawPeer(token=self.harness.token) as peer:
                failed = self.reject(peer, RawPeer.hello_frame("intentionally-wrong-lesson-token"),
                                     "AUTH_FAILED", close=True)
                wire = list(peer.events)
            unchanged = self.read(case_id, position, "minecraft:air")
            self.record("N01", case_id, local=local_proof, wrongTokenReply=failed,
                        eof=True, unchanged=unchanged, wire=wire)

    def test_02_n02_hello_schema_state_and_major_are_enforced(self) -> None:
        case_id, position = self.case(), self.position(16)
        cases = []
        with self.prepared(case_id, [position]):
            invalid = [
                ("major-2", {"protocol": {"major": 2, "minor": 0}}, "PROTOCOL_VERSION"),
                ("major-negative", {"protocol": {"major": -1, "minor": 0}}, "INVALID_PARAMS"),
                ("minor-fraction", {"protocol": {"major": 1, "minor": .5}}, "INVALID_PARAMS"),
                ("minor-bool", {"protocol": {"major": 1, "minor": True}}, "INVALID_PARAMS"),
                ("protocol-incomplete", {"protocol": {"major": 1}}, "INVALID_PARAMS"),
                ("token-type", {"token": 42}, "INVALID_PARAMS"),
                ("world-type", {"world": 42}, "INVALID_PARAMS"),
                ("relative-profile", {"coordinates": "relative"}, "UNSUPPORTED_FEATURE"),
                ("unknown-field", {"unexpected": 1}, "INVALID_PARAMS"),
            ]
            for name, overrides, code in invalid:
                with RawPeer(token=self.harness.token) as peer:
                    frame = RawPeer.hello_frame(self.harness.token, **overrides)
                    reply = self.reject(peer, frame, code, close=True)
                    cases.append({"name": name, "reply": reply, "wire": list(peer.events),
                                  "unchanged": self.read(case_id, position, "minecraft:air")})
            for missing in ("token", "coordinates"):
                with RawPeer(token=self.harness.token) as peer:
                    frame = RawPeer.hello_frame(self.harness.token)
                    del frame["params"][missing]
                    reply = self.reject(peer, frame, "INVALID_PARAMS", close=True)
                    cases.append({"name": "missing-" + missing, "reply": reply,
                                  "wire": list(peer.events)})
            with RawPeer(token=self.harness.token) as peer:
                peer.hello()
                frame = RawPeer.hello_frame(self.harness.token)
                frame["id"] = 2
                reply = self.reject(peer, frame, "INVALID_STATE", close=True)
                cases.append({"name": "repeated-hello", "reply": reply, "wire": list(peer.events)})
            with RawPeer(token=self.harness.token) as peer:
                reply = self.reject(peer, self.request(1, position), "NOT_READY", close=True)
                cases.append({"name": "blocks-before-hello", "reply": reply, "wire": list(peer.events)})
            self.record("N02", case_id, subcases=cases,
                        unchanged=self.read(case_id, position, "minecraft:air"))

    def test_03_n03_unknown_and_other_existing_worlds_are_not_authorized(self) -> None:
        case_id, other_case = self.case(), self.case()
        position = self.position(32)
        worlds = self.observer.result(case_id, "worlds")["worlds"]
        others = [world for world in worlds if world["uuid"] != self.world["uuid"]]
        self.assertTrue(others, "The controlled Paper fixture must have another existing world")
        other = others[0]
        other_position = [position[0], other["maxYExclusive"] - 8, position[2]]
        missing = "missing-" + uuid.uuid4().hex
        cases = []
        with self.prepared(case_id, [position]):
            preparation = self.observer.result(other_case, "setup", other["uuid"],
                                               "%d,%d,%d" % tuple(other_position))
            try:
                before_other = self.observer.call(other_case, "read", other["uuid"], *other_position)
                self.assertEqual(before_other["result"]["key"], "minecraft:air")
                for requested, code in ((missing, "WORLD_NOT_FOUND"),
                                        (other["name"], "PERMISSION_DENIED")):
                    with RawPeer(token=self.harness.token) as peer:
                        reply = self.reject(peer, RawPeer.hello_frame(self.harness.token, world=requested),
                                            code, close=True)
                        cases.append({"phase": "hello", "requestedWorld": requested,
                                      "reply": reply, "wire": list(peer.events)})
                with RawPeer(token=self.harness.token) as peer:
                    context = peer.hello()
                    self.assertEqual(context["world"], self.world)
                    for request_id, requested, code in ((2, missing, "WORLD_NOT_FOUND"),
                                                        (3, other["name"], "PERMISSION_DENIED")):
                        self.observer.result(case_id, "track", peer.session_id, request_id)
                        before = self.checkpoint(case_id)
                        reply = self.reject(peer, self.request(request_id, position, world=requested), code)
                        events = self.request_events(case_id, peer, request_id, before, error=code)
                        cases.append({"phase": "blocks.set", "requestedWorld": requested,
                                      "reply": reply, "events": events, "ready": self.ready(case_id, peer)})
                    peer.send({"jsonrpc": "2.0", "id": 4, "method": "not.a.method", "params": {}})
                    self.assertEqual(peer.receive()["error"]["data"]["code"], "METHOD_NOT_FOUND")
                    wire = list(peer.events)
                after_other = self.observer.call(other_case, "read", other["uuid"], *other_position)
                self.assertEqual(after_other["result"], before_other["result"])
                self.record("N03", case_id, selectedWorld=self.world, otherWorld=other,
                            subcases=cases, wire=wire, otherBefore=before_other, otherAfter=after_other,
                            unchanged=self.read(case_id, position, "minecraft:air"), preparation=preparation)
            finally:
                self.observer.result(other_case, "cleanup")

    def test_04_n04_invalid_blocks_and_unsupported_legacy_never_fall_back_to_air(self) -> None:
        case_id, position = self.case(), self.position(48)
        cases = []
        with self.prepared(case_id, [position]):
            with RawPeer(token=self.harness.token) as peer:
                peer.hello()
                invalid = [
                    ({"key": "minecraft:there_is_no_such_block_t10", "states": {}}, "INVALID_BLOCK"),
                    ({"key": "minecraft:iron_sword", "states": {}}, "INVALID_BLOCK"),
                    ({"key": "STONE", "states": {}}, "INVALID_BLOCK"),
                    ({"key": "minecraft:stone", "states": {"axis": "x"}}, "UNSUPPORTED_FEATURE"),
                ]
                for request_id, (value, code) in enumerate(invalid, 2):
                    self.observer.result(case_id, "track", peer.session_id, request_id)
                    before = self.checkpoint(case_id)
                    reply = self.reject(peer, self.request(request_id, position, block=value), code)
                    events = self.request_events(case_id, peer, request_id, before, error=code)
                    cases.append({"input": value, "reply": reply, "events": events,
                                  "unchanged": self.read(case_id, position, "minecraft:air")})
                raw_wire = list(peer.events)
                self.ready(case_id, peer)
            with FacadeClient(self.harness, "n04-local-legacy") as client:
                before = self.checkpoint(case_id)
                for material, data, form in ((999, 0, "numeric"), (4, 1, "numeric"), (999, 0, "legacy")):
                    command_id = client.set(position, material, form=form, data=data)
                    failure = client.response()
                    self.assertEqual(failure, {"type": "result", "commandId": command_id, "ok": False,
                                               "error": "UnsupportedLegacyBlockError",
                                               "code": "UNSUPPORTED_LEGACY_BLOCK", "outcome": "not-applied"})
                    cases.append({"form": form, "legacyId": material, "data": data,
                                  "localFailure": failure})
                trace = self.observer.result(case_id, "trace", before["latestSequence"])
                self.assertFalse(any(event["sessionId"] == client.context["sessionId"]
                                     for event in trace["events"]))
                public_wire = self.wire(client)
                self.assertEqual([item["frame"]["method"] for item in public_wire
                                  if item["direction"] == "request"], ["system.hello"])
                self.record("N04", case_id, subcases=cases, rawWire=raw_wire, localWire=public_wire,
                            noLocalMutationRPC=True, unchanged=self.read(case_id, position, "minecraft:air"))

    def test_05_n05_raw_coordinates_height_and_exact_border_are_checked(self) -> None:
        case_id = self.case()
        ordinary = self.position(64)
        bottom = [ordinary[0], self.world["minY"], ordinary[2]]
        top = [ordinary[0], self.world["maxYExclusive"] - 1, ordinary[2]]
        lower = [ordinary[0] - 2, ordinary[1], ordinary[2]]
        upper = [ordinary[0] + 2, ordinary[1], ordinary[2]]
        outside = [ordinary[0] - 3, ordinary[1], ordinary[2]]
        z_upper = [ordinary[0], ordinary[1], ordinary[2] + 2]
        positions = [ordinary, bottom, top, lower, upper, outside, z_upper]
        cases = []
        with self.prepared(case_id, positions):
            with RawPeer(token=self.harness.token) as peer:
                peer.hello()
                invalid = [
                    (None, "INVALID_PARAMS"), ("0,0,0", "INVALID_PARAMS"),
                    (ordinary[:2], "INVALID_PARAMS"), (ordinary + [0], "INVALID_PARAMS"),
                    ([ordinary[0] + .5, ordinary[1], ordinary[2]], "INVALID_PARAMS"),
                    ([True, ordinary[1], ordinary[2]], "INVALID_PARAMS"),
                    ([2147483648, ordinary[1], ordinary[2]], "INVALID_PARAMS"),
                    ([-2147483649, ordinary[1], ordinary[2]], "INVALID_PARAMS"),
                    ([ordinary[0], self.world["minY"] - 1, ordinary[2]], "COORDINATE_OUT_OF_BOUNDS"),
                    ([ordinary[0], self.world["maxYExclusive"], ordinary[2]], "COORDINATE_OUT_OF_BOUNDS"),
                ]
                request_id = 2
                for supplied, code in invalid:
                    self.observer.result(case_id, "track", peer.session_id, request_id)
                    before = self.checkpoint(case_id)
                    reply = self.reject(peer, self.request(request_id, supplied), code)
                    events = self.request_events(case_id, peer, request_id, before, error=code)
                    cases.append({"inputPosition": supplied, "reply": reply, "events": events})
                    request_id += 1
                unchanged = [self.read(case_id, position, "minecraft:air") for position in positions]
                border = self.observer.result(case_id, "border", self.world["uuid"], 4,
                                               ordinary[0] + .5, ordinary[2] + .5)
                try:
                    for supplied in (upper, outside, z_upper):
                        self.observer.result(case_id, "track", peer.session_id, request_id)
                        before = self.checkpoint(case_id)
                        reply = self.reject(peer, self.request(request_id, supplied), "COORDINATE_OUT_OF_BOUNDS")
                        events = self.request_events(case_id, peer, request_id, before,
                                                     error="COORDINATE_OUT_OF_BOUNDS")
                        cases.append({"inputPosition": supplied, "border": border,
                                      "reply": reply, "events": events,
                                      "unchanged": self.read(case_id, supplied, "minecraft:air")})
                        request_id += 1
                    self.observer.result(case_id, "track", peer.session_id, request_id)
                    before = self.checkpoint(case_id)
                    peer.send(self.request(request_id, lower))
                    allowed = peer.receive()
                    self.assertEqual(allowed, {"jsonrpc": "2.0", "id": request_id,
                                               "result": {"applied": True}})
                    allowed_events = self.request_events(case_id, peer, request_id, before)
                    self.assertEqual([event["phase"] for event in allowed_events],
                                     ["QUEUED", "APPLY_BEGIN", "APPLY_DONE", "ACK_ENQUEUED"])
                    lower_read = self.read(case_id, lower, "minecraft:cobblestone")
                finally:
                    restored_border = self.observer.result(case_id, "restoreBorder", self.world["uuid"])
                self.record("N05", case_id, subcases=cases, unchangedBeforeAllowedEdge=unchanged,
                            border=border, lowerInclusive={"position": lower, "reply": allowed,
                                                         "events": allowed_events, "snapshot": lower_read},
                            restoredBorder=restored_border, ready=self.ready(case_id, peer), wire=list(peer.events))

    def test_06_n06_loaded_only_rejection_does_not_load_chunk(self) -> None:
        case_id = self.case()
        position = [98304, self.world["maxYExclusive"] - 8, 98304]
        chunk = (self.world["uuid"], position[0] // 16, position[2] // 16)
        with self.prepared(case_id, [position]):
            unloaded = self.observer.result(case_id, "unload", *chunk, 200, timeout=20)
            self.assertFalse(unloaded["loaded"])
            self.assertFalse(unloaded["ticketHeld"])
            before_chunk = self.observer.result(case_id, "checkChunk", *chunk)
            self.assertFalse(before_chunk["loaded"])
            with RawPeer(token=self.harness.token) as peer:
                peer.hello()
                self.observer.result(case_id, "track", peer.session_id, 2)
                before = self.checkpoint(case_id)
                request = self.request(2, position)
                rejected = self.reject(peer, request, "CHUNK_NOT_LOADED")
                rejected_events = self.request_events(case_id, peer, 2, before, error="CHUNK_NOT_LOADED")
                after_chunk = self.observer.result(case_id, "checkChunk", *chunk)
                self.assertFalse(after_chunk["loaded"])
                self.assertFalse(after_chunk["ticketHeld"])
                ready = self.ready(case_id, peer)
                rejected_wire = list(peer.events)
        # Cleanup is an explicit fixture load. A new setup provides the fresh
        # AIR sentinel before resending exactly the same wire request.
        reloaded_case = self.case()
        with self.prepared(reloaded_case, [position]) as reloaded:
            with RawPeer(token=self.harness.token) as peer:
                peer.hello()
                self.observer.result(reloaded_case, "track", peer.session_id, 2)
                before = self.checkpoint(reloaded_case)
                peer.send(request)
                applied = peer.receive()
                self.assertEqual(applied, {"jsonrpc": "2.0", "id": 2, "result": {"applied": True}})
                events = self.request_events(reloaded_case, peer, 2, before)
                self.assertEqual([event["phase"] for event in events],
                                 ["QUEUED", "APPLY_BEGIN", "APPLY_DONE", "ACK_ENQUEUED"])
                self.assertLess(events[-2]["sequence"], events[-1]["sequence"])
                snapshot = self.read(reloaded_case, position, "minecraft:cobblestone")
                self.record("N06", case_id, unloaded=unloaded, beforeRequest=before_chunk,
                            rejection=rejected, rejectedEvents=rejected_events,
                            afterRequest=after_chunk, readyAfterRejection=ready, rejectedWire=rejected_wire,
                            reloadCaseId=reloaded_case, reloaded=reloaded,
                            sameRequest=request, success=applied, appliedEvents=events,
                            snapshot=snapshot, appliedWire=list(peer.events))
