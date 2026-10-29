"""Export pinned Paper item/effect/entity registries and spawn API probes locally.

Uses a disposable plugin/server and existing cached toolchain and EULA consent.
Does not build a release artifact or expose any production RPC/test endpoint.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import socket
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1]


def export() -> Path:
    toolchain = json.loads((ROOT / ".tools/t02-toolchain.json").read_text(encoding="utf-8"))
    java = Path(toolchain["javaHome"]) / "bin"
    paper = Path(toolchain["paperJar"])
    with paper.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == toolchain["artifacts"]["paper"]["sha256"]
    source_server = ROOT / ".work/t02-server"
    consent = source_server / "eula.txt"
    assert "eula=true" in consent.read_text(encoding="utf-8").splitlines(), "Existing EULA consent required"
    workspace = ROOT / ".work" / ("i04-catalog-export-" + uuid.uuid4().hex)
    server, classes = workspace / "server", workspace / "classes"
    classes.mkdir(parents=True)
    server.mkdir()
    for name in ("libraries", "cache", "versions"):
        shutil.copytree(source_server / name, server / name)
    shutil.copy2(consent, server / "eula.txt")
    classpath = ";".join(path.as_posix() for path in sorted((server / "libraries").rglob("*.jar")))
    arguments = workspace / "javac.args"
    source = ROOT / "tools/catalog/GameRegistryExport.java"
    arguments.write_text(f'-encoding UTF-8 -cp "{classpath}" -d "{classes.as_posix()}" "{source.as_posix()}"', encoding="utf-8")
    subprocess.run([str(java / "javac.exe"), "@" + str(arguments)], check=True)
    (classes / "plugin.yml").write_text("name: GameRegistryExport\nversion: '1'\nmain: dev.minebridge.catalog.GameRegistryExport\napi-version: '26.2'\n", encoding="utf-8")
    (server / "plugins").mkdir()
    subprocess.run([str(java / "jar.exe"), "--create", "--file", str(server / "plugins/GameRegistryExport.jar"), "-C", str(classes), "."], check=True)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        game_port = probe.getsockname()[1]
    (server / "server.properties").write_text(
        f"server-ip=127.0.0.1\nserver-port={game_port}\nlevel-name=catalog-world\n"
        "online-mode=true\nenable-rcon=false\nenable-query=false\nview-distance=2\n"
        "simulation-distance=2\npause-when-empty-seconds=-1\nlevel-type=minecraft:flat\n"
        "generate-structures=false\n", encoding="utf-8")
    with (workspace / "server.log").open("w", encoding="utf-8") as log:
        result = subprocess.run([str(java / "java.exe"), "-Xms256M", "-Xmx1G", "-Dterminal.jline=false", "-Dterminal.ansi=false", "-jar", str(paper), "--nogui"], cwd=server, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, timeout=300, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    result.check_returncode()
    output = json.loads((server / "game-registry-export.json").read_text(encoding="utf-8"))
    output["source"] = {"paper": toolchain["artifacts"]["paper"], "exporter": "tools/catalog/GameRegistryExport.java", "checkedOn": "2026-10-22",
                        "registryApi": "Registry.ITEM / Registry.MOB_EFFECT / Registry.ENTITY_TYPE",
                        "probeScope": "Actual pinned server, loaded flat Overworld, creation and validAtReturn checked then immediate removal; generic and listed adapters. Fishing adapter needs an online player in integration tests. No lifetime, AI or gameplay guarantees."}
    target = ROOT / "catalogs/paper-26.2-build133-game.json"
    target.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"snapshot": str(target), "items": len(output["items"]), "effects": len(output["effects"]), "entities": len(output["entities"]), "evidence": str(workspace)}))
    return target


if __name__ == "__main__":
    export()
