"""Correlate new 0.3.1 IDE evidence with the exact installed final wheel."""

import hashlib
import json
import os
from pathlib import Path
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[3]


def main() -> None:
    result_path = ROOT / ".work/ide-v031-results.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "passed"
    config = result["config"]
    assert os.path.samefile(sys.executable, config["python"])
    package = Path(config["installedPackage"]).resolve()
    wheel = Path(config["wheel"]).resolve()
    hashes = {}
    try:
        with zipfile.ZipFile(wheel) as archive:
            for name in archive.namelist():
                if not name.startswith("minebridge/") or name.endswith("/"):
                    continue
                data = archive.read(name)
                assert (package / name.removeprefix("minebridge/")).read_bytes() == data, name
                hashes[name] = hashlib.sha256(data).hexdigest()
        assert "minebridge/py.typed" in hashes
        assert "minebridge/selector.py" in hashes and "minebridge/errors.py" in hashes
        for group in ("completions", "signatures"):
            for item in result[group].values():
                for definition in item["definitions"]:
                    name = "minebridge/" + Path(definition).resolve().relative_to(package).as_posix()
                    assert name in hashes, name
        result["artifactValidation"] = {
            "status": "passed",
            "wheel": str(wheel),
            "wheelSha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
            "installedPackageFilesCompared": len(hashes),
            "installedFileSha256": hashes,
            "helperSha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                             for path in sorted(Path(__file__).parent.iterdir()) if path.is_file()},
        }
    except BaseException as error:
        result["status"] = "failed"
        result["artifactValidation"] = {"status": "failed", "error": str(error)}
        raise
    finally:
        result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"IDE 0.3.1: {len(hashes)} installed package files match final wheel")


if __name__ == "__main__":
    main()
