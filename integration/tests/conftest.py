"""Standard-library integration fixtures (the historical filename is intentional).

No pytest dependency, server download, build, EULA acceptance or recursive
deletion is performed here. Each invocation creates a new isolated workspace.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import queue
import re
import secrets
import shutil
import socket
import subprocess
import threading
import time
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[2]
BRIDGE_PORT = 4711
WORLD_NAME = "t08-world"


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def free_game_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def require_port_free(port: int) -> None:
    with socket.socket() as probe:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        probe.bind(("127.0.0.1", port))


class Harness:
    def __init__(self, wheel: Path, *, run_id: str | None = None, stage: str = "T08") -> None:
        if stage not in ("T08", "T09", "T10"):
            raise ValueError("An explicitly supported integration stage is required")
        self.stage = stage
        self.world_name = stage.lower() + "-world"
        self.wiretap = None
        self.trace_offsets: dict[str, int] = {}
        self.run_id = run_id or uuid.uuid4().hex
        if not re.fullmatch(r"[0-9a-f]{32}", self.run_id):
            raise ValueError("A new lowercase hexadecimal run ID is required")
        self.workspace = ROOT / ".work" / (stage.lower() + "-" + self.run_id)
        self.server = self.workspace / "server"
        self.artifacts = ROOT / "integration/artifacts" / (stage.lower() + "-" + self.run_id)
        self.toolchain = json.loads((ROOT / ".tools/t02-toolchain.json").read_text(encoding="utf-8"))
        self.java = Path(self.toolchain["javaHome"]) / "bin/java.exe"
        self.python = ROOT / (".venv-t10-314/Scripts/python.exe" if stage == "T10"
                              else ".venv-t01-314/Scripts/python.exe")
        self.wheel = wheel.resolve()
        self.production = ROOT / "plugin/build/libs/minebridge-paper-0.1.0-dev.jar"
        self.observer = ROOT / "integration/observer-plugin/build/libs/minebridge-observer-0.1.0-dev.jar"
        self.token = secrets.token_urlsafe(32)
        self.game_port = free_game_port()
        self.manifest: dict = {}

    def prepare(self) -> None:
        require_port_free(BRIDGE_PORT)
        if self.workspace.exists() or self.artifacts.exists():
            raise RuntimeError("A run ID cannot reuse an earlier workspace or evidence directory")
        for artifact in (self.java, self.python, self.wheel, self.production, self.observer):
            if not artifact.is_file():
                raise RuntimeError("Required prebuilt artifact is missing: " + str(artifact))
        paper = Path(self.toolchain["paperJar"])
        if sha256(paper) != self.toolchain["artifacts"]["paper"]["sha256"]:
            raise RuntimeError("Pinned Paper SHA-256 verification failed")
        consent = ROOT / ".work/t02-server/eula.txt"
        if not consent.is_file() or "eula=true" not in (
            line.strip() for line in consent.read_text(encoding="utf-8").splitlines()
        ):
            raise RuntimeError("Existing project operator EULA consent is required; no consent is created")
        self.verify_installed_wheel()
        self.server.mkdir(parents=True)
        self.artifacts.mkdir(parents=True)
        copied_cache: list[str] = []
        # Only immutable/bootstrap caches, never prior worlds/plugins/configuration.
        for name in ("libraries", "cache", "versions"):
            source = ROOT / ".work/t02-server" / name
            if source.is_dir():
                shutil.copytree(source, self.server / name)
                copied_cache.append(name)
        shutil.copy2(consent, self.server / "eula.txt")
        plugin_dir = self.server / "plugins"
        (plugin_dir / "Minebridge").mkdir(parents=True)
        shutil.copy2(self.production, plugin_dir / "Minebridge.jar")
        shutil.copy2(self.observer, plugin_dir / "MinebridgeObserver.jar")
        (plugin_dir / "Minebridge/config.yml").write_text(
            "listenAddress: '127.0.0.1'\nport: 4711\n"
            f"defaultWorld: '{self.world_name}'\ntoken: {json.dumps(self.token)}\n", encoding="utf-8")
        template = (ROOT / "integration/configs/server.properties").read_text(encoding="utf-8")
        (self.server / "server.properties").write_text(
            template.format(game_port=self.game_port, world_name=self.world_name), encoding="utf-8")
        self.manifest = {
            "schemaVersion": 1, "stage": self.stage, "runId": self.run_id,
            "contract": "v0.1-r1/protocol-1.0", "server": str(self.server),
            "world": {"name": self.world_name, "seed": "20261021", "fresh": True},
            "network": {"address": "127.0.0.1", "bridgePort": BRIDGE_PORT,
                        "gamePort": self.game_port, "rcon": False, "query": False},
            "toolchain": self.toolchain,
            "artifacts": {"paper": self.describe(paper), "production": self.describe(self.production),
                          "observer": self.describe(self.observer), "wheel": self.describe(self.wheel)},
            "eula": {"source": str(consent), "sha256": sha256(consent),
                     "copiedExistingConsent": True, "acceptedAutomatically": False,
                     "authorization": "Existing project test-server consent supplied by user on 2026-10-20"},
            "bootstrapCachesCopied": copied_cache,
            "scope": {"T08": "Observer/gate acceptance only; complete T09/T10 matrix remains pending",
                      "T09": "V01-V07/D01-D04 acceptance; complete N/F matrix remains T10",
                      "T10": "Complete V/D/N/F technical-prototype acceptance"}[self.stage],
            "modes": [], "allPassed": False,
        }
        self.save_manifest()

    @staticmethod
    def describe(path: Path) -> dict:
        return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size}

    def verify_installed_wheel(self) -> None:
        # Compare all importable/data payloads with the installed package using
        # the isolated interpreter. Never import the project source directory.
        with zipfile.ZipFile(self.wheel) as archive:
            expected = {name: hashlib.sha256(archive.read(name)).hexdigest()
                        for name in archive.namelist()
                        if name.startswith("minebridge/") and not name.endswith("/")}
        script = ("import hashlib,json,pathlib,sys,minebridge;"
                  "base=pathlib.Path(minebridge.__file__).resolve().parent.parent;"
                  "expected=json.loads(sys.stdin.read());"
                  "actual={name:hashlib.sha256((base/name).read_bytes()).hexdigest() for name in expected};"
                  "assert actual==expected,'Installed package differs from selected wheel';"
                  "print(json.dumps({'python':sys.version.split()[0],'package':str(base/'minebridge')}))")
        completed = subprocess.run([str(self.python), "-I", "-c", script],
                                   input=json.dumps(expected), text=True, encoding="utf-8",
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if completed.returncode != 0:
            raise RuntimeError("Installed isolated interpreter does not match the selected wheel")
        self.installed = json.loads(completed.stdout)

    def save_manifest(self) -> None:
        (self.artifacts / "manifest.json").write_text(json.dumps(self.manifest, indent=2) + "\n", encoding="utf-8")


class PaperRun:
    def __init__(self, harness: Harness, *, control: bool, mode: str | None = None) -> None:
        self.harness, self.server, self.control = harness, harness.server, control
        self.mode = mode or ("control-enabled" if control else "control-disabled")
        if not re.fullmatch(r"[a-z0-9-]{1,48}", self.mode):
            raise ValueError("A safe local mode name is required")
        self.log = harness.artifacts / (self.mode + ".log")
        self.lines: list[str] = []
        self.events: queue.Queue[str] = queue.Queue()
        self.process: subprocess.Popen | None = None
        self.reader: threading.Thread | None = None
        self.stop_requested = False
        self.secret_seen = False

    def __enter__(self) -> PaperRun:
        require_port_free(BRIDGE_PORT)
        self.process = subprocess.Popen(
            [str(self.harness.java), "-Xms512M", "-Xmx1G",
             "-Dminebridge.testControl=" + str(self.control).lower(),
             "-jar", self.harness.toolchain["paperJar"], "--nogui"],
            cwd=self.server, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

        def capture() -> None:
            assert self.process is not None and self.process.stdout is not None
            with self.log.open("w", encoding="utf-8") as stream:
                for raw in self.process.stdout:
                    # Never retain credentials, even on failure paths.
                    self.secret_seen |= self.harness.token in raw
                    line = raw.replace(self.harness.token, "<redacted>")
                    stream.write(line)
                    stream.flush()
                    self.lines.append(line)
                    self.events.put(line)
        self.reader = threading.Thread(target=capture, daemon=True)
        self.reader.start()
        return self

    def wait_ready(self) -> None:
        deadline = time.monotonic() + 300
        done = listener = observer = False
        while time.monotonic() < deadline:
            try:
                line = self.events.get(timeout=0.2)
            except queue.Empty:
                if self.process.poll() is not None:
                    break
                continue
            done |= "Done (" in line
            listener |= "TCP listener ready on port 4711." in line
            observer |= "[MinebridgeObserver]" in line and "Enabling" in line
            if done and listener and observer:
                return
        raise AssertionError("Fresh Paper readiness deadline elapsed; inspect " + str(self.log))

    def command(self, command: str) -> None:
        if "\n" in command or "\r" in command or len(command) > 8192:
            raise ValueError("Console commands must be one bounded line")
        if self.process.poll() is not None:
            raise AssertionError("Paper already exited")
        self.process.stdin.write(command + "\n")
        self.process.stdin.flush()

    def finish(self) -> dict:
        if not self.stop_requested and self.process.poll() is None:
            self.command("stop")
            self.stop_requested = True
        self.process.wait(timeout=60)
        self.reader.join(timeout=5)
        if self.reader.is_alive() or self.process.returncode != 0:
            raise AssertionError("Paper did not terminate cleanly")
        if self.secret_seen:
            raise AssertionError("Lesson token appeared in Paper output (evidence has been redacted)")
        if not any("[Minebridge] Lifecycle stopped." in line for line in self.lines):
            raise AssertionError("Production plugin shutdown was not observed")
        if any(re.search(r"\b(?:ERROR|SEVERE|FATAL)\]:", line) for line in self.lines):
            raise AssertionError("Unexpected Paper error; inspect " + str(self.log))
        require_port_free(BRIDGE_PORT)
        return {"mode": self.mode, "passed": True, "exitCode": self.process.returncode,
                "log": str(self.log), "productionSha256": sha256(self.harness.production)}

    def __exit__(self, *_: object) -> None:
        if self.process is not None and self.process.poll() is None:
            try:
                if not self.stop_requested:
                    self.command("stop")
                self.process.wait(timeout=40)
            except (OSError, subprocess.TimeoutExpired):
                self.process.kill()
                self.process.wait(timeout=10)
        if self.reader is not None:
            self.reader.join(timeout=5)
        if self.process is not None:
            for pipe in (self.process.stdin, self.process.stdout):
                if pipe is not None:
                    pipe.close()


class FacadeClient:
    def __init__(self, harness: Harness, name: str, *, port: int | None = None,
                 timeout: float = 30.0, env_token: bool = True) -> None:
        self.harness, self.name = harness, name
        self.process: subprocess.Popen | None = None
        self.events: queue.Queue[dict | None] = queue.Queue()
        self.outputs: list[dict] = []
        self.errors: list[str] = []
        self.threads: list[threading.Thread] = []
        self.closed = False
        self.context: dict = {}
        self.port, self.timeout, self.env_token = port, timeout, env_token

    def __enter__(self) -> FacadeClient:
        environment = os.environ.copy()
        if self.env_token:
            environment["MINEBRIDGE_TOKEN"] = self.harness.token
        else:
            environment.pop("MINEBRIDGE_TOKEN", None)
        environment["MINEBRIDGE_TEST_PORT"] = str(
            self.port if self.port is not None else
            (self.harness.wiretap.port if self.harness.wiretap is not None else BRIDGE_PORT))
        environment["MINEBRIDGE_TEST_TIMEOUT"] = str(self.timeout)
        self.process = subprocess.Popen(
            [str(self.harness.python), "-I", str(ROOT / "integration/tests/facade_worker.py")],
            cwd=ROOT, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

        def output() -> None:
            for line in self.process.stdout:
                if len(line) > 16384 or self.harness.token in line:
                    self.events.put({"type": "fatal", "error": "UnsafeOutput"})
                    continue
                try:
                    value = json.loads(line)
                except ValueError:
                    value = {"type": "fatal", "error": "InvalidOutput"}
                self.outputs.append(value)
                self.events.put(value)
            self.events.put(None)

        def errors() -> None:
            for line in self.process.stderr:
                if len(self.errors) < 32:
                    self.errors.append(line.replace(self.harness.token, "<redacted>"))

        self.threads = [threading.Thread(target=output, daemon=True), threading.Thread(target=errors, daemon=True)]
        for thread in self.threads:
            thread.start()
        try:
            self.context = self.response()
            if self.context.get("type") != "ready":
                raise AssertionError("Installed public client did not complete hello")
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def response(self, *, timeout: float = 10) -> dict:
        try:
            result = self.events.get(timeout=timeout)
        except queue.Empty:
            raise AssertionError("Installed public client response deadline elapsed") from None
        if result is None or result.get("type") == "fatal":
            raise AssertionError("Installed public client stopped unexpectedly")
        return result

    def send(self, command: dict) -> None:
        self.process.stdin.write(json.dumps(command, allow_nan=False) + "\n")
        self.process.stdin.flush()

    def set(self, position: list[int | float], material: object, *, route: str = "root",
            form: str = "constant", data: int = 0) -> str:
        command_id = uuid.uuid4().hex
        self.send({"op": "set", "position": position, "material": material,
                   "route": route, "form": form, "data": data, "commandId": command_id})
        return command_id

    def reopen(self, position: list[int]) -> dict:
        self.send({"op": "reopen", "position": position})
        result = self.response()
        if result.get("type") != "reopened":
            raise AssertionError("Public close/reopen did not complete")
        self.context = result
        return result

    def success(self, command_id: str) -> dict:
        result = self.response()
        if result != {"type": "result", "commandId": command_id, "ok": True, "returnedNone": True}:
            raise AssertionError("Public setBlock did not return None after successful ACK")
        return result

    def assert_pending(self) -> None:
        # The worker answers through the same ordered stdout as call results.
        # A result already emitted cannot hide behind a delayed parent reader.
        probe_id = uuid.uuid4().hex
        self.send({"op": "pending", "probeId": probe_id})
        if self.response() != {"type": "pending", "probeId": probe_id, "pending": True}:
            raise AssertionError("Public call completed while its server request remained gated")

    def close(self) -> list[dict]:
        if self.closed:
            return []
        self.send({"op": "close"})
        observed: list[dict] = []
        deadline = time.monotonic() + 7
        while True:
            result = self.response(timeout=max(.01, deadline - time.monotonic()))
            observed.append(result)
            if result.get("type") == "closed" and result.get("closed") is True:
                break
            if time.monotonic() >= deadline:
                raise AssertionError("Public close did not interrupt the pending request")
        self.closed = True
        return observed

    def __exit__(self, *_: object) -> None:
        if self.process is None:
            return
        try:
            if self.process.poll() is None and not self.closed:
                self.close()
        finally:
            if self.process.stdin is not None:
                self.process.stdin.close()
            try:
                self.process.wait(timeout=7)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
            for thread in self.threads:
                thread.join(timeout=3)
            for pipe in (self.process.stdout, self.process.stderr):
                if pipe is not None:
                    pipe.close()
            (self.harness.artifacts / (self.name + ".json")).write_text(
                json.dumps({"events": self.outputs, "stderr": self.errors,
                            "exitCode": self.process.returncode}, indent=2) + "\n", encoding="utf-8")
        if any(thread.is_alive() for thread in self.threads) or self.errors or self.process.returncode != 0:
            raise AssertionError("Installed public client did not terminate cleanly")
