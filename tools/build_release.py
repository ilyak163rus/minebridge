"""Build a matching Paper JAR and Python sdist/wheel; publish or install nothing.

Run with a Python 3.11+ environment containing build and twine. JAVA_HOME should
point to JDK 25. The repository's optional local tool cache is used when present.
Installed Python tests, IDE checks and Paper acceptance are separate release gates.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tomllib
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def describe(path: Path) -> dict:
    path = path.resolve()
    name = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)
    return {"path": name, "sha256": sha256(path), "bytes": path.stat().st_size}


def save(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def project_version() -> str:
    project = tomllib.loads((ROOT / "python/pyproject.toml").read_text(encoding="utf-8"))
    version = project["project"]["version"]
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){2}", version):
        raise ValueError("Release version must be three numeric components")
    tree = ast.parse((ROOT / "python/src/minebridge/__init__.py").read_text(encoding="utf-8"))
    versions = [ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets)]
    java = re.findall(r'(?m)^version\s*=\s*"([^"\n]+)"', (ROOT / "plugin/build.gradle.kts").read_text(encoding="utf-8"))
    if versions != [version] or java != [version]:
        raise ValueError("Python metadata, runtime and plugin versions must match")
    if (ROOT / "LICENSE").read_bytes() != (ROOT / "python/LICENSE").read_bytes():
        raise ValueError("The root and Python package LICENSE files differ")
    return version


def production_inputs() -> dict:
    candidates = [ROOT / name for name in (
        "LICENSE", "THIRD_PARTY_NOTICES.md", "plugin/build.gradle.kts", "plugin/settings.gradle.kts",
        "plugin/gradle.lockfile", "plugin/buildscript-gradle.lockfile", "plugin/gradlew", "plugin/gradlew.bat",
        "python/pyproject.toml", "python/README.md", "python/LICENSE", "python/MANIFEST.in", "python/setup.cfg")]
    for directory in ("plugin/src/main", "plugin/gradle", "python/src/minebridge"):
        candidates.extend(path for path in (ROOT / directory).rglob("*") if path.is_file()
                          and "__pycache__" not in path.parts and path.suffix != ".pyc")
    files = [describe(path) for path in sorted(set(candidates)) if path.is_file()]
    records = "".join(f"{row['path']}\0{row['sha256']}\n" for row in files).encode()
    return {"algorithm": "SHA-256 of sorted path + NUL + file SHA-256 + LF records",
            "sha256": hashlib.sha256(records).hexdigest(), "files": files, "fileCount": len(files)}


def historical_artifacts(output: Path) -> list[dict]:
    return [describe(path) for path in sorted((ROOT / "dist").rglob("*"))
            if path.is_file() and not path.resolve().is_relative_to(output)]


def java_environment() -> tuple[Path, dict[str, str]]:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("MINEBRIDGE_TOKEN", None)
    env.update(PYTHONUTF8="1", PIP_DISABLE_PIP_VERSION_CHECK="1", PIP_NO_INPUT="1")
    executable = "java.exe" if os.name == "nt" else "java"
    home = env.get("JAVA_HOME")
    if home:
        java = Path(home) / "bin" / executable
        if not java.is_file():
            raise ValueError("JAVA_HOME does not contain bin/" + executable)
    else:
        local = ROOT / ".tools/t02-toolchain.json"
        cached = json.loads(local.read_text(encoding="utf-8")).get("javaHome") if local.is_file() else None
        candidate = Path(cached) / "bin" / executable if cached else None
        if candidate is not None and candidate.is_file():
            java = candidate
            env["JAVA_HOME"] = str(candidate.parent.parent)
        else:
            found = shutil.which(executable)
            if found is None:
                raise ValueError("Install JDK 25 and set JAVA_HOME before building")
            java = Path(found)
    cache = ROOT / ".tools/gradle-cache"
    if cache.is_dir() and "GRADLE_USER_HOME" not in env:
        env["GRADLE_USER_HOME"] = str(cache)
    return java.resolve(), env


def run(command: list[str], log: Path, env: dict[str, str], *, cwd: Path = ROOT) -> None:
    with log.open("wb") as stream:
        result = subprocess.run(command, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}); see {log}\n"
                           + log.read_text(encoding="utf-8", errors="replace")[-5000:])


def java_results() -> dict:
    totals = dict(tests=0, errors=0, failures=0, skipped=0)
    for path in (ROOT / "plugin/build/test-results/test").glob("TEST-*.xml"):
        attributes = ET.parse(path).getroot().attrib
        for name in totals:
            totals[name] += int(attributes.get(name, 0))
    if not totals["tests"] or any(totals[name] for name in ("errors", "failures", "skipped")):
        raise AssertionError("Java release suite did not pass without skips: " + str(totals))
    return totals


def canonicalize_sdist(path: Path, epoch: int) -> None:
    """Normalize only container metadata and prove file payload is unchanged."""
    with tarfile.open(path, "r:gz") as source:
        members = source.getmembers()
        if any(not (item.isfile() or item.isdir()) for item in members):
            raise AssertionError("Generated sdist contains links or special files")
        files = {item.name: source.extractfile(item).read() for item in members if item.isfile()}
        directories = {item.name for item in members if item.isdir()}
    target = path.with_name(path.name + ".canonical")
    with target.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=epoch) as compressed:
            with tarfile.open(mode="w", fileobj=compressed, format=tarfile.PAX_FORMAT) as output:
                for name in sorted(directories | files.keys()):
                    item = tarfile.TarInfo(name)
                    item.mtime, item.uid, item.gid, item.uname, item.gname = epoch, 0, 0, "", ""
                    if name in directories:
                        item.type, item.mode = tarfile.DIRTYPE, 0o755
                        output.addfile(item)
                    else:
                        content = files[name]
                        item.mode, item.size = 0o644, len(content)
                        output.addfile(item, io.BytesIO(content))
    with tarfile.open(target, "r:gz") as check:
        compared = {item.name: check.extractfile(item).read() for item in check.getmembers() if item.isfile()}
    if compared != files:
        raise AssertionError("Normalizing sdist metadata changed file payload")
    target.replace(path)


def extract_sdist(path: Path, directory: Path) -> None:
    """Extract only ordinary files/directories, including on Python 3.11.0."""
    directory = directory.resolve()
    with tarfile.open(path, "r:gz") as archive:
        for item in archive.getmembers():
            target = (directory / item.name).resolve()
            if not target.is_relative_to(directory) or not (item.isfile() or item.isdir()):
                raise AssertionError("Unsafe sdist member: " + item.name)
            if item.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(item) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Defaults to dist/v<project version>")
    parser.add_argument("--source-date-epoch", type=int, help="SOURCE_DATE_EPOCH or current UTC midnight by default")
    parser.add_argument("--offline", action="store_true", help="Use the existing Gradle dependency cache")
    parser.add_argument("--replace", action="store_true", help="Explicitly replace this version's existing candidate")
    args = parser.parse_args()
    version = project_version()
    output = (args.output or ROOT / ("dist/v" + version)).resolve()
    dist = (ROOT / "dist").resolve()
    if output.is_relative_to(dist):
        first = output.relative_to(dist).parts
        if not first or first[0].startswith("v") and first[0] != "v" + version:
            raise ValueError("Output cannot replace a different historical release directory")
    targets = [output / f"minebridge-paper-{version}.jar", output / f"minebridge-{version}-py3-none-any.whl",
               output / f"minebridge-{version}.tar.gz"]
    if not args.replace and any(path.exists() for path in [*targets, output / "BUILD.json", output / "SHA256SUMS.txt"]):
        raise ValueError("Candidate already exists; use --replace only for an intentional rebuild of this version")
    for module in ("build", "twine"):
        if importlib.util.find_spec(module) is None:
            raise RuntimeError(f"Missing build tool {module}; install the release requirements in this Python environment")
    default_epoch = int(dt.datetime.combine(dt.datetime.now(dt.timezone.utc).date(), dt.time(), dt.timezone.utc).timestamp())
    epoch = args.source_date_epoch if args.source_date_epoch is not None else int(os.environ.get("SOURCE_DATE_EPOCH", default_epoch))
    if not 315532800 <= epoch <= 4294967295:
        raise ValueError("SOURCE_DATE_EPOCH must fit ZIP (1980+) and gzip timestamps")
    original, old = production_inputs(), historical_artifacts(output)
    java, env = java_environment()
    env["SOURCE_DATE_EPOCH"] = str(epoch)
    stage = ROOT / ".work" / ("release-v" + version + "-" + uuid.uuid4().hex)
    stage.mkdir(parents=True)
    print(json.dumps({"phase": "java-test-and-jar", "version": version, "stage": str(stage)}), flush=True)
    command = [str(java), "-Xmx64m", "-Xms64m", "-Dorg.gradle.appname=gradlew", "-jar",
               str(ROOT / "plugin/gradle/wrapper/gradle-wrapper.jar"), "-p", str(ROOT / "plugin"),
               "test", "shadowJar", ":observer:jar", "--console=plain"]
    if args.offline:
        command.append("--offline")
    run(command, stage / "java.log", env)
    java_counts = java_results()
    print(json.dumps({"phase": "sdist-then-wheel", "version": version}), flush=True)
    run([sys.executable, "-I", "-m", "build", "--sdist", "--outdir", str(stage / "sdist"), str(ROOT / "python")],
        stage / "sdist.log", env)
    sdist = stage / "sdist" / f"minebridge-{version}.tar.gz"
    canonicalize_sdist(sdist, epoch)
    unpacked = stage / "source"
    unpacked.mkdir()
    extract_sdist(sdist, unpacked)
    run([sys.executable, "-I", "-m", "build", "--wheel", "--outdir", str(stage / "wheel"),
         str(unpacked / f"minebridge-{version}")], stage / "wheel.log", env)
    wheel = stage / "wheel" / f"minebridge-{version}-py3-none-any.whl"
    run([sys.executable, "-I", "-m", "twine", "check", "--strict", str(wheel), str(sdist)], stage / "twine.log", env)
    if production_inputs() != original or historical_artifacts(output) != old:
        raise AssertionError("Production inputs or historical dist files changed during the build")
    output.mkdir(parents=True, exist_ok=True)
    for source, target in zip((ROOT / f"plugin/build/libs/minebridge-paper-{version}.jar", wheel, sdist), targets):
        shutil.copyfile(source, target)
    if historical_artifacts(output) != old:
        raise AssertionError("Historical dist files changed while delivering the candidate")
    evidence = {"buildPassed": True, "releaseVerified": False, "version": version,
                "releaseDate": dt.datetime.fromtimestamp(epoch, dt.timezone.utc).date().isoformat(),
                "sourceDateEpoch": epoch, "artifacts": [describe(path) for path in targets],
                "productionInputs": original, "historicalArtifacts": old, "java": java_counts,
                "wheelBuiltFromSdist": True, "sdistContainerMetadataNormalized": True, "twineStrict": True,
                "stage": str(stage.relative_to(ROOT)), "logs": [describe(path) for path in sorted(stage.glob("*.log"))],
                "buildPython": sys.version, "javaExecutable": str(java),
                "notPerformed": ["Python installed-package tests", "IDE verification", "Paper integration acceptance", "publication"]}
    save(output / "BUILD.json", evidence)
    (output / "SHA256SUMS.txt").write_text("".join(f"{sha256(path)}  {path.name}\n" for path in targets), encoding="utf-8")
    print(json.dumps({"phase": "candidate-built", "version": version, "java": java_counts,
                      "artifacts": evidence["artifacts"], "releaseVerified": False}, indent=2), flush=True)


if __name__ == "__main__":
    main()
