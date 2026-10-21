"""Fetch the pinned portable T02 toolchain; do not alter PATH or accept an EULA."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ".tools"

ARTIFACTS = {
    "jdk": {
        "name": "OpenJDK25U-jdk_x64_windows_hotspot_25.0.4.1_1.zip",
        "url": "https://github.com/adoptium/temurin25-binaries/releases/download/jdk-25.0.4.1%2B1/OpenJDK25U-jdk_x64_windows_hotspot_25.0.4.1_1.zip",
        "sha256": "00c847d804f4a78e9f04f2683faf14fed898535b177b7fc704486cb0284e9283",
    },
    "gradle": {
        "name": "gradle-9.1.0-bin.zip",
        "url": "https://services.gradle.org/distributions/gradle-9.1.0-bin.zip",
        "sha256": "a17ddd85a26b6a7f5ddb71ff8b05fc5104c0202c6e64782429790c933686c806",
    },
    "paper": {
        "name": "paper-26.2-133.jar",
        "url": "https://fill-data.papermc.io/v1/objects/bf1dcf627364f8a631ab15250d240eb5a8e89faaac523b391e1c61367fce9ff1/paper-26.2-133.jar",
        "sha256": "bf1dcf627364f8a631ab15250d240eb5a8e89faaac523b391e1c61367fce9ff1",
    },
}


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download(spec: dict[str, str]) -> Path:
    path = TOOLS / "downloads" / spec["name"]
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        print("Downloading " + spec["name"], flush=True)
        request = urllib.request.Request(spec["url"], headers={"User-Agent": "Minebridge-local-development/0.1"})
        with urllib.request.urlopen(request, timeout=60) as response, path.open("wb") as output:
            shutil.copyfileobj(response, output)
    actual = sha256(path)
    if actual != spec["sha256"]:
        raise RuntimeError(f"Checksum mismatch: {path.name}; expected {spec['sha256']}, got {actual}")
    return path


def extract(archive: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as contents:
        top_levels = {name.split("/")[0] for name in contents.namelist() if name}
        if len(top_levels) != 1:
            raise RuntimeError("Expected one archive root")
        for entry in contents.infolist():
            target = (destination / entry.filename).resolve()
            if not target.is_relative_to(destination.resolve()):
                raise RuntimeError("Archive entry leaves the tools directory")
        contents.extractall(destination)
    return destination / top_levels.pop()


def main() -> None:
    paths = {name: download(spec) for name, spec in ARTIFACTS.items()}
    java_home = extract(paths["jdk"], TOOLS / "java25")
    gradle_home = extract(paths["gradle"], TOOLS)
    result = {
        "javaHome": str(java_home),
        "gradleHome": str(gradle_home),
        "paperJar": str(paths["paper"]),
        "artifacts": ARTIFACTS,
    }
    (TOOLS / "t02-toolchain.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()

