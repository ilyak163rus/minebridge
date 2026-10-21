"""Run the T08 independent observer/gate acceptance with prebuilt artifacts.

No build, installation, download, EULA acceptance or recursive removal occurs.
The Python bridge uses 127.0.0.1:4711, which must be free before the run.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integration/tests"))

from conftest import Harness, PaperRun, WORLD_NAME
from observer_client import ObserverClient
from test_observer import ObserverAcceptance, ControlDisabledAcceptance


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path,
                        default=ROOT / "dist/t08/minebridge-0.1.0.dev0-py3-none-any.whl")
    arguments = parser.parse_args()
    harness = Harness(arguments.wheel)
    pointer = ROOT / ".work/t08-paper-results.json"
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(json.dumps({"allPassed": False, "runId": harness.run_id,
                                  "artifacts": str(harness.artifacts)}, indent=2) + "\n", encoding="utf-8")
    harness.prepare()
    all_passed = False
    try:
        production_hash = harness.manifest["artifacts"]["production"]["sha256"]
        for control, tests in ((True, ObserverAcceptance), (False, ControlDisabledAcceptance)):
            mode = "control-enabled" if control else "control-disabled"
            tests.evidence = []
            with PaperRun(harness, control=control) as paper:
                paper.wait_ready()
                observer = ObserverClient(paper, harness.artifacts / (mode + "-observer.json"))
                case_id = observer.case_id()
                worlds = observer.result(case_id, "worlds")["worlds"]
                world = next(entry for entry in worlds if entry["name"] == WORLD_NAME)
                tests.harness, tests.paper, tests.observer, tests.world = harness, paper, observer, world
                suite = unittest.defaultTestLoader.loadTestsFromTestCase(tests)
                with (harness.artifacts / (mode + "-tests.log")).open("w", encoding="utf-8") as stream:
                    result = unittest.TextTestRunner(stream=stream, verbosity=2, failfast=True).run(suite)
                outcome = paper.finish()
                if outcome["productionSha256"] != production_hash:
                    raise AssertionError("Production JAR changed between opt-in and ordinary modes")
                outcome.update({"testsRun": result.testsRun, "failures": len(result.failures),
                                "errors": len(result.errors), "skipped": len(result.skipped),
                                "checks": tests.evidence, "worlds": worlds})
                harness.manifest["modes"].append(outcome)
                harness.save_manifest()
                if not result.wasSuccessful() or result.skipped:
                    raise AssertionError("T08 server acceptance failed; inspect " + str(harness.artifacts))
        all_passed = True
    finally:
        harness.manifest["allPassed"] = all_passed
        harness.save_manifest()
        pointer.write_text(json.dumps(harness.manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"allPassed": True, "runId": harness.run_id,
                      "manifest": str(harness.artifacts / "manifest.json"),
                      "modes": [{"mode": mode["mode"], "testsRun": mode["testsRun"]}
                                for mode in harness.manifest["modes"]]}, indent=2))


if __name__ == "__main__":
    main()
