"""Export a registry snapshot on pinned Paper using a disposable local plugin.

Requires existing toolchain/bootstrap caches and operator EULA consent. Does not
build production JARs/wheels, download files, modify production settings or expose
a network operation. Run before generate_block_catalog.py when updating Paper.
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
    assert hashlib.file_digest(paper.open("rb"), "sha256").hexdigest() == toolchain["artifacts"]["paper"]["sha256"]
    source_server = ROOT / ".work/t02-server"
    consent = source_server / "eula.txt"
    assert "eula=true" in consent.read_text(encoding="utf-8").splitlines(), "Existing EULA consent required"
    workspace = ROOT / ".work" / ("i02-catalog-export-" + uuid.uuid4().hex)
    server, classes = workspace / "server", workspace / "classes"
    classes.mkdir(parents=True)
    server.mkdir()
    for name in ("libraries", "cache", "versions"):
        shutil.copytree(source_server / name, server / name)
    shutil.copy2(consent, server / "eula.txt")
    snapshot = json.loads((ROOT / "catalogs/mcpi-upstream-constants.json").read_text(encoding="utf-8"))
    # Pi-only blocks have no Java equivalent. 95 is stained glass in Java, not invisible bedrock.
    base = {row["id"] for row in snapshot["constants"] if row.get("id") is not None and row["id"] not in (246, 247)}
    pairs = {(value, 0) for value in base}
    variants = {1: range(7), 3: range(3), 5: range(6), 6: range(6),
                12: range(2), 17: range(16), 18: range(16), 24: range(3),
                35: range(16), 38: range(9), 43: range(8), 44: range(16),
                95: range(16), 98: range(4), 125: range(6), 126: range(16),
                159: range(16), 160: range(16), 161: (0, 1, 4, 5, 8, 9, 12, 13),
                162: (0, 1, 4, 5, 8, 9, 12, 13), 171: range(16)}
    # Additional well-defined Java variants and orientation metadata; reserved values omitted.
    for block_id in (53, 67, 108, 109, 114, 128):
        variants[block_id] = range(8)
    for block_id in (54, 61, 62, 65, 68):
        variants[block_id] = range(2, 6)
    variants[73], variants[74], variants[75] = (0,), (0,), (0,)
    for block_id, values in variants.items():
        pairs.update((block_id, value) for value in values)
    # Only existing oak..dark_oak slab data, not undefined variant 6/7.
    pairs.difference_update((126, value) for value in (6, 7, 14, 15))
    (server / "legacy-pairs.json").write_text(json.dumps([
        {"id": value, "data": data} for value, data in sorted(pairs)
    ]), encoding="utf-8")
    jars = sorted((server / "libraries").rglob("*.jar"))
    classpath = ";".join(path.as_posix() for path in jars)
    arguments = workspace / "javac.args"
    source = ROOT / "tools/catalog/BlockRegistryExport.java"
    arguments.write_text(f'-encoding UTF-8 -cp "{classpath}" -d "{classes.as_posix()}" "{source.as_posix()}"', encoding="utf-8")
    subprocess.run([str(java / "javac.exe"), "@" + str(arguments)], check=True)
    (classes / "plugin.yml").write_text("name: BlockRegistryExport\nversion: '1'\nmain: dev.minebridge.catalog.BlockRegistryExport\napi-version: '26.2'\n", encoding="utf-8")
    (server / "plugins").mkdir()
    subprocess.run([str(java / "jar.exe"), "--create", "--file", str(server / "plugins/BlockRegistryExport.jar"), "-C", str(classes), "."], check=True)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        game_port = probe.getsockname()[1]
    (server / "server.properties").write_text(
        f"server-ip=127.0.0.1\nserver-port={game_port}\nlevel-name=catalog-world\n"
        "online-mode=true\nenable-rcon=false\nenable-query=false\nview-distance=2\n"
        "simulation-distance=2\npause-when-empty-seconds=-1\n", encoding="utf-8")
    with (workspace / "server.log").open("w", encoding="utf-8") as log:
        result = subprocess.run([str(java / "java.exe"), "-Xms256M", "-Xmx1G", "-Dterminal.jline=false", "-Dterminal.ansi=false", "-jar", str(paper), "--nogui"], cwd=server, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, timeout=300, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    result.check_returncode()
    output = json.loads((server / "block-registry-export.json").read_text(encoding="utf-8"))
    output["source"] = {"paper": toolchain["artifacts"]["paper"], "exporter": "tools/catalog/BlockRegistryExport.java", "checkedOn": "2026-10-22"}
    target = ROOT / "catalogs/paper-26.2-build133-blocks.json"
    target.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"snapshot": str(target), "blocks": len(output["blocks"]), "legacyPairs": len(output["legacyConversions"]), "evidence": str(workspace)}))
    return target


if __name__ == "__main__":
    export()
