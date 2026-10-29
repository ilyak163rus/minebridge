"""N10: a real Paper socket reaches backpressure with a non-reading peer.

The receive buffer is reduced before connect. No writer-pause control is used;
ordinary small error replies fill the actual TCP buffers. Request batches,
observer calls, retained diagnostics, bytes and elapsed time all have bounds.
"""

from __future__ import annotations

import json
import socket
import time

from conftest import FacadeClient
from raw_peer import RawPeer
from t09_support import PaperAcceptance


class SlowReaderAcceptance(PaperAcceptance):
    def test_n10_kernel_slow_reader_closes_while_another_session_progresses(self) -> None:
        case_id = self.case()
        y = self.world["maxYExclusive"] - 8
        positions = [[24704, y, 24576], [24705, y, 24576]]
        max_rounds, max_observations = 1500, 1800
        observer_calls = 0
        began = time.monotonic()
        deadline = began + 120
        high_water = {"request": 0, "output": 0}
        sample = None

        with self.prepared(case_id, positions):
            with FacadeClient(self.harness, "N10-kernel-slow-B") as b:
                peer = RawPeer(token=self.harness.token)
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as endpoint:
                    endpoint.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
                    receive_buffer = endpoint.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)
                    endpoint.settimeout(8)
                    endpoint.connect((peer.host, peer.port))
                    peer.socket = endpoint
                    peer.hello()
                    self.assertEqual(peer.buffer, bytearray())
                    self.observer.result(case_id, "track", peer.session_id, 2)

                    def stats() -> dict:
                        nonlocal observer_calls, sample
                        self.assertLess(observer_calls, max_observations,
                                        "The bounded real-socket observation budget was exhausted")
                        self.assertLess(time.monotonic(), deadline,
                                        "The real-socket backpressure deadline elapsed")
                        observer_calls += 1
                        sample = self.observer.call(case_id, "sessionStats", peer.session_id)
                        value = sample["result"]
                        self.assertFalse(value["writerPaused"])
                        self.assertLessEqual(value["queuedRequests"], 8)
                        self.assertLessEqual(value["outputFrames"], 8)
                        self.assertLessEqual(value["requestHighWater"], 8)
                        self.assertLessEqual(value["outputHighWater"], 8)
                        high_water["request"] = max(high_water["request"], value["requestHighWater"])
                        high_water["output"] = max(high_water["output"], value["outputHighWater"])
                        return value

                    initial = stats()
                    self.assertTrue(initial["ready"] and initial["open"])
                    self.assertEqual(initial["outputFrames"], 0)
                    self.assertEqual(initial["receivedFrames"], 1)
                    self.observer.result(case_id, "track", b.context["sessionId"], 2)
                    before_return = b.success(b.set(positions[1], "STONE"))
                    before_application = self.assert_applied(case_id, b, 2, positions[1], "minecraft:stone")

                    # After hello there are deliberately no recv calls until
                    # independent observer state confirms server-side close.
                    sent, rounds = 0, 0
                    backpressure = None
                    for rounds in range(1, max_rounds + 1):
                        frames = [{"jsonrpc": "2.0", "id": rpc_id,
                                   "method": "future.kernel_slow_reader", "params": {}}
                                  for rpc_id in range(sent + 2, sent + 6)]
                        payload = b"".join(json.dumps(frame, separators=(",", ":")).encode("utf-8") + b"\n"
                                           for frame in frames)
                        peer.send_bytes(payload)
                        sent += 4
                        # Accept all four complete frames and finish dispatch
                        # before another batch. Neither application queue is
                        # flooded merely to manufacture an overflow closure.
                        while True:
                            value = stats()
                            self.assertTrue(value["open"],
                                            "The socket closed before live kernel backpressure was observed")
                            if value["receivedFrames"] == sent + 1 and value["queuedRequests"] == 0:
                                break
                        self.assertEqual(value["partialFrameBytes"], 0)
                        if value["outputFrames"] == 0:
                            continue
                        pending_tick = sample["tick"]
                        pending = dict(value)
                        # A normal publication may be sampled just before the
                        # reactor drains it. Require pending output over real
                        # Paper ticks with no new requests and no socket reads.
                        while value["open"] and value["outputFrames"]:
                            if sample["tick"] - pending_tick >= 3:
                                backpressure = {"first": pending, "confirmed": dict(value),
                                                "firstTick": pending_tick, "confirmedTick": sample["tick"],
                                                "requestFrames": sent, "rounds": rounds}
                                break
                            value = stats()
                        self.assertTrue(value["open"],
                                        "The socket closed before concurrent progress could be checked")
                        if backpressure is not None:
                            break
                    self.assertIsNotNone(backpressure,
                                         "The finite real-socket load did not reach TCP backpressure")

                    flood_trace = self.observer.result(case_id, "trace", 0)
                    self.assertEqual(flood_trace["droppedEvents"], 0)
                    # The intentional stream can evict historical ERROR events.
                    # Preserve the earlier B proof and start a new complete
                    # interval for B's concurrent operation after A stops sending.
                    self.harness.trace_offsets[case_id] = flood_trace["latestSequence"]
                    self.observer.result(case_id, "track", b.context["sessionId"], 3)
                    concurrent_return = b.success(b.set(positions[1], "COBBLESTONE"))
                    concurrent_application = self.assert_applied(case_id, b, 3, positions[1],
                                                                 "minecraft:cobblestone")
                    concurrent = stats()
                    self.assertTrue(concurrent["open"], "Slow socket must remain live while B completes")
                    self.assertGreater(concurrent["outputFrames"], 0)
                    self.assertGreater(concurrent_application["snapshot"]["tick"],
                                       backpressure["firstTick"])
                    during_progress = dict(concurrent)
                    while concurrent["open"]:
                        concurrent = stats()
                    closed = dict(concurrent)
                    self.assertEqual(closed["queuedRequests"], 0)
                    self.assertEqual(closed["outputFrames"], 0)
                    self.assertEqual(closed["receivedFrames"], sent + 1)
                    untouched = self.read(case_id, positions[0], "minecraft:air")

                    # Drain only after server close. Keep counts rather than a
                    # list of thousands of decoded frames. A deadline may cut
                    # off a partially written final frame; that prefix is a
                    # permitted transport outcome, never an RPC response.
                    drain_deadline = time.monotonic() + 15
                    buffer = bytearray(peer.buffer)
                    received_bytes, response_frames = len(buffer), 0
                    while True:
                        remaining = drain_deadline - time.monotonic()
                        self.assertGreater(remaining, 0, "Closed socket did not reach a terminal read")
                        endpoint.settimeout(remaining)
                        try:
                            chunk = endpoint.recv(8192)
                        except ConnectionResetError:
                            chunk = b""
                        if not chunk:
                            break
                        received_bytes += len(chunk)
                        self.assertLessEqual(received_bytes, sent * 512 + RawPeer.MAX_FRAME_BYTES)
                        buffer.extend(chunk)
                        while b"\n" in buffer:
                            split = buffer.index(b"\n")
                            self.assertLessEqual(split, RawPeer.MAX_FRAME_BYTES)
                            frame = json.loads(bytes(buffer[:split]).decode("utf-8"))
                            del buffer[:split + 1]
                            self.assertEqual(frame.get("jsonrpc"), "2.0")
                            self.assertEqual(frame.get("id"), response_frames + 2)
                            self.assertNotIn("result", frame)
                            self.assertEqual(frame["error"]["code"], -32601)
                            self.assertEqual(frame["error"]["data"],
                                             {"code": "METHOD_NOT_FOUND", "outcome": "not-applied"})
                            response_frames += 1
                            self.assertLessEqual(response_frames, sent)
                        self.assertLessEqual(len(buffer), RawPeer.MAX_FRAME_BYTES)
                    peer.eof = True
                    self.assertGreater(response_frames, 0)
                    self.assertLess(response_frames, sent)

                    with RawPeer(token=self.harness.token) as recovered:
                        recovered.hello()
                        self.assertNotEqual(recovered.session_id, peer.session_id)
                        self.observer.result(case_id, "track", recovered.session_id, 2)
                        recovered.send({"jsonrpc": "2.0", "id": 2, "method": "blocks.set",
                                        "params": {"world": self.world["name"], "position": positions[0],
                                                   "block": {"key": "minecraft:cobblestone", "states": {}}}})
                        recovery_ack = recovered.receive()
                        self.assertEqual(recovery_ack, {"jsonrpc": "2.0", "id": 2,
                                                        "result": {"applied": True}})
                        recovered_snapshot = self.read(case_id, positions[0], "minecraft:cobblestone")
                        recovered_events = [event for event in self.trace(case_id)["events"]
                                            if event["sessionId"] == recovered.session_id
                                            and event["requestId"] == 2]
                        self.assertEqual([event["phase"] for event in recovered_events],
                                         ["QUEUED", "APPLY_BEGIN", "APPLY_DONE", "ACK_ENQUEUED"])
                        self.record("N10", case_id, subcase="kernel-slow-reader", context=peer.context,
                                    requestedReceiveBuffer=1024, actualReceiveBuffer=receive_buffer,
                                    initial=initial, requestFrames=sent, rounds=rounds,
                                    observerCalls=observer_calls, highWater=high_water,
                                    backpressure=backpressure, duringBProgress=during_progress, closed=closed,
                                    floodTraceRetention={key: flood_trace[key] for key in
                                                         ("latestSequence", "oldestSequence",
                                                          "droppedEvents", "evictedEvents")},
                                    beforeReturn=before_return, beforeApplication=before_application,
                                    concurrentReturn=concurrent_return, concurrentApplication=concurrent_application,
                                    untouched=untouched, drainedResponseFrames=response_frames,
                                    drainedBytes=received_bytes, trailingPartialBytes=len(buffer), eof=True,
                                    recovered={"context": recovered.context, "ack": recovery_ack,
                                               "snapshot": recovered_snapshot, "events": recovered_events},
                                    writerPauseUsed=False, elapsedSeconds=time.monotonic() - began)
