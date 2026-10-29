"""Verify final v0.2 artifacts and installed imports without building or installing.

Usage: python tools/check_v02_package.py --wheel FILE --sdist FILE --jar FILE
       --python CLEAN_VENV_PYTHON [--python ANOTHER_CLEAN_VENV_PYTHON]
The interpreter checks run with -I from a temporary directory outside the repo.
"""

from __future__ import annotations

import argparse
import base64
import csv
from email.parser import BytesParser
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.2.0"
REQUIRED = {
    "minebridge/py.typed", "minebridge/block.py", "minebridge/items.py",
    "minebridge/effects.py", "minebridge/entity.py", "minebridge/selector.py",
    "minebridge/api/players.py", "minebridge/api/effects.py", "minebridge/api/entities.py",
    "minebridge/_data/legacy-blocks-v0.1.json", "minebridge/_data/legacy-blocks-v0.2.json",
    "minebridge/_data/blocks-paper-26.2.json", "minebridge/_data/game-paper-26.2.json",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(value: object, message: str) -> None:
    if not value:
        raise AssertionError(message)


def archives(wheel: Path, sdist: Path, jar: Path) -> dict:
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        require(len(set(names)) == len(names), "Duplicate wheel members")
        require(REQUIRED.issubset(names), "Wheel is missing public typing/catalog resources")
        require(not any("__pycache__" in name or name.endswith(".pyc") for name in names),
                "Wheel includes local bytecode")
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = BytesParser().parsebytes(archive.read(metadata_name))
        require(metadata["Version"] == VERSION, "Unexpected wheel version")
        require(metadata["Requires-Python"] == ">=3.11", "Wrong supported Python range")
        require(not metadata.get_all("Requires-Dist"), "Unexpected runtime dependency")
        record_name = next(name for name in names if name.endswith(".dist-info/RECORD"))
        record = list(csv.reader(io.StringIO(archive.read(record_name).decode("utf-8"))))
        require({row[0] for row in record} == set(names), "RECORD does not cover the complete wheel")
        for name, digest, size in record:
            if name == record_name:
                require(digest == size == "", "RECORD cannot hash itself")
                continue
            content = archive.read(name)
            require(int(size) == len(content), "RECORD size differs: " + name)
            algorithm, encoded = digest.split("=", 1)
            actual = base64.urlsafe_b64encode(hashlib.new(algorithm, content).digest()).rstrip(b"=").decode()
            require(encoded == actual, "RECORD hash differs: " + name)
        package = {name: archive.read(name) for name in names if name.startswith("minebridge/")}
        expected_package = {"minebridge/" + file.relative_to(ROOT / "python/src/minebridge").as_posix():
                            file.read_bytes() for file in (ROOT / "python/src/minebridge").rglob("*")
                            if file.is_file() and file.suffix in (".py", ".json") or
                            file.is_file() and file.name == "py.typed"}
        require(package == expected_package, "Wheel package differs from the reviewed source files")
        blocks = json.loads(package["minebridge/_data/blocks-paper-26.2.json"])
        legacy = json.loads(package["minebridge/_data/legacy-blocks-v0.2.json"])
        game = json.loads(package["minebridge/_data/game-paper-26.2.json"])
        counts = {"blocks": len(blocks["blocks"]), "legacyPairs": len(legacy["blocks"]),
                  **{key: len(game[key]) for key in ("items", "effects", "entities")}}
        require(counts == {"blocks": 1196, "legacyPairs": 361, "items": 1537,
                           "effects": 40, "entities": 158}, "Wrong packaged registry coverage")
    with tarfile.open(sdist, "r:gz") as archive:
        members = {member.name: member for member in archive.getmembers() if member.isfile()}
        prefix = f"minebridge-{VERSION}/src/"
        for name, content in package.items():
            require(prefix + name in members, "sdist cannot reproduce package member: " + name)
            require(archive.extractfile(members[prefix + name]).read() == content,
                    "sdist and wheel differ: " + name)
    with zipfile.ZipFile(jar) as archive:
        descriptor = archive.read("plugin.yml").decode("utf-8")
        match = re.search(r"(?m)^version:\s*['\"]?([^'\"\s]+)", descriptor)
        require(match is not None and match.group(1) == VERSION, "JAR and wheel versions differ")
    return {"version": VERSION, "wheelEntries": len(names), "packageFiles": len(package),
            "registryCounts": counts, "recordVerified": True, "sdistMatchesWheelPackage": True,
            "artifacts": {name: {"path": str(path), "sha256": sha256(path)}
                          for name, path in (("wheel", wheel), ("sdist", sdist), ("jar", jar))}}


INSTALLED_CHECK = r'''
import base64, hashlib, importlib.metadata as metadata, importlib.resources as resources
import json, pathlib, socket, sys
attempts = []
def deny(*args, **kwargs):
    attempts.append("network")
    raise AssertionError("Offline package import attempted a connection")
socket.create_connection = socket.socket.connect = socket.socket.connect_ex = deny
from minebridge import Minecraft, block, items, effects, entity, selector
import minebridge
distribution = metadata.distribution("minebridge")
package = pathlib.Path(minebridge.__file__).resolve().parent
site = pathlib.Path(sys.executable).resolve().parent.parent / "Lib" / "site-packages"
assert package == site / "minebridge", (package, site)
assert minebridge.__version__ == distribution.version == sys.argv[1]
assert not distribution.requires
assert pathlib.Path(distribution.locate_file("minebridge/__init__.py")).resolve() == package / "__init__.py"
assert not attempts
verified = 0
for entry in distribution.files:
    name = str(entry).replace("\\", "/")
    if not name.startswith("minebridge/") or name.endswith(".pyc"):
        continue
    content = pathlib.Path(distribution.locate_file(entry)).read_bytes()
    assert len(content) == entry.size and entry.hash is not None, name
    digest = hashlib.new(entry.hash.mode, content).digest()
    assert base64.urlsafe_b64encode(digest).rstrip(b"=").decode() == entry.hash.value, name
    verified += 1
assert resources.files("minebridge").joinpath("py.typed").is_file()
assert len(items.__all__) == 1537 and len(effects.__all__) == 40 and len(entity.__all__) == 158
assert block.COBBLESTONE.id == 4 and selector.SELF.expression == "@s"
print(json.dumps({"python": sys.version, "executable": sys.executable, "package": str(package),
                  "version": distribution.version, "networkAttempts": len(attempts),
                  "recordPackageFilesVerified": verified, "sysPath": sys.path}))
'''


def main() -> None:
    global VERSION
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=VERSION, help="Expected matching Python/plugin version")
    for name in ("wheel", "sdist", "jar"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--python", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, default=ROOT / ".work/v02-package-results.json")
    args = parser.parse_args()
    VERSION = args.version
    result = {"passed": False}
    try:
        result.update(archives(args.wheel.resolve(), args.sdist.resolve(), args.jar.resolve()))
        generated = []
        for name in ("generate_block_catalog.py", "generate_game_catalog.py"):
            completed = subprocess.run([sys.executable, "-I", str(ROOT / "tools" / name), "--check"],
                                       cwd=ROOT, text=True, capture_output=True, timeout=30)
            require(completed.returncode == 0, "Generated catalog differs: " + completed.stdout + completed.stderr)
            generated.append(name)
        result["generatorsChecked"] = generated
        result["installedInterpreters"] = []
        with tempfile.TemporaryDirectory(prefix="minebridge-v02-offline-") as outside:
            for python in args.python:
                completed = subprocess.run([str(python.resolve()), "-I", "-c", INSTALLED_CHECK, VERSION],
                                           cwd=outside, text=True, capture_output=True, timeout=30)
                require(completed.returncode == 0, "Installed import failed: " + completed.stdout + completed.stderr)
                runtime = json.loads(completed.stdout)
                require(not any(Path(entry).resolve() == ROOT / "python/src" for entry in runtime["sysPath"]),
                        "Repository source leaked into isolated interpreter")
                result["installedInterpreters"].append(runtime)
        result["passed"] = True
        print(json.dumps(result, indent=2))
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
