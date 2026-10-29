"""Write RELEASE.json only after matching local build and acceptance proofs pass.

No artifacts are rebuilt, installed, uploaded or otherwise changed. This local
release gate requires installed Python 3.11/3.14 tests, a current/baseline Paper
comparison and a real IDE proof. Cloud CI/publication is not implied.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import urllib.parse
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_release import describe, historical_artifacts, production_inputs, save, sha256

PAPER_SHA256 = "bf1dcf627364f8a631ab15250d240eb5a8e89faaac523b391e1c61367fce9ff1"


def require(condition: object, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def resolve(value: str | Path) -> Path:
    path = Path(value)
    return (path if path.is_absolute() else ROOT / path).resolve()


def load(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(document, dict), "Expected a JSON object: " + str(path))
    return document


def verify_file(row: dict) -> Path:
    path = resolve(row["path"])
    require(path.is_file() and sha256(path) == row["sha256"], "Evidence/artifact bytes changed: " + str(path))
    if "bytes" in row:
        require(path.stat().st_size == row["bytes"], "Evidence/artifact size changed: " + str(path))
    return path


def manifest_paths(value: object) -> set[Path]:
    if isinstance(value, dict):
        return set().union(*(manifest_paths(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(manifest_paths(item) for item in value))
    return {resolve(value)} if isinstance(value, str) and value.endswith("manifest.json") else set()


def check_documents(output: Path, evidence: set[Path]) -> list[dict]:
    names = ["README.md", "python/README.md", "LICENSE", "THIRD_PARTY_NOTICES.md",
             "CONTRIBUTING.md", "CHANGELOG.md", "docs/QUICKSTART.ru.md", "docs/API_V0_3.ru.md",
             "docs/PUBLISHING.ru.md"]
    paths = [ROOT / name for name in names]
    if (output / "README.ru.md").is_file():
        paths.append(output / "README.ru.md")
    results = []
    for path in paths:
        require(path.is_file(), "Publication document is missing: " + str(path))
        for link in re.findall(r"\[[^\]]*\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
            if "://" in link or link.startswith(("#", "mailto:")):
                continue
            target = urllib.parse.unquote(link.split("#", 1)[0].strip("<>"))
            linked = (path.parent / target).resolve()
            require(linked.is_file() or linked.is_dir() or linked == output / "RELEASE.json",
                    f"Broken local documentation link in {path}: {link}")
        evidence.add(path)
        results.append(describe(path))
    return results


def finalize(args: argparse.Namespace) -> dict:
    paths = {name: resolve(getattr(args, name)) for name in ("build", "package", "python_tests", "paper", "ide")}
    build, package, python, paper, ide = (load(paths[name]) for name in ("build", "package", "python_tests", "paper", "ide"))
    require(build.get("buildPassed") is True and package.get("passed") is True and python.get("passed") is True,
            "Build, archive audit and installed Python tests must pass")
    require(paper.get("allPassed") is True, "Paper acceptance has not passed; no RELEASE.json was written")
    require(ide.get("status") == "passed", "IDE acceptance has not passed")
    version = build["version"]
    output = paths["build"].parent
    require(package.get("version") == python.get("version") == version, "Acceptance versions differ")
    require(production_inputs() == build["productionInputs"], "Production inputs changed after building")
    require(historical_artifacts(output) == build["historicalArtifacts"], "Historical dist files changed")
    evidence = set(paths.values())
    artifacts = build["artifacts"]
    for row in [*artifacts, *build["historicalArtifacts"], *build.get("logs", [])]:
        evidence.add(verify_file(row))
    java = build["java"]
    require(java.get("tests", 0) > 0 and all(java.get(name) == 0 for name in ("errors", "failures", "skipped")),
            "Java test evidence is incomplete or contains failures/skips")
    wheel_row = next(row for row in artifacts if row["path"].endswith(".whl"))
    wheel = resolve(wheel_row["path"])
    for row in package["artifacts"].values():
        require(any(row["sha256"] == item["sha256"] and resolve(row["path"]).name == resolve(item["path"]).name for item in artifacts),
                "Archive audit used another candidate")
        evidence.add(verify_file(row))
    require(package.get("recordVerified") is True and package.get("sdistMatchesWheelPackage") is True
            and package.get("twineStrict") is True and package.get("metadata", {}).get("licenseExpression") == "MIT",
            "Packaging metadata/license/RECORD gates did not pass")
    require(package.get("sourceDateEpoch") == build["sourceDateEpoch"], "Build/audit SOURCE_DATE_EPOCH differs")
    sums = output / "SHA256SUMS.txt"
    checksums = dict((name.strip(), digest) for digest, name in
                     (line.split(None, 1) for line in sums.read_text(encoding="utf-8").splitlines() if line.strip()))
    require(checksums == {resolve(row["path"]).name: row["sha256"] for row in artifacts}, "SHA256SUMS differs")
    evidence.add(sums)

    python_runs = []
    python_minors = set()
    for run in python.get("runs", []):
        require(run.get("version") == version and run.get("isolated") is True
                and run.get("tests", 0) > 0 and run.get("skipped") == 0, "Installed Python run is incomplete")
        log = resolve(run["log"])
        require(sha256(log) == run["logSha256"], "Python test log changed")
        text = log.read_text(encoding="utf-8")
        require(re.search(rf"Ran {run['tests']} tests", text) and re.search(r"(?m)^OK\s*$", text)
                and "skipped=" not in text, "Python test log disagrees with the summary")
        audited = [item for item in package.get("installedInterpreters", []) if resolve(item["executable"]) == resolve(run["executable"])]
        require(len(audited) == 1 and audited[0].get("version") == version
                and audited[0].get("networkAttempts") == 0
                and audited[0].get("packageFilesVerified") == package["packageFiles"], "Python run is not bound to the audited installed wheel")
        python_minors.add(".".join(run["python"].split()[0].split(".")[:2]))
        evidence.add(log)
        python_runs.append({"python": run["python"], "version": version, "tests": run["tests"],
                            "skipped": 0, "isolated": True, "installedWheelVerified": True,
                            "log": describe(log)["path"], "logSha256": run["logSha256"]})
    require({"3.11", "3.14"} <= python_minors, "Both Python 3.11 and 3.14 installed runs are required")

    artifact_check = ide.get("artifactValidation", {})
    require(artifact_check.get("status") == "passed" and artifact_check.get("wheelSha256") == wheel_row["sha256"],
            "IDE did not verify the delivered wheel")
    with zipfile.ZipFile(wheel) as archive:
        file_hashes = {name: hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist() if name.startswith("minebridge/")}
    require(artifact_check.get("installedFileSha256") == file_hashes, "IDE package bytes differ from the delivered wheel")
    helper_dir = ROOT / "python/tests" / paths["ide"].name.removesuffix("-results.json")
    for name, digest in artifact_check.get("helperSha256", {}).items():
        helper = (helper_dir / name).resolve()
        require(helper.is_relative_to(helper_dir.resolve()) and helper.is_file() and sha256(helper) == digest,
                "IDE helper changed after verification: " + str(helper))
        evidence.add(helper)

    manifests = []
    current = baseline = False
    for path in sorted(manifest_paths(paper)):
        document = load(path)
        require(document.get("allPassed") is True and document.get("checks")
                and all(check.get("passed") is True for check in document["checks"]), "A referenced Paper manifest did not pass")
        modes = document.get("modes", [])
        require(modes and all(mode.get("passed") is True and mode.get("exitCode") == 0 for mode in modes),
                "Paper did not stop cleanly")
        is_current = document.get("version") == version
        current |= is_current
        baseline |= not is_current
        if not is_current:
            require(any(key.startswith("baseline") and value is True for key, value in document.items()), "Unlabelled historical Paper run")
        expected = artifacts if is_current else build["historicalArtifacts"]
        for name, suffix in (("production", ".jar"), ("wheel", ".whl")):
            row = document["artifacts"][name]
            matches = [item for item in expected if item["path"].endswith(suffix)
                       and resolve(item["path"]).name == resolve(row["path"]).name and item["sha256"] == row["sha256"]]
            require(len(matches) == 1, "Paper used an unverified current/baseline artifact")
            evidence.add(verify_file(row))
        require(document["artifacts"]["paper"]["sha256"] == PAPER_SHA256, "Paper server differs from pinned 26.2 build 133")
        for row in document["artifacts"].values():
            evidence.add(verify_file(row))
        for name, digest in document.get("scripts", {}).items():
            script = resolve(name)
            require(script.is_file() and sha256(script) == digest, "Paper fixture changed after acceptance: " + str(script))
            evidence.add(script)
        for mode in modes:
            evidence.add(resolve(mode["log"]))
        evidence.add(path)
        manifests.append({"path": describe(path)["path"], "runId": document["runId"], "version": document.get("version"),
                          "baseline": not is_current, "checksPassed": len(document["checks"]), "allPassed": True,
                          "shutdownExitCodes": [mode["exitCode"] for mode in modes]})
    require(current and baseline, "Current and historical-baseline Paper manifests are required")

    workflow_path = resolve(args.workflow_validation)
    workflows = load(workflow_path)
    require(workflows.get("passed") is True and workflows.get("githubActionsExecuted") is False
            and workflows.get("published") is False, "Local workflow validation must pass without claiming cloud CI/publication")
    evidence.add(workflow_path)
    workflow_sources = sorted((ROOT / ".github/workflows").glob("*.y*ml"))
    require(workflow_sources, "Publication workflows are missing")
    for row in workflows.get("files", []):
        evidence.add(verify_file(row))
    evidence.update(workflow_sources)
    documentation = check_documents(output, evidence)
    tools = [ROOT / "tools" / name for name in ("build_release.py", "check_release.py", "finalize_release.py")]
    evidence.update(tools)
    release = {"schemaVersion": 1, "project": "Minebridge", "version": version, "license": "MIT", "protocol": "2.0",
               "releaseDate": build["releaseDate"], "pathsRelativeTo": "repository root", "artifacts": artifacts,
               "productionInputs": build["productionInputs"], "historicalArtifacts": build["historicalArtifacts"],
               "verification": {"passed": True, "java": java, "pythonInstalledRuns": python_runs,
                    "package": {name: package[name] for name in ("metadata", "wheelEntries", "packageFiles", "registryCounts",
                        "recordVerified", "sdistMatchesWheelPackage", "twineStrict", "jarAudit")},
                    "paper": {"allPassed": True, "minecraft": "26.2", "build": 133, "serverSha256": PAPER_SHA256,
                              "manifests": manifests, "scope": "Local two-process/two-game-client acceptance; no classroom/LAN load claim"},
                    "ide": {"status": "passed", "vscode": ide["vscode"], "wheelSha256": wheel_row["sha256"],
                            "extensions": {name: value["version"] if isinstance(value, dict) else value for name, value in ide["extensions"].items()},
                            "completions": list(ide.get("completions", {})), "signatures": list(ide.get("signatures", {})),
                            "inferredTypes": list(ide.get("inferredTypes", {})), "installedFilesCompared": len(file_hashes)},
                    "workflows": {**workflows, "files": [describe(path) for path in workflow_sources]},
                    "historicalArtifactsUnchanged": True, "localDocumentationLinks": "passed"},
               "performance": paper.get("performance"),
               "measurements": {name: paper[name] for name in ("new031", "old030", "vanillaFill") if name in paper},
               "build": {"sourceDateEpoch": build["sourceDateEpoch"], "wheelBuiltFromSdist": build.get("wheelBuiltFromSdist"),
                         "sdistContainerMetadataNormalized": build.get("sdistContainerMetadataNormalized"), "twineStrict": build.get("twineStrict")},
               "documentation": documentation, "evidence": [describe(path) for path in sorted(evidence)],
               "verificationTools": [describe(path) for path in tools],
               "publication": {"githubActionsExecuted": False, "githubReleasePublished": False, "pypiUploaded": False},
               "notes": ["BUILD.json describes the build phase and remains unchanged; RELEASE.json adds local acceptance proof.",
                         "Production input hashes identify working-tree bytes, not a claim that git HEAD contains them.",
                         "Workflow validation is local; no cloud CI execution or publication is claimed."]}
    save(output / "RELEASE.json", release)
    return release


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("build", "package", "python-tests", "paper", "ide"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--workflow-validation", type=Path, default=ROOT / ".work/github-workflows-validation.json")
    args = parser.parse_args()
    result = finalize(args)
    print(json.dumps({"finalized": True, "version": result["version"], "verified": result["verification"]["passed"],
                      "paperManifests": result["verification"]["paper"]["manifests"]}, indent=2))


if __name__ == "__main__":
    main()
