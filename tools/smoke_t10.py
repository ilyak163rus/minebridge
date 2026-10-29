"""Execute the complete technical slice, a fresh V/D repeat and default-off smoke.

Uses prebuilt exact artifacts and fresh installed-wheel interpreters. No build,
download, EULA acceptance, global configuration change or deletion is performed.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integration/tests"))

from conftest import Harness, PaperRun, sha256
from observer_client import ObserverClient
from test_observer import ObserverAcceptance, ControlDisabledAcceptance
from test_vertical_slice import VerticalSliceAcceptance
from test_two_sessions import TwoSessionAcceptance
from test_validation import ValidationAcceptance
from test_protocol_edges import ProtocolEdgesAcceptance
from test_slow_reader import SlowReaderAcceptance
from test_failures import FaultAcceptance
from test_shutdown import ShutdownAcceptance
from wire_tap import WireTap

VD = [*(f"V{n:02}" for n in range(1, 8)), *(f"D{n:02}" for n in range(1, 5))]
NF = [*(f"N{n:02}" for n in range(1, 11)), *(f"F{n:02}" for n in range(1, 6))]


def save(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def configure(classes, harness, paper, observer, world) -> None:
    for tests in classes:
        tests.harness, tests.paper, tests.observer, tests.world = harness, paper, observer, world
        tests.evidence = []


def group(harness, paper, observer, world, name: str, classes: tuple, *, oracle=False) -> dict:
    configure(classes, harness, paper, observer, world)
    with WireTap(token=harness.token, evidence=harness.artifacts / (name + "-wire.json")) as tap:
        harness.wiretap = tap
        suite = unittest.TestSuite()
        if oracle:
            configure((ObserverAcceptance,), harness, paper, observer, world)
            suite.addTest(ObserverAcceptance("test_01_oracle_preparation_read_correlation_and_cleanup"))
        for tests in classes:
            suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(tests))
        expected = suite.countTestCases()
        with (harness.artifacts / (name + "-tests.log")).open("w", encoding="utf-8") as stream:
            result = unittest.TextTestRunner(stream=stream, verbosity=2, failfast=True).run(suite)
        endpoints_closed = tap.wait_closed(timeout=8)
        status = None
        trace = None
        if paper.process.poll() is None:
            status = observer.await_value(observer.case_id(), "status", (), lambda value: value["sessions"] == [])
            trace = observer.result(observer.case_id(), "trace", 0)
            if trace["droppedEvents"]:
                raise AssertionError("Diagnostic publication lost events")
    # A later ordinary-mode client must connect to Paper, not a closed capture listener.
    harness.wiretap = None
    checks = [item for tests in classes for item in tests.evidence]
    outcome = {"name": name, "passed": result.wasSuccessful() and not result.skipped and endpoints_closed
               and result.testsRun == expected, "testsRun": result.testsRun, "expectedTests": expected,
               "failures": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped),
               "checks": checks, "clientCapturePort": tap.port, "endpointsClosed": endpoints_closed,
               "finalStatus": status, "traceSnapshot": trace}
    if oracle:
        outcome["oracleChecks"] = ObserverAcceptance.evidence
    harness.manifest.setdefault("groups", []).append(outcome)
    harness.save_manifest()
    if not outcome["passed"]:
        raise AssertionError("T10 group failed; inspect " + str(harness.artifacts / (name + "-tests.log")))
    return outcome


def run(wheel: Path, *, full: bool) -> dict:
    harness = Harness(wheel, stage="T10")
    harness.prepare()
    sources = [ROOT / "tools/smoke_t10.py", *sorted((ROOT / "integration/tests").glob("*.py")),
               ROOT / "integration/configs/server.properties",
               *sorted((ROOT / "plugin/src/main").rglob("*.java")),
               *sorted((ROOT / "integration/observer-plugin/src/main").rglob("*.java"))]
    harness.manifest.update({"testSources": {path.relative_to(ROOT).as_posix(): sha256(path) for path in sources},
                             "requiredScenarios": VD + NF if full else VD, "fullMatrix": full,
                             "groups": [], "ideRequirement": "VS Code/Python/Pylance; PyCharm waived by user 2026-10-22"})
    harness.save_manifest()
    successful = False
    try:
        with PaperRun(harness, control=True, mode="primary" if full else "repeat") as paper:
            paper.wait_ready()
            observer = ObserverClient(paper, harness.artifacts / (paper.mode + "-observer.json"))
            worlds = observer.result(observer.case_id(), "worlds")["worlds"]
            world = next(item for item in worlds if item["name"] == harness.world_name)
            group(harness, paper, observer, world, "vertical", (VerticalSliceAcceptance, TwoSessionAcceptance), oracle=True)
            if full:
                group(harness, paper, observer, world, "validation", (ValidationAcceptance,))
                group(harness, paper, observer, world, "protocol", (ProtocolEdgesAcceptance,))
                group(harness, paper, observer, world, "slow-reader", (SlowReaderAcceptance,))
                group(harness, paper, observer, world, "faults", (FaultAcceptance,))
                group(harness, paper, observer, world, "shutdown", (ShutdownAcceptance,))
            outcome = paper.finish()
            outcome["worlds"] = worlds
            harness.manifest["modes"].append(outcome)
        checks = [item for item_group in harness.manifest["groups"] for item in item_group["checks"]]
        required = set(VD + NF if full else VD)
        coverage = Counter(item["id"] for item in checks)
        expected_coverage = Counter(required)
        if full:
            expected_coverage["N07"] = 2
            expected_coverage["N10"] = 5
        if coverage != expected_coverage:
            raise AssertionError("Required scenario/subcase coverage is incomplete")
        harness.manifest["coveredScenarios"] = dict(coverage)
        if not full:
            with PaperRun(harness, control=False, mode="default-off") as plain:
                plain.wait_ready()
                observer = ObserverClient(plain, harness.artifacts / "default-off-observer.json")
                worlds = observer.result(observer.case_id(), "worlds")["worlds"]
                world = next(item for item in worlds if item["name"] == harness.world_name)
                configure((ControlDisabledAcceptance,), harness, plain, observer, world)
                suite = unittest.defaultTestLoader.loadTestsFromTestCase(ControlDisabledAcceptance)
                with (harness.artifacts / "default-off-tests.log").open("w", encoding="utf-8") as stream:
                    result = unittest.TextTestRunner(stream=stream, verbosity=2, failfast=True).run(suite)
                disabled = observer.call(observer.case_id(), "writerPause", "00000000-0000-0000-0000-000000000000",
                                         expected_error="CONTROL_DISABLED")
                mode = plain.finish()
                mode.update({"passed": result.wasSuccessful() and not result.skipped and result.testsRun == 1,
                             "testsRun": result.testsRun, "failures": len(result.failures),
                             "errors": len(result.errors), "skipped": len(result.skipped),
                             "checks": ControlDisabledAcceptance.evidence, "writerControlDisabled": disabled})
                harness.manifest["modes"].append(mode)
                if not mode["passed"]:
                    raise AssertionError("Default-off production smoke failed")
        if any(sha256(path) != harness.manifest["testSources"][path.relative_to(ROOT).as_posix()] for path in sources):
            raise AssertionError("Sources changed during acceptance")
        if any(sha256(Path(item["path"])) != item["sha256"] for item in harness.manifest["artifacts"].values()):
            raise AssertionError("An acceptance artifact changed during the run")
        successful = True
    finally:
        harness.manifest["allPassed"] = successful
        harness.save_manifest()
    return harness.manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, default=ROOT / "dist/t10/minebridge-0.1.0.dev0-py3-none-any.whl")
    args = parser.parse_args()
    path = ROOT / ".work/t10-paper-results.json"
    summary = {"stage": "T10", "allPassed": False, "runs": []}
    save(path, summary)
    try:
        for full in (True, False):
            summary["runs"].append(run(args.wheel, full=full))
            save(path, summary)
        a, b = summary["runs"]
        if a["artifacts"] != b["artifacts"] or a["testSources"] != b["testSources"]:
            raise AssertionError("The clean repeat used different artifacts or sources")
        uuids = [next(world["uuid"] for world in item["modes"][0]["worlds"]
                      if world["name"] == "t10-world") for item in (a, b)]
        if a["runId"] == b["runId"] or uuids[0] == uuids[1]:
            raise AssertionError("The main-path repeat must use a fresh world")
        summary["allPassed"] = True
    finally:
        save(path, summary)
    print(json.dumps({"allPassed": True, "runs": [{"runId": item["runId"],
          "fullMatrix": item["fullMatrix"], "coveredScenarios": item["coveredScenarios"]}
          for item in summary["runs"]]}, indent=2))


if __name__ == "__main__":
    main()
