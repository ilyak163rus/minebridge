"""Generate offline Python DamageCause constants from pinned Paper API133 export."""

import argparse
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def generate() -> str:
    data = json.loads((ROOT / "catalogs/paper-26.2-build133-damage-causes.json").read_text(encoding="utf-8"))
    assert data["minecraft"] == "26.2" and data["paperBuild"] == 133
    assert data["apiSha256"] == "e8079e853374d75e571a24379573e96f6dfe1581b97bae5465163c77f00f327a"
    values = data["values"]
    assert values and len(values) == len(set(values))
    assert all(re.fullmatch(r"[A-Z][A-Z0-9_]*", value) for value in values)
    lines = ['"""Damage causes exported from Paper 26.2 build133. Generated; do not edit."""',
             "", "from enum import StrEnum", "from typing import Final", "",
             "__all__ = [\"DamageCause\", " + ", ".join(repr(v) for v in values) + "]", "",
             "", "class DamageCause(StrEnum):"]
    lines += [f"    {value} = {value!r}" for value in values]
    lines += ["", ""] + [f"{value}: Final[DamageCause] = DamageCause.{value}" for value in values] + [""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = ROOT / "python/src/minebridge/damageCause.py"
    expected = generate()
    if args.check:
        if path.read_text(encoding="utf-8") != expected:
            raise SystemExit("Damage cause catalog differs; run generator")
    else:
        path.write_text(expected, encoding="utf-8", newline="\n")
    print("Damage cause catalog:33 constants verified" if args.check else "Damage cause catalog generated")


if __name__ == "__main__":
    main()
