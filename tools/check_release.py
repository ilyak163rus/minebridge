"""Audit release archives and optionally installed wheel imports; install/publish nothing.

Usage: python tools/check_release.py --wheel FILE --sdist FILE --jar FILE
       [--python VENV_PYTHON ...] [--output RESULT_JSON]
Requires twine in the executing Python environment for strict README validation.
"""

from __future__ import annotations

import argparse
import base64
import csv
from email.parser import BytesParser
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import struct
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def require(condition: object, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metadata_check(data: bytes, version: str, urls: dict[str, str]) -> dict:
    metadata = BytesParser().parsebytes(data)
    require(metadata["Name"] == "minebridge" and metadata["Version"] == version, "Package name/version mismatch")
    require(tuple(map(int, metadata["Metadata-Version"].split("."))) >= (2, 4), "PEP 639 metadata is required")
    require(metadata["License-Expression"] == "MIT", "License-Expression must be MIT")
    require("LICENSE" in metadata.get_all("License-File", []), "License-File is missing")
    require(metadata["Requires-Python"] == ">=3.11", "Unexpected Python support range")
    require(not metadata.get_all("Requires-Dist"), "Unexpected runtime dependency")
    require(metadata["Description-Content-Type"] == "text/markdown", "README must be Markdown")
    require(bool(metadata.get_payload().strip()), "README description is empty")
    actual_urls = dict(value.split(", ", 1) for value in metadata.get_all("Project-URL", []))
    require(actual_urls == urls, "Project URLs differ from pyproject.toml")
    return {"metadataVersion": metadata["Metadata-Version"], "licenseExpression": "MIT",
            "licenseFile": "LICENSE", "projectUrls": actual_urls, "requiresPython": metadata["Requires-Python"]}


def safe_names(names: list[str]) -> None:
    require(len(names) == len(set(names)), "Archive contains duplicate members")
    require(all(not PurePosixPath(name).is_absolute() and ".." not in PurePosixPath(name).parts
                and "\\" not in name for name in names), "Archive contains unsafe member names")


def archives(wheel: Path, sdist: Path, jar: Path, version: str) -> dict:
    project = tomllib.loads((ROOT / "python/pyproject.toml").read_text(encoding="utf-8"))["project"]
    license_bytes = (ROOT / "LICENSE").read_bytes()
    require(license_bytes == (ROOT / "python/LICENSE").read_bytes(), "Root/Python licenses differ")
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        safe_names(names)
        require(not any("__pycache__" in name or name.endswith(".pyc") for name in names), "Wheel contains bytecode")
        metadata_names = [name for name in names if name.endswith(".dist-info/METADATA")]
        require(len(metadata_names) == 1, "Wheel must contain one distribution")
        info = metadata_names[0].rsplit("/", 1)[0]
        require(info == f"minebridge-{version}.dist-info", "Unexpected dist-info directory")
        require(all(name.startswith(("minebridge/", info + "/")) for name in names), "Unexpected wheel files")
        meta = metadata_check(archive.read(metadata_names[0]), version, project["urls"])
        require(archive.read(info + "/licenses/LICENSE") == license_bytes, "Wheel MIT license differs")
        wheel_meta = BytesParser().parsebytes(archive.read(info + "/WHEEL"))
        require(wheel_meta["Root-Is-Purelib"] == "true" and wheel_meta.get_all("Tag") == ["py3-none-any"],
                "Python wheel must be platform independent")
        record_name = info + "/RECORD"
        records = list(csv.reader(io.StringIO(archive.read(record_name).decode("utf-8"))))
        require(all(len(row) == 3 for row in records), "Malformed wheel RECORD")
        require(len(records) == len(names) and {row[0] for row in records} == set(names), "Incomplete/duplicate RECORD")
        for name, digest, size in records:
            if name == record_name:
                require(digest == size == "", "RECORD cannot hash itself")
                continue
            content = archive.read(name)
            actual = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
            require(digest == "sha256=" + actual and size == str(len(content)), "RECORD mismatch: " + name)
        package = {name: archive.read(name) for name in names if name.startswith("minebridge/")}
        source = ROOT / "python/src/minebridge"
        expected = {"minebridge/" + path.relative_to(source).as_posix(): path.read_bytes()
                    for path in source.rglob("*") if path.is_file()
                    and "__pycache__" not in path.parts and path.suffix != ".pyc"}
        require(package == expected, "Wheel package differs from current reviewed source")
        require("minebridge/py.typed" in package, "py.typed is missing")
        catalogs = {name: json.loads(data) for name, data in package.items() if name.startswith("minebridge/_data/") and name.endswith(".json")}
        required = {"blocks-paper-26.2.json", "game-paper-26.2.json", "gamerules-paper-26.2.json",
                    "legacy-blocks-v0.1.json", "legacy-blocks-v0.2.json"}
        require(required <= {PurePosixPath(name).name for name in catalogs}, "A packaged catalog is missing")
        game = catalogs["minebridge/_data/game-paper-26.2.json"]
        counts = {name: len(game[name]) for name in ("items", "effects", "entities")}
        counts.update(blocks=len(catalogs["minebridge/_data/blocks-paper-26.2.json"]["blocks"]),
                      legacyPairs=len(catalogs["minebridge/_data/legacy-blocks-v0.2.json"]["blocks"]),
                      canonicalGameRules=len(catalogs["minebridge/_data/gamerules-paper-26.2.json"]["rules"]))
        require(counts == {"items": 1537, "effects": 40, "entities": 158, "blocks": 1196,
                           "legacyPairs": 361, "canonicalGameRules": 59}, "Pinned Paper catalog coverage differs")
        wheel_dates = {entry.date_time for entry in archive.infolist()}
    with tarfile.open(sdist, "r:gz") as archive:
        members = archive.getmembers()
        safe_names([entry.name for entry in members])
        require(all(entry.isfile() or entry.isdir() for entry in members), "sdist contains links/special files")
        entries = {entry.name: entry for entry in members if entry.isfile()}
        prefix = f"minebridge-{version}/"
        require(all(entry.name == prefix.rstrip("/") or entry.name.startswith(prefix) for entry in members), "Unexpected sdist root")
        source_files = {name.removeprefix(prefix + "src/"): archive.extractfile(entry).read()
                        for name, entry in entries.items() if name.startswith(prefix + "src/minebridge/")}
        require(source_files == package, "sdist package differs from wheel")
        require(archive.extractfile(entries[prefix + "LICENSE"]).read() == license_bytes, "sdist MIT license differs")
        metadata_check(archive.extractfile(entries[prefix + "PKG-INFO"]).read(), version, project["urls"])
        epochs = {entry.mtime for entry in members}
        require(len(epochs) == 1 and all(entry.uid == entry.gid == 0 and not entry.uname and not entry.gname for entry in members),
                "sdist metadata is not canonical")
        epoch = int(next(iter(epochs)))
        require(struct.unpack("<I", sdist.read_bytes()[4:8])[0] == epoch, "gzip and tar epochs differ")
        date = list(time.gmtime(epoch)[:6]); date[5] -= date[5] % 2
        require(wheel_dates == {tuple(date)}, "Wheel timestamps differ from SOURCE_DATE_EPOCH")
    with zipfile.ZipFile(jar) as archive:
        jar_names = archive.namelist()
        safe_names(jar_names)
        descriptor = archive.read("plugin.yml").decode("utf-8")
        match = re.search(r"(?m)^version:\s*['\"]?([^'\"\s]+)", descriptor)
        require(match is not None and match.group(1) == version, "JAR version differs from wheel")
        require(archive.read("META-INF/LICENSE-minebridge.txt") == license_bytes, "JAR MIT license differs")
        require(archive.read("META-INF/THIRD_PARTY_NOTICES.md") == (ROOT / "THIRD_PARTY_NOTICES.md").read_bytes(),
                "JAR third-party notices differ")
        apache = archive.read("META-INF/LICENSE").decode("utf-8")
        notice = archive.read("META-INF/NOTICE").decode("utf-8")
        require("Apache License" in apache and "Version 2.0" in apache and "jackson" in notice.lower(),
                "Jackson Apache license/notice is missing")
        for name in ("META-INF/FastDoubleParser-LICENSE", "META-INF/FastDoubleParser-ThirdParty-LICENSE", "META-INF/Schubfach-LICENSE"):
            require(bool(archive.read(name).strip()), "Bundled third-party license is missing: " + name)
        require(not any(name.startswith(("dev/minebridge/observer/", "com/fasterxml/jackson/")) or name.endswith("Test.class")
                        for name in jar_names), "Production JAR includes observer/tests/unrelocated Jackson")
        require(not any(name.startswith(("org/bukkit/", "net/minecraft/", "io/papermc/")) for name in jar_names),
                "Production JAR unexpectedly bundles Paper/Minecraft classes")
        require(any(name.startswith("dev/minebridge/internal/jackson/core/") for name in jar_names), "Shaded Jackson is missing")
        classes = [name for name in jar_names if name.startswith("dev/minebridge/") and "/internal/" not in name and name.endswith(".class")]
        require("dev/minebridge/BridgePlugin.class" in classes, "Plugin entry class is missing")
        for name in classes:
            magic, minor, major = struct.unpack(">IHH", archive.read(name)[:8])
            require(magic == 0xCAFEBABE and major == 69, "Production class is not Java 25: " + name)
    return {"version": version, "metadata": meta, "wheelEntries": len(names), "packageFiles": len(package),
            "recordVerified": True, "sdistMatchesWheelPackage": True, "registryCounts": counts,
            "sourceDateEpoch": epoch, "jarAudit": {"javaClassMajor": 69, "productionClasses": len(classes),
                "observerAndTestsExcluded": True, "jacksonRelocated": True, "licensesAndNoticesVerified": True}}


INSTALLED_CHECK = r'''
import base64, hashlib, importlib.metadata as metadata, importlib.resources as resources
import json, pathlib, socket, sys, sysconfig, zipfile
attempts=[]
def deny(*args,**kwargs):
    attempts.append('network')
    raise AssertionError('Offline import attempted a connection')
socket.create_connection=socket.socket.connect=socket.socket.connect_ex=deny
import minebridge
from minebridge import Minecraft,block,items,effects,entity,selector,events,slots,gamemode,weather,gamerule,damageCause,errors
distribution=metadata.distribution('minebridge')
package=pathlib.Path(minebridge.__file__).resolve().parent
sites={pathlib.Path(sysconfig.get_path(name)).resolve() for name in ('purelib','platlib')}
assert package.parent in sites,(package,sites)
assert pathlib.Path(distribution.locate_file('minebridge/__init__.py')).resolve()==package/'__init__.py'
assert minebridge.__version__==distribution.version==sys.argv[1]
assert not distribution.requires and not attempts
assert resources.files('minebridge').joinpath('py.typed').is_file()
assert selector.playerByName('YourNick').expression=='@a[name=YourNick,limit=1]'
assert errors.PeacefulSpawnError.code=='PEACEFUL_SPAWN_BLOCKED'
assert issubclass(errors.PeacefulSpawnError,errors.MinecraftError)
assert block.COBBLESTONE.id==4 and entity.GIANT.key=='minecraft:giant'
assert events.BLOCK_HIT is events.BLOCK_INTERACT and slots.OFF_HAND.value=='off_hand'
assert len(items.__all__)==1537 and len(effects.__all__)==40 and len(entity.__all__)==158
assert len(gamerule.__all__)==82 and len(damageCause.DamageCause)==33
assert len({getattr(events,name).key for name in events.__all__})==14
verified=0
with zipfile.ZipFile(sys.argv[2]) as wheel:
    for name in wheel.namelist():
        if not name.startswith('minebridge/'):continue
        assert pathlib.Path(distribution.locate_file(name)).read_bytes()==wheel.read(name),name
        verified+=1
for entry in distribution.files:
    name=str(entry).replace('\\','/')
    if not name.startswith('minebridge/') or name.endswith('.pyc'):continue
    content=pathlib.Path(distribution.locate_file(entry)).read_bytes()
    assert entry.hash is not None and len(content)==entry.size,name
    actual=base64.urlsafe_b64encode(hashlib.new(entry.hash.mode,content).digest()).rstrip(b'=').decode()
    assert actual==entry.hash.value,name
assert not attempts
print(json.dumps({'python':sys.version,'executable':sys.executable,'package':str(package),'version':distribution.version,
                  'networkAttempts':len(attempts),'packageFilesVerified':verified,'sysPath':sys.path}))
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("wheel", "sdist", "jar"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--version", help="Defaults to the current pyproject version")
    parser.add_argument("--python", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, help="Optional audit result JSON")
    args = parser.parse_args()
    version = args.version or tomllib.loads((ROOT / "python/pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    wheel, sdist, jar = (getattr(args, name).resolve() for name in ("wheel", "sdist", "jar"))
    result = {"passed": False, "version": version}
    try:
        result.update(archives(wheel, sdist, jar, version))
        twine = subprocess.run([sys.executable, "-I", "-m", "twine", "check", "--strict", str(wheel), str(sdist)],
                               cwd=ROOT, capture_output=True, text=True, timeout=120)
        require(twine.returncode == 0, "Strict metadata/README check failed: " + (twine.stdout + twine.stderr)[-4000:])
        result["twineStrict"] = True
        result["installedInterpreters"] = []
        with tempfile.TemporaryDirectory(prefix="minebridge-release-audit-") as outside:
            for python in args.python:
                completed = subprocess.run([str(python.resolve()), "-I", "-c", INSTALLED_CHECK, version, str(wheel)],
                                           cwd=outside, capture_output=True, text=True, timeout=45)
                require(completed.returncode == 0, "Installed wheel check failed: " + (completed.stdout + completed.stderr)[-4000:])
                runtime = json.loads(completed.stdout)
                require(not any(Path(entry).resolve() == ROOT / "python/src" for entry in runtime["sysPath"]), "Source path leaked into isolated import")
                result["installedInterpreters"].append(runtime)
        result["artifacts"] = {name: {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size}
                               for name, path in (("wheel", wheel), ("sdist", sdist), ("jar", jar))}
        result["passed"] = True
        print(json.dumps(result, indent=2))
    finally:
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
