"""Compile a read-only gamerule export fixture; never starts/stops Paper or builds a release."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PAPER_SHA = "bf1dcf627364f8a631ab15250d240eb5a8e89faaac523b391e1c61367fce9ff1"
API_SHA = "e8079e853374d75e571a24379573e96f6dfe1581b97bae5465163c77f00f327a"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare() -> Path:
    toolchain = json.loads((ROOT / ".tools/t02-toolchain.json").read_text(encoding="utf-8"))
    java_home = Path(toolchain["javaHome"])
    paper = Path(toolchain["paperJar"])
    api = next((ROOT / ".tools/gradle-cache/caches/modules-2/files-2.1/io.papermc.paper/paper-api/26.2.build.133-stable").rglob("*.jar"))
    assert sha(paper) == PAPER_SHA and sha(api) == API_SHA, "Pinned input hash mismatch"
    workspace = ROOT / ".work/v03-i01-gamerule-export"
    classes = workspace / "classes"
    classes.mkdir(parents=True, exist_ok=True)
    source = ROOT / "tools/catalog/GameRuleRegistryExport.java"
    libraries = sorted((ROOT / ".work/t02-server/libraries").rglob("*.jar"))
    assert libraries, "Prepare existing Paper bootstrap caches first"
    classpath = os.pathsep.join(str(path) for path in [api, *libraries])
    arguments = workspace / "javac.args"
    arguments.write_text("\n".join([
        "--release", "25", "-encoding", "UTF-8", "-classpath", json.dumps(classpath.replace('\\', '/')),
        "-d", json.dumps(classes.as_posix()), json.dumps(source.as_posix()),
    ]) + "\n", encoding="utf-8")
    subprocess.run([str(java_home / "bin/javac.exe"), "@" + str(arguments)], check=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    (classes / "plugin.yml").write_text(
        "name: MinebridgeGameRuleExport\nversion: 0.3-i01-fixture\nmain: dev.minebridge.catalog.GameRuleRegistryExport\napi-version: '26.2'\nload: POSTWORLD\n",
        encoding="utf-8")
    (classes / "provenance.json").write_text(json.dumps({
        "paper": {"sha256": PAPER_SHA, "build": 133},
        "paperApi": {"sha256": API_SHA, "version": "26.2.build.133-stable"},
        "exporter": {"path": "tools/catalog/GameRuleRegistryExport.java", "sha256": sha(source)},
        "method": "Registry.GAME_RULE + GameRules field identity; legacy aliases only for identical objects",
    }, indent=2) + "\n", encoding="utf-8")
    jar = workspace / "minebridge-gamerule-export.jar"
    subprocess.run([str(java_home / "bin/jar.exe"), "--create", "--file", str(jar), "-C", str(classes), "."],
                   check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return jar


if __name__ == "__main__":
    print(prepare())
