"""Build one Minebridge 0.3 candidate and install it in two clean interpreters.

Run from the workspace after the production source freeze. This tool does not
publish anything. Historical dist directories are checked, never modified.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.metadata
import gzip
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.3.0"
EPOCH = 1793145600
OUTPUT = ROOT / "dist/v0.3"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def describe(path: Path) -> dict:
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": sha256(path), "bytes": path.stat().st_size}


def production_inputs() -> dict:
    candidates = [ROOT / "plugin/build.gradle.kts", ROOT / "plugin/settings.gradle.kts",
                  ROOT / "plugin/gradle.lockfile", ROOT / "plugin/buildscript-gradle.lockfile",
                  ROOT / "plugin/gradlew", ROOT / "plugin/gradlew.bat",
                  ROOT / "python/pyproject.toml", ROOT / "python/README.md",
                  ROOT / "python/MANIFEST.in", ROOT / "python/setup.cfg"]
    for directory in ("plugin/src/main", "plugin/gradle", "python/src/minebridge"):
        candidates.extend(path for path in (ROOT / directory).rglob("*") if path.is_file()
                          and "__pycache__" not in path.parts and path.suffix != ".pyc")
    files = [describe(path) for path in sorted(set(candidates)) if path.is_file()]
    records = "".join(f"{row['path']}\0{row['sha256']}\n" for row in files).encode("utf-8")
    return {"algorithm": "SHA-256 of sorted path + NUL + file SHA-256 + LF records",
            "sha256": hashlib.sha256(records).hexdigest(), "files": files, "fileCount": len(files)}


def historical_artifacts() -> list[dict]:
    verified = []
    for directory in (ROOT / "dist/v0.2", ROOT / "dist/v0.2.1"):
        checksum = directory / "SHA256SUMS.txt"
        if not checksum.is_file():
            continue
        for line in checksum.read_text(encoding="utf-8").splitlines():
            digest, name = line.split(None, 1)
            path = directory / name.strip()
            if sha256(path) != digest:
                raise AssertionError("Historical artifact has changed: " + str(path))
            verified.append(describe(path))
    return verified


def run(command: list[str], log: Path, env: dict[str, str], *, cwd: Path = ROOT) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("wb") as stream:
        result = subprocess.run(command, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}); see {log.relative_to(ROOT)}\n"
                           + log.read_text(encoding="utf-8", errors="replace")[-6000:])


def java_results() -> dict:
    totals = dict(tests=0, errors=0, failures=0, skipped=0)
    for path in (ROOT / "plugin/build/test-results/test").glob("TEST-*.xml"):
        attributes = ET.parse(path).getroot().attrib
        for name in totals:
            totals[name] += int(attributes.get(name, 0))
    if not totals["tests"] or any(totals[name] for name in ("errors", "failures", "skipped")):
        raise AssertionError("Java release suite failed: " + str(totals))
    return totals


def canonicalize_sdist(path: Path) -> None:
    """Normalize container metadata only; verify every delivered file byte stays identical."""
    with tarfile.open(path, "r:gz") as source:
        members = source.getmembers()
        if any(not (member.isfile() or member.isdir()) for member in members):
            raise AssertionError("Unexpected links/special files in generated sdist")
        files = {member.name: source.extractfile(member).read() for member in members if member.isfile()}
        directories = {member.name for member in members if member.isdir()}
    target = path.with_name(path.name + ".canonical")
    with target.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=EPOCH) as compressed:
            with tarfile.open(mode="w", fileobj=compressed, format=tarfile.PAX_FORMAT) as output:
                for name in sorted(directories | files.keys()):
                    member = tarfile.TarInfo(name)
                    member.mtime = EPOCH
                    member.uid = member.gid = 0
                    member.uname = member.gname = ""
                    if name in directories:
                        member.type, member.mode = tarfile.DIRTYPE, 0o755
                        output.addfile(member)
                    else:
                        content = files[name]
                        member.mode, member.size = 0o644, len(content)
                        output.addfile(member, io.BytesIO(content))
    with tarfile.open(target, "r:gz") as check:
        compared = {member.name: check.extractfile(member).read() for member in check.getmembers() if member.isfile()}
    if compared != files:
        raise AssertionError("Archive normalization changed the sdist payload")
    target.replace(path)


def finalize_metadata(paper_path: Path, ide_path: Path) -> None:
    """Publish local provenance only after package, IDE and real-server evidence all pass."""
    build_path = ROOT / ".work/v03-i05-build-results.json"
    package_path = ROOT / ".work/v03-i05-package-results.json"
    build = json.loads(build_path.read_text(encoding="utf-8"))
    package = json.loads(package_path.read_text(encoding="utf-8"))
    paper = json.loads(paper_path.read_text(encoding="utf-8"))
    ide = json.loads(ide_path.read_text(encoding="utf-8"))
    if not build.get("passed") or not package.get("passed") or not paper.get("allPassed") or ide.get("status") != "passed":
        raise AssertionError("All release evidence must pass before finalizing RELEASE.json")
    if production_inputs() != build["productionInputs"] or historical_artifacts() != build["historicalArtifacts"]:
        raise AssertionError("Release source inputs or historical artifacts changed after candidate build")
    for item in build["artifacts"]:
        if describe(ROOT / item["path"]) != item:
            raise AssertionError("Candidate artifact changed after the recorded build")
    wheel_sha = next(item["sha256"] for item in build["artifacts"] if item["path"].endswith(".whl"))
    if ide.get("artifactValidation", {}).get("wheelSha256") != wheel_sha:
        raise AssertionError("IDE did not inspect the final installed wheel")
    for item in package["artifacts"].values():
        if sha256(Path(item["path"])) != item["sha256"]:
            raise AssertionError("Audited package artifact has changed")
    paths = {build_path, package_path, paper_path, ide_path}
    toolchain_path = ROOT / ".tools/t02-toolchain.json"
    toolchain = json.loads(toolchain_path.read_text(encoding="utf-8"))
    paths.add(toolchain_path)
    for name in ("v03-i05-java-tests.log", "v03-i05-python-311-tests.log", "v03-i05-python-314-tests.log",
                 "v03-i05-sdist-build.log", "v03-i05-wheel-build.log", "v03-i05-canonical-rebuild.log"):
        path = ROOT / ".work" / name
        if path.is_file():
            paths.add(path)
    manifests: list[dict] = []

    def collect(value: object) -> None:
        if isinstance(value, dict):
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)
        elif isinstance(value, str) and value.endswith("manifest.json"):
            path = Path(value)
            if not path.is_absolute():
                path = ROOT / path
            path = path.resolve()
            if path.is_file() and path.is_relative_to(ROOT) and path not in paths:
                document = json.loads(path.read_text(encoding="utf-8"))
                if document.get("allPassed") is not True:
                    raise AssertionError("Referenced final Paper manifest did not pass: " + str(path))
                selected = document.get("artifacts", {})
                expected = build["historicalArtifacts"] if document.get("baseline021") else build["artifacts"]
                for key, suffix in (("production", ".jar"), ("wheel", ".whl")):
                    artifact = selected.get(key, {})
                    matches = [item for item in expected if item["path"].endswith(suffix)
                               and Path(item["path"]).name == Path(artifact.get("path", "")).name]
                    if len(matches) != 1 or artifact.get("sha256") != matches[0]["sha256"]:
                        raise AssertionError("Paper did not test the frozen release artifact: " + str(path))
                if selected.get("paper", {}).get("sha256") != toolchain["artifacts"]["paper"]["sha256"]:
                    raise AssertionError("Paper acceptance used a different server toolchain")
                paths.add(path)
                manifests.append({"path": path.relative_to(ROOT).as_posix(),
                                  "runId": document.get("runId"), "checksPassed": len(document.get("checks", [])),
                                  "allPassed": True})
    collect(paper)
    if not manifests:
        raise AssertionError("Real Paper manifest evidence is required")
    release = {"schemaVersion": 1, "project": "Minebridge", "version": VERSION,
               "releaseDate": build["releaseDate"], "protocol": "2.0", "pathsRelativeTo": "workspace root",
               "artifacts": build["artifacts"], "productionInputs": build["productionInputs"],
               "verification": {"passed": True, "java": build["java"],
                    "pythonInstalledRuns": build["pythonInstalledRuns"],
                    "package": {key: package[key] for key in ("wheelEntries", "packageFiles", "registryCounts",
                        "recordVerified", "sdistMatchesWheelPackage", "archiveMetadata", "jarAudit", "generatorsChecked")},
                    "paper": {"minecraft": "26.2", "build": 133, "allPassed": True, "manifests": manifests,
                              "summary": paper_path.relative_to(ROOT).as_posix(),
                              "scope": "Local installed release acceptance; no LAN or classroom load claim"},
                    "ide": {"status": "passed", "vscode": ide.get("vscode"), "extensions": ide.get("extensions"),
                            "catalogs": len(ide.get("catalogs", {})), "signatures": len(ide.get("signatures", {})),
                            "wheelSha256": wheel_sha}, "historicalArtifactsUnchanged": True},
               "historicalArtifacts": build["historicalArtifacts"],
               "evidence": [describe(path) for path in sorted(paths)],
               "verificationTools": [describe(ROOT / "tools" / name) for name in
                    ("build_v03_release.py", "check_v03_package.py", "check_v02_package.py")],
               "documentation": ["dist/v0.3/README.ru.md", "docs/QUICKSTART.ru.md", "docs/API_V0_3.ru.md",
                                 "docs/reports/V0_3_I05.ru.md"],
               "build": {"sourceDateEpoch": EPOCH, "setuptools": build["setuptools"], "frontend": build["buildFrontend"],
                         "gradle": build["gradle"], "wheelBuiltFromSdist": True,
                         "toolchain": toolchain,
                         "sdistContainerMetadataNormalized": build.get("sdistContainerMetadataNormalized", False),
                         "wheelRebuiltFromCanonicalSdistIdentical": build.get("wheelRebuiltFromCanonicalSdistIdentical", False)},
               "notes": ["Built from a dirty workspace; productionInputs hashes identify the reviewed bytes, not git HEAD.",
                         "sdist file payload is unchanged; gzip/tar metadata is explicitly normalized because raw setuptools sdist timestamps are not reproducible.",
                         "PyPI publication was not performed. Existing dist/v0.2 and dist/v0.2.1 are unchanged."]}
    save(OUTPUT / "RELEASE.json", release)
    (OUTPUT / "SHA256SUMS.txt").write_text("".join(f"{row['sha256']}  {Path(row['path']).name}\n" for row in build["artifacts"]), encoding="utf-8")
    print(json.dumps({"phase": "release-metadata-finalized", "version": VERSION,
                      "productionInputs": build["productionInputs"]["sha256"], "paperManifests": manifests}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-date-epoch", type=int, default=EPOCH)
    parser.add_argument("--finalize", action="store_true", help="Write RELEASE.json from completed audit/IDE/Paper evidence without rebuilding")
    parser.add_argument("--paper-results", type=Path, default=ROOT / ".work/v03-i05-paper-results.json")
    parser.add_argument("--ide-results", type=Path, default=ROOT / ".work/ide-v03-results.json")
    args = parser.parse_args()
    if args.source_date_epoch != EPOCH:
        raise SystemExit("Use the frozen 0.3 release epoch")
    if args.finalize:
        finalize_metadata(args.paper_results.resolve(), args.ide_results.resolve())
        return
    import tomllib
    project = tomllib.loads((ROOT / "python/pyproject.toml").read_text(encoding="utf-8"))
    if project["project"]["version"] != VERSION:
        raise SystemExit("Freeze Python/plugin versions before building")
    if f'version = "{VERSION}"' not in (ROOT / "plugin/build.gradle.kts").read_text(encoding="utf-8"):
        raise SystemExit("Plugin version is not the release version")
    if f'__version__ = "{VERSION}"' not in (ROOT / "python/src/minebridge/__init__.py").read_text(encoding="utf-8"):
        raise SystemExit("Python runtime version differs")
    original = production_inputs()
    old = historical_artifacts()
    tools = json.loads((ROOT / ".tools/t02-toolchain.json").read_text(encoding="utf-8"))
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("MINEBRIDGE_TOKEN", None)
    environment.update(JAVA_HOME=tools["javaHome"], GRADLE_USER_HOME=str(ROOT / ".tools/gradle-cache"),
                       SOURCE_DATE_EPOCH=str(EPOCH), PIP_DISABLE_PIP_VERSION_CHECK="1", PIP_NO_INPUT="1")
    stage = ROOT / ".work" / ("v03-release-build-" + uuid.uuid4().hex)
    stage.mkdir(parents=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    print(json.dumps({"phase": "java-test-and-release-jar", "sourceInputs": original["sha256"]}), flush=True)
    java = str(Path(tools["javaHome"]) / "bin/java.exe")
    run([java, "-Xmx64m", "-Xms64m", "-Dorg.gradle.appname=gradlew", "-jar",
         str(ROOT / "plugin/gradle/wrapper/gradle-wrapper.jar"), "-p", "plugin", "test", "shadowJar",
         ":observer:jar", "--offline", "--console=plain"], ROOT / ".work/v03-i05-java-tests.log", environment)
    java_counts = java_results()
    build_python = ROOT / ".venv-tools/Scripts/python.exe"
    print(json.dumps({"phase": "sdist-then-wheel"}), flush=True)
    run([str(build_python), "-I", "-m", "build", "--sdist", "--outdir", str(stage / "sdist"),
         str(ROOT / "python")], ROOT / ".work/v03-i05-sdist-build.log", environment)
    sdist = stage / "sdist" / f"minebridge-{VERSION}.tar.gz"
    canonicalize_sdist(sdist)
    unpacked = stage / "sdist-source"
    unpacked.mkdir()
    with tarfile.open(sdist, "r:gz") as archive:
        archive.extractall(unpacked, filter="data")
    run([str(build_python), "-I", "-m", "build", "--wheel", "--outdir", str(stage / "wheel"),
         str(unpacked / f"minebridge-{VERSION}")], ROOT / ".work/v03-i05-wheel-build.log", environment)
    source_wheel = stage / "wheel" / f"minebridge-{VERSION}-py3-none-any.whl"
    artifacts = [OUTPUT / f"minebridge-paper-{VERSION}.jar", OUTPUT / source_wheel.name, OUTPUT / sdist.name]
    for source, target in zip((ROOT / f"plugin/build/libs/minebridge-paper-{VERSION}.jar", source_wheel, sdist), artifacts):
        shutil.copyfile(source, target)
    python_runs = []
    for suffix in ("311", "314"):
        python = ROOT / f".venv-v03-{suffix}/Scripts/python.exe"
        if not python.is_file():
            run([str(ROOT / f".venv-v021-{suffix}/Scripts/python.exe"), "-m", "venv", str(python.parent.parent)],
                ROOT / f".work/v03-i05-venv-{suffix}.log", environment)
        print(json.dumps({"phase": "installed-wheel-tests", "python": str(python)}), flush=True)
        run([str(python), "-I", "-m", "pip", "install", "--no-index", "--no-deps", "--force-reinstall", str(artifacts[1])],
            ROOT / f".work/v03-i05-install-{suffix}.log", environment)
        log = ROOT / f".work/v03-i05-python-{suffix}-tests.log"
        run([str(python), "-I", "-m", "unittest", "discover", "-s", str(ROOT / "python/tests"), "-q"], log, environment,
            cwd=stage)
        text = log.read_text(encoding="utf-8")
        import re
        match = re.search(r"Ran (\d+) tests", text)
        if match is None or not re.search(r"(?m)^OK\s*$", text) or "skipped=" in text:
            raise AssertionError("Installed unit tests must pass without skips: " + str(log))
        completed = subprocess.run([str(python), "-I", "-c",
            "import json,sys,minebridge;print(json.dumps({'version':sys.version,'package':minebridge.__file__,'minebridge':minebridge.__version__}))"],
            cwd=stage, env=environment, text=True, capture_output=True, check=True)
        runtime = json.loads(completed.stdout)
        if "site-packages" not in runtime["package"] or runtime["minebridge"] != VERSION:
            raise AssertionError("Tests did not use the installed final wheel")
        python_runs.append({"executable": str(python), **runtime, "tests": int(match.group(1)), "skipped": 0})
    if production_inputs() != original or historical_artifacts() != old:
        raise AssertionError("Production inputs or historical artifacts changed during release build")
    checksums = "".join(f"{sha256(path)}  {path.name}\n" for path in artifacts)
    (OUTPUT / "SHA256SUMS.txt").write_text(checksums, encoding="utf-8")
    evidence = {"passed": True, "version": VERSION, "sourceDateEpoch": EPOCH,
                "releaseDate": dt.datetime.fromtimestamp(EPOCH, dt.timezone.utc).date().isoformat(),
                "artifacts": [describe(path) for path in artifacts], "productionInputs": original,
                "historicalArtifacts": old, "java": java_counts, "pythonInstalledRuns": python_runs,
                "wheelBuiltFromSdist": True, "buildFrontend": importlib.metadata.version("build"),
                "setuptools": "84.2.0", "gradle": "9.1.0", "sdistContainerMetadataNormalized": True,
                "stage": stage.relative_to(ROOT).as_posix()}
    save(ROOT / ".work/v03-i05-build-results.json", evidence)
    print(json.dumps({"phase": "candidate-ready", "java": java_counts, "python": python_runs,
                      "artifacts": evidence["artifacts"]}, indent=2), flush=True)


if __name__ == "__main__":
    main()
