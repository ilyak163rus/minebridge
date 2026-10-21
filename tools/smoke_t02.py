"""Real Paper lifecycle smoke test. EULA consent must be supplied by the operator."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import queue
import re
import secrets
import shutil
import socket
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / ".work" / "t02-server"


def prepare() -> dict[str, str]:
    toolchain = json.loads((ROOT / ".tools" / "t02-toolchain.json").read_text(encoding="utf-8"))
    jar = ROOT / "plugin" / "build" / "libs" / "minebridge-paper-0.1.0-dev.jar"
    if not jar.is_file():
        raise RuntimeError("Build the plugin before preparing the server")
    (SERVER / "plugins" / "Minebridge").mkdir(parents=True, exist_ok=True)
    shutil.copy2(jar, SERVER / "plugins" / "Minebridge.jar")
    eula = SERVER / "eula.txt"
    if not eula.exists():
        eula.write_text("# Operator must accept https://www.minecraft.net/en-us/eula\neula=false\n", encoding="utf-8")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    (SERVER / "server.properties").write_text(
        "server-ip=127.0.0.1\n"
        f"server-port={port}\n"
        "level-name=t02-world\n"
        "online-mode=true\n"
        "enable-rcon=false\n"
        "enable-query=false\n"
        "view-distance=2\n"
        "simulation-distance=2\n"
        "max-players=1\n"
        "pause-when-empty-seconds=-1\n",
        encoding="utf-8",
    )
    return toolchain


def config_text(world: str, token: str) -> str:
    # JSON string literals are valid YAML quoted scalars. Preserve the token exactly.
    return (
        "listenAddress: '127.0.0.1'\nport: 4711\n"
        f"defaultWorld: {json.dumps(world)}\ntoken: {json.dumps(token)}\n"
    )


def run_case(toolchain: dict[str, str], name: str, config: str, expected: str, enabled: bool) -> dict[str, object]:
    (SERVER / "plugins" / "Minebridge" / "config.yml").write_text(config, encoding="utf-8")
    java = Path(toolchain["javaHome"]) / "bin" / "java.exe"
    process = subprocess.Popen(
        [str(java), "-Xms512M", "-Xmx1G", "-jar", toolchain["paperJar"], "--nogui"],
        cwd=SERVER, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    lines: list[str] = []
    events: queue.Queue[str] = queue.Queue()

    def read_output() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            lines.append(line)
            events.put(line)

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    log = ROOT / ".work" / f"t02-{name}.log"
    try:
        deadline = time.monotonic() + 240
        ready = False
        while time.monotonic() < deadline:
            if process.poll() is not None:
                break
            try:
                line = events.get(timeout=0.5)
            except queue.Empty:
                continue
            if "Done (" in line:
                ready = True
                break
        if not ready:
            raise AssertionError(f"Paper did not reach readiness for {name}; inspect {log}")
        output = "".join(lines)
        if expected not in output:
            raise AssertionError(f"Missing lifecycle outcome for {name}; inspect {log}")
        actual_enabled = "[Minebridge] Lifecycle initialized for world" in output
        if actual_enabled != enabled:
            raise AssertionError(f"Unexpected enabled state for {name}")
        assert process.stdin is not None
        process.stdin.write("stop\n")
        process.stdin.flush()
        process.wait(timeout=60)
        reader.join(timeout=5)
        if process.returncode != 0:
            raise AssertionError(f"Unclean server exit for {name}: {process.returncode}")
        if enabled and "[Minebridge] Lifecycle stopped." not in "".join(lines):
            raise AssertionError("Plugin did not complete its shutdown")
        if enabled and any(
            re.search(r"\[\d{2}:\d{2}:\d{2} (?:ERROR|SEVERE|FATAL)\]:", line)
            for line in lines
        ):
            raise AssertionError(f"Unexpected server error for {name}; inspect {log}")
        return {"case": name, "passed": True, "exitCode": process.returncode, "log": str(log)}
    finally:
        if process.poll() is None:
            if process.stdin is not None:
                try:
                    process.stdin.write("stop\n")
                    process.stdin.flush()
                    process.wait(timeout=30)
                except (OSError, subprocess.TimeoutExpired):
                    process.kill()
                    process.wait(timeout=10)
        reader.join(timeout=5)
        log.write_text("".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true", help="Prepare files, leaving EULA false")
    arguments = parser.parse_args()
    toolchain = prepare()
    token = secrets.token_urlsafe(32)
    config_file = SERVER / "plugins" / "Minebridge" / "config.yml"
    config_file.write_text(config_text("t02-world", token), encoding="utf-8")
    if arguments.prepare:
        print("Prepared " + str(SERVER) + "; EULA consent was not changed.")
        return
    eula_lines = (SERVER / "eula.txt").read_text(encoding="utf-8").splitlines()
    if "eula=true" not in [line.strip() for line in eula_lines]:
        raise RuntimeError("Operator EULA consent is required in .work/t02-server/eula.txt")
    cases: list[dict[str, object]] = []
    success = False
    result_file = ROOT / ".work" / "t02-smoke-results.json"
    # A stopped/interrupted run must not leave an earlier successful summary.
    result_file.write_text(json.dumps({"paper": "26.2-133", "cases": [], "allPassed": False}, indent=2)
                           + "\n", encoding="utf-8")
    try:
        cases.append(run_case(toolchain, "valid", config_text("t02-world", token),
                              "[Minebridge] Lifecycle initialized for world", True))
        cases.append(run_case(toolchain, "blank-token", config_text("t02-world", ""),
                              "token must be a nonblank string", False))
        cases.append(run_case(toolchain, "missing-world", config_text("__missing_world__", token),
                              "Configured defaultWorld is not loaded", False))
        cases.append(run_case(toolchain, "invalid-yaml", "token: [\n", "Cannot read config.yml", False))
        for case in cases:
            if token in Path(str(case["log"])).read_text(encoding="utf-8"):
                raise AssertionError("A log exposed the test token")
        success = True
    finally:
        config_file.write_text(config_text("t02-world", token), encoding="utf-8")
        result = {"paper": "26.2-133", "cases": cases, "allPassed": success}
        result_file.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
