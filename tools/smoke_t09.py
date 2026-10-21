"""Run the complete V/D matrix twice against fresh pinned Paper worlds.

Requires prebuilt artifacts and an installed wheel. Does not download/build,
accept EULA, change production configuration or delete previous runs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integration/tests"))

from conftest import Harness, PaperRun, sha256
from observer_client import ObserverClient
from test_observer import ObserverAcceptance
from test_vertical_slice import VerticalSliceAcceptance
from test_two_sessions import TwoSessionAcceptance
from wire_tap import WireTap

REQUIRED = [*(f"V{number:02}" for number in range(1, 8)),
            *(f"D{number:02}" for number in range(1, 5))]


def save(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def run_once(wheel: Path) -> dict:
    harness = Harness(wheel, stage="T09")
    harness.prepare()
    source_files = [ROOT / "tools/smoke_t09.py", *sorted((ROOT / "integration/tests").glob("*.py")),
                    ROOT / "integration/configs/server.properties"]
    harness.manifest["testSources"] = {path.relative_to(ROOT).as_posix(): sha256(path) for path in source_files}
    harness.manifest["requiredScenarios"] = REQUIRED
    harness.save_manifest()
    successful = False
    try:
        with PaperRun(harness, control=True) as paper:
            paper.wait_ready()
            observer = ObserverClient(paper, harness.artifacts / "control-enabled-observer.json")
            worlds = observer.result(observer.case_id(), "worlds")["worlds"]
            world = next(entry for entry in worlds if entry["name"] == harness.world_name)
            with WireTap(token=harness.token, evidence=harness.artifacts / "wire.json") as tap:
                harness.wiretap = tap
                harness.manifest["network"]["clientCapturePort"] = tap.port
                classes = (ObserverAcceptance, VerticalSliceAcceptance, TwoSessionAcceptance)
                for tests in classes:
                    tests.harness, tests.paper, tests.observer, tests.world = harness, paper, observer, world
                    tests.evidence = []
                suite = unittest.TestSuite([
                    ObserverAcceptance("test_01_oracle_preparation_read_correlation_and_cleanup"),
                    unittest.defaultTestLoader.loadTestsFromTestCase(VerticalSliceAcceptance),
                    unittest.defaultTestLoader.loadTestsFromTestCase(TwoSessionAcceptance),
                ])
                with (harness.artifacts / "control-enabled-tests.log").open("w", encoding="utf-8") as stream:
                    result = unittest.TextTestRunner(stream=stream, verbosity=2, failfast=True).run(suite)
                if not tap.wait_closed(timeout=8):
                    raise AssertionError("Captured client connections did not close")
                final_status = observer.await_value(
                    observer.case_id(), "status", (), lambda value: value["sessions"] == [])
                final_trace = observer.result(observer.case_id(), "trace", 0)
                if final_trace["droppedEvents"] or final_trace["evictedEvents"]:
                    raise AssertionError("The acceptance trace must be complete")
            outcome = paper.finish()
            checks = [*VerticalSliceAcceptance.evidence, *TwoSessionAcceptance.evidence]
            coverage = [check["id"] for check in checks]
            successful = (result.wasSuccessful() and not result.skipped and result.testsRun == 12
                          and len(coverage) == len(REQUIRED) and set(coverage) == set(REQUIRED))
            outcome.update({"passed": successful, "testsRun": result.testsRun,
                            "failures": len(result.failures), "errors": len(result.errors),
                            "skipped": len(result.skipped), "oracleChecks": ObserverAcceptance.evidence,
                            "checks": checks, "worlds": worlds, "coveredScenarios": coverage,
                            "finalStatus": final_status, "finalTrace": final_trace})
            harness.manifest["modes"].append(outcome)
            if any(sha256(path) != harness.manifest["testSources"][path.relative_to(ROOT).as_posix()]
                   for path in source_files):
                successful = False
                raise AssertionError("Integration test source changed during the run")
    finally:
        harness.manifest["allPassed"] = successful
        harness.save_manifest()
    if not successful:
        raise AssertionError("T09 matrix failed; inspect " + str(harness.artifacts))
    return harness.manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path,
                        default=ROOT / "dist/t09/minebridge-0.1.0.dev0-py3-none-any.whl")
    arguments = parser.parse_args()
    pointer = ROOT / ".work/t09-paper-results.json"
    pointer.parent.mkdir(parents=True, exist_ok=True)
    summary = {"stage": "T09", "allPassed": False, "requiredScenarios": REQUIRED,
               "runs": [], "scope": "Full V/D acceptance; N01-N10/F01-F05 remain T10"}
    save(pointer, summary)
    try:
        for _ in range(2):
            summary["runs"].append(run_once(arguments.wheel))
            save(pointer, summary)
        first, second = summary["runs"]
        if first["artifacts"] != second["artifacts"] or first["testSources"] != second["testSources"]:
            raise AssertionError("The clean repeated run used different artifacts or test sources")
        first_world = next(
            world["uuid"] for world in first["modes"][0]["worlds"] if world["name"] == "t09-world")
        second_world = next(world["uuid"] for world in second["modes"][0]["worlds"]
                            if world["name"] == "t09-world")
        if first["runId"] == second["runId"] or first_world == second_world:
            raise AssertionError("The repeated run must use a fresh directory and world")
        summary["allPassed"] = True
    finally:
        save(pointer, summary)
    print(json.dumps({"allPassed": summary["allPassed"], "runs": [
        {"runId": run["runId"], "testsRun": run["modes"][0]["testsRun"],
         "coveredScenarios": run["modes"][0]["coveredScenarios"],
         "manifest": str(ROOT / "integration/artifacts" / ("t09-" + run["runId"]) / "manifest.json")}
        for run in summary["runs"]]}, indent=2))


if __name__ == "__main__":
    main()
