"""T10 F04: stop with two pending public clients, then reuse the saved world.

The explicit orchestrator supplies the first Paper process and passive wire
capture. This final case owns its stop and the bounded restart of that server.
"""

from __future__ import annotations

import time

from conftest import FacadeClient, PaperRun
from observer_client import ObserverClient
from t09_support import PaperAcceptance


class ShutdownAcceptance(PaperAcceptance):
    def test_F04_stop_pending_sessions_and_restart_accepts_fresh_create(self) -> None:
        case_id = self.case()
        primary, observer, world = self.paper, self.observer, self.world
        y = world["maxYExclusive"] - 8
        positions = [[98304, y, 98304], [-98304, y, 98304],
                     [98304, world["minY"], 98304]]
        # This case deliberately survives until onDisable. A prepared() context
        # would attempt a console cleanup after its Paper process has stopped.
        setup = observer.result(case_id, "setup", world["uuid"],
                                *("%d,%d,%d" % tuple(position) for position in positions))
        self.assertEqual(len(setup["originals"]), len(positions))
        self.assertEqual(len(setup["snapshots"]), len(positions))
        self.assertNotEqual(setup["originals"][-1]["key"], "minecraft:air")
        self.assertTrue(all(chunk["loaded"] and chunk["ticketHeld"] for chunk in setup["chunks"]))
        baseline = [self.read(case_id, position, "minecraft:air") for position in positions]

        with FacadeClient(self.harness, "F04-A", timeout=20.0) as a, \
                FacadeClient(self.harness, "F04-B", timeout=20.0) as b:
            clients = [a, b]
            contexts = [client.context for client in clients]
            self.assertNotEqual(a.context["pid"], b.context["pid"])
            self.assertNotEqual(a.context["sessionId"], b.context["sessionId"])
            ready = observer.result(case_id, "status")
            self.assertTrue(ready["controlEnabled"])
            sessions = {session["sessionId"]: session for session in ready["sessions"]}
            for client in clients:
                self.assertEqual(client.context["world"], world)
                self.assertIsNone(client.process.poll())
                session = sessions[client.context["sessionId"]]
                self.assertTrue(session["open"])
                self.assertTrue(session["ready"])
                observer.result(case_id, "gateArm", client.context["sessionId"], 2)
            commands = [a.set(positions[0], "COBBLESTONE"), b.set(positions[1], "STONE")]
            gated = []
            for client in clients:
                held = observer.await_value(
                    case_id, "gateStatus", (client.context["sessionId"], 2),
                    lambda value: value["state"] == "GATED")
                self.assertTrue(held["sessionOpen"])
                self.assertEqual(held["queuedRequests"], 1)
                gated.append(held)
                client.assert_pending()
            before_stop = [self.read(case_id, position, "minecraft:air") for position in positions]
            trace_before_stop = self.trace(case_id)
            for client in clients:
                events = [event for event in trace_before_stop["events"]
                          if event["sessionId"] == client.context["sessionId"]
                          and event["requestId"] == 2]
                self.assertEqual([event["phase"] for event in events], ["QUEUED"])
                client.assert_pending()

            stop_started = time.monotonic()
            stopped = primary.finish()
            failures = []
            for client, command in zip(clients, commands):
                failure = client.response(timeout=10)
                self.assertEqual(failure.get("type"), "result")
                self.assertEqual(failure.get("commandId"), command)
                self.assertIs(failure.get("ok"), False)
                self.assertIn((failure.get("error"), failure.get("code")),
                              (("ConnectionError", "CONNECTION_LOST"),
                               ("OperationTimeoutError", "TIMEOUT")))
                self.assertEqual(failure.get("outcome"), "unknown")
                failures.append(failure)
            stopped["clientsCompletedSeconds"] = time.monotonic() - stop_started
            closed = [client.close() for client in clients]
        self.assertTrue(self.harness.wiretap.wait_closed(timeout=8))
        old_wire = [self.wire(client) for client in clients]
        for frames in old_wire:
            self.assertEqual([event["frame"]["method"] for event in frames
                              if event["direction"] == "request"], ["system.hello", "blocks.set"])
            self.assertFalse(any(event["direction"] == "response"
                                 and event["frame"].get("id") == 2 for event in frames))

        try:
            with PaperRun(self.harness, control=True, mode="restart") as restarted:
                restarted.wait_ready()
                self.assertNotEqual(restarted.process.pid, primary.process.pid)
                new_observer = ObserverClient(restarted, self.harness.artifacts / "restart-observer.json")
                worlds = new_observer.result(new_observer.case_id(), "worlds")["worlds"]
                new_world = next(entry for entry in worlds if entry["name"] == world["name"])
                self.assertEqual(new_world, world)
                self.paper, self.observer, self.world = restarted, new_observer, new_world
                restart_case = self.case()
                with self.prepared(restart_case, positions) as restored:
                    # setup captures the saved world before clearing it. The
                    # minY witness was non-AIR before the first setup and AIR
                    # before stop, so equality proves onDisable restoration.
                    self.assertEqual(restored["originals"], setup["originals"])
                    restored_originals = restored["originals"]
                    with FacadeClient(self.harness, "F04-restarted") as fresh:
                        fresh_context = fresh.context
                        self.assertEqual(fresh.context["world"], new_world)
                        self.assertNotIn(fresh.context["sessionId"],
                                         [context["sessionId"] for context in contexts])
                        fresh_ready = new_observer.result(restart_case, "status")
                        active = next(session for session in fresh_ready["sessions"]
                                      if session["sessionId"] == fresh.context["sessionId"])
                        self.assertTrue(active["open"])
                        self.assertTrue(active["ready"])
                        new_observer.result(restart_case, "track", fresh.context["sessionId"], 2)
                        returned = fresh.success(fresh.set(positions[0], "COBBLESTONE"))
                        application = self.assert_applied(
                            restart_case, fresh, 2, positions[0], "minecraft:cobblestone")
                final_status = new_observer.await_value(
                    restart_case, "status", (), lambda value: value["sessions"] == [])
                self.assertTrue(self.harness.wiretap.wait_closed(timeout=8))
                restart_outcome = restarted.finish()
                restart_outcome.update({"worlds": worlds, "finalStatus": final_status,
                                        "freshSessionId": fresh_context["sessionId"]})
                self.harness.manifest.setdefault("restarts", []).append(restart_outcome)
        finally:
            self.paper, self.observer, self.world = primary, observer, world

        self.record("F04", case_id, clients=contexts, simultaneousReady=ready,
                    setup=setup, baseline=baseline, gated=gated, pendingBeforeStop=True,
                    beforeStop=before_stop, traceBeforeStop=trace_before_stop,
                    stopped=stopped, clientFailures=failures, clientClose=closed,
                    oldWire=old_wire, restartCaseId=restart_case,
                    restoredOriginals=restored_originals, restarted=restart_outcome,
                    freshClient=fresh_context, freshReady=fresh_ready, freshReturn=returned,
                    freshApplication=application,
                    automaticRetries=0)
