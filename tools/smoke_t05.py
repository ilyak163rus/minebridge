"""T05 on pinned real Paper: hello/auth/worlds and two installed-wheel processes.

Uses the previously accepted EULA of this project's local test server. The extra
fixture only reads world metadata; no block operation or public facade is tested.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import queue
import secrets
import select
import shutil
import socket
import subprocess
import threading
import time
from uuid import UUID

import smoke_t02
from smoke_t04 import (PaperRun as TransportPaperRun, check_refused, configuration,
                       connect, expect_close, expect_error, free_port)

ROOT = Path(__file__).resolve().parents[1]
SERVER = smoke_t02.SERVER
PYTHON = ROOT / ".venv-t01-314/Scripts/python.exe"
PROBE_NAME = "minebridge-world-metadata-probe-0.1.0-dev.jar"
METADATA = SERVER / "plugins/MinebridgeWorldMetadataProbe/worlds.tsv"


class PaperRun(TransportPaperRun):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)
        self.log = ROOT / ".work" / f"t05-paper-{self.name}.log"

    def __enter__(self) -> PaperRun:
        METADATA.unlink(missing_ok=True)
        super().__enter__()
        return self


def read_worlds() -> list[dict]:
    worlds = []
    for row in METADATA.read_text(encoding="utf-8").splitlines():
        encoded_name, world_id, minimum, maximum = row.split("\t")
        worlds.append({"name": base64.b64decode(encoded_name, validate=True).decode("utf-8"),
                       "uuid": str(UUID(world_id)), "minY": int(minimum), "maxYExclusive": int(maximum)})
    if not worlds:
        raise AssertionError("Read-only metadata fixture found no loaded worlds")
    return worlds


def request(request_id: int, method: str, params: dict) -> bytes:
    return json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method,
                       "params": params}, separators=(",", ":")).encode() + b"\n"


def hello(token: str, world: str | None = None) -> dict:
    return {"protocol": {"major": 1, "minor": 0}, "token": token,
            "world": world, "coordinates": "absolute"}


def read_response(peer: socket.socket) -> dict:
    data = bytearray()
    deadline = time.monotonic() + 5
    while True:
        peer.settimeout(max(0.001, deadline - time.monotonic()))
        byte = peer.recv(1)
        if byte == b"\n":
            return json.loads(data.decode("utf-8"))
        if not byte or len(data) >= 65536 or time.monotonic() >= deadline:
            raise AssertionError("Missing bounded RPC response")
        data.extend(byte)


def ready(peer: socket.socket, token: str, expected: dict, world: str | None = None,
          minor: int = 0) -> dict:
    params = hello(token, world)
    params["protocol"]["minor"] = minor
    peer.sendall(request(1, "system.hello", params))
    response = read_response(peer)
    if response.get("jsonrpc") != "2.0" or response.get("id") != 1 or "error" in response:
        raise AssertionError("Expected successful hello")
    result = response["result"]
    if (result["protocol"] != {"major": 1, "minor": 0} or result["world"] != expected
            or result["serverVersion"] != "26.2" or result["pluginVersion"] != "0.1.0-dev"
            or result["coordinates"] != "absolute" or result["chunkPolicy"] != "loaded-only"
            or result["applyPhysics"] is not True or result["capabilities"] != ["blocks.set"]):
        raise AssertionError("Hello context differs from contract or independent world metadata")
    UUID(result["sessionId"])
    expected_limits = {"maxFrameBytes": 65536, "maxJsonDepth": 16, "maxSessions": 8,
                       "maxQueuedRequests": 8, "maxOutputFrames": 8,
                       "handshakeTimeoutSeconds": 5, "frameAssemblyTimeoutSeconds": 5,
                       "writeTimeoutSeconds": 5, "maxOperationsPerTick": 32,
                       "maxOperationsPerSessionPerTick": 4, "executorBudgetMillis": 2}
    if result["limits"] != expected_limits:
        raise AssertionError("Hello advertised different active limits")
    return result


class PythonPeer:
    """Two persistent child interpreters prove contexts coexist, rather than reconnecting."""

    def __init__(self, port: int, token: str, world: str | None = None) -> None:
        command = [str(PYTHON), "-I", str(ROOT / "tools/check_t05_client.py"), "--port", str(port)]
        if world is not None:
            command.extend(["--world", world])
        environment = os.environ.copy()
        environment["MINEBRIDGE_TOKEN"] = token
        self.process = subprocess.Popen(command, cwd=ROOT, env=environment,
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.events: queue.Queue[str | None] = queue.Queue()
        self.lines: list[str] = []
        self.token = token

        def capture() -> None:
            assert self.process.stdout is not None
            for line in self.process.stdout:
                self.lines.append(line)
                self.events.put(line)
            self.events.put(None)

        self.reader = threading.Thread(target=capture, daemon=True)
        self.reader.start()

    def receive(self, event: str) -> dict:
        try:
            line = self.events.get(timeout=10)
        except queue.Empty:
            raise AssertionError("Installed-wheel child did not reply") from None
        try:
            value = json.loads(line) if line is not None else {}
        except (ValueError, TypeError):
            raise AssertionError("Installed-wheel child failed; no peer text is echoed") from None
        if value.get("event") != event:
            raise AssertionError("Unexpected installed-wheel child event")
        return value

    def send(self, command: str) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(command + "\n")
        self.process.stdin.flush()

    def probe(self) -> None:
        self.send("probe")
        assert self.receive("probe")["code"] == "METHOD_NOT_FOUND"

    def __enter__(self) -> PythonPeer:
        return self

    def __exit__(self, *_: object) -> None:
        try:
            if self.process.poll() is None:
                self.send("close")
                self.receive("closed")
            self.process.wait(timeout=10)
            if self.process.returncode != 0:
                raise AssertionError("Installed-wheel child exited unsuccessfully")
        finally:
            if self.process.poll() is None:
                self.process.kill()
                self.process.wait(timeout=10)
            self.reader.join(timeout=5)
            if self.process.stdin is not None:
                self.process.stdin.close()
            if self.process.stdout is not None:
                self.process.stdout.close()
            if self.reader.is_alive():
                raise AssertionError("Client output reader leaked")
            if self.token in "".join(self.lines):
                raise AssertionError("Test token appeared in child output")


def check_python_context(context: dict, expected: dict) -> None:
    if context["world"] != {"name": expected["name"], "uuid": expected["uuid"],
                            "min_y": expected["minY"], "max_y_exclusive": expected["maxYExclusive"]}:
        raise AssertionError("Installed-wheel context differs from read-only fixture")
    UUID(context["session_id"])
    if context["protocol"] != {"major": 1, "minor": 0}:
        raise AssertionError("Wrong negotiated Python context")


def handshake_checks(port: int, token: str, worlds: list[dict], default: dict) -> list[str]:
    checks: list[str] = []
    with PythonPeer(port, token) as a, PythonPeer(port, token, default["name"]) as b:
        a_context = a.receive("ready")["context"]
        b_context = b.receive("ready")["context"]
        check_python_context(a_context, default)
        check_python_context(b_context, default)
        if a_context["session_id"] == b_context["session_id"]:
            raise AssertionError("Two Python processes shared a session UUID")
        a.probe()
        b.probe()
        checks.append("two-simultaneous-installed-wheel-processes-distinct-contexts-ID1")
        with connect(port) as partial:
            partial.sendall(b'{"jsonrpc":')
            b.probe()
            if select.select([partial], [], [], 0)[0]:
                raise AssertionError("Partial A closed before B completed")
            partial.sendall(b'\xff\n')
            expect_close(partial)
            b.probe()
        checks.append("partial-and-malformed-A-did-not-block-authorized-B")
        invalids: list[tuple[str, dict, str]] = []
        for label, wrong in (("wrong-token", token + "-wrong"), ("empty-token", ""), ("blank-token", " \t")):
            invalids.append((label, {**hello(token), "token": wrong}, "AUTH_FAILED"))
        missing = hello(token)
        del missing["token"]
        invalids.extend([
            ("missing-token", missing, "INVALID_PARAMS"),
            ("extra-param", {**hello(token), "unexpected": True}, "INVALID_PARAMS"),
            ("major", {**hello(token), "protocol": {"major": int("9" * 300), "minor": 0}}, "PROTOCOL_VERSION"),
            ("coordinates", {**hello(token), "coordinates": "relative"}, "UNSUPPORTED_FEATURE"),
            ("missing-world", hello(token, "__t05_absent_world__"), "WORLD_NOT_FOUND"),
        ])
        forbidden = next((world for world in worlds if world["uuid"] != default["uuid"]), None)
        if forbidden is None:
            raise AssertionError("A second loaded world is required for real permission/defaultWorld checks")
        invalids.append(("forbidden-world", hello(token, forbidden["name"]), "PERMISSION_DENIED"))
        for label, params, code in invalids:
            with connect(port) as bad:
                bad.sendall(request(1, "system.hello", params))
                expect_error(bad, code, 1)
                expect_close(bad)
            b.probe()
            checks.append(label + "-isolated-close")
        with connect(port) as bad:
            bad.sendall(request(1, "blocks.set", {}))
            expect_error(bad, "NOT_READY", 1)
            expect_close(bad)
        checks.append("state-checked-before-mutation-params")
        with connect(port) as peer:
            ready(peer, token, default, minor=int("9" * 300))
            peer.sendall(request(2, "system.hello", {}))
            expect_error(peer, "INVALID_STATE", 2)
            expect_close(peer)
        checks.append("large-minor-negotiated-zero-and-repeated-hello-invalid-state")
        with connect(port) as peer:
            selected = ready(peer, token, default)
            peer.sendall(request(2, "blocks.set", {
                "world": selected["world"]["name"], "position": [0, default["minY"], 0],
                "block": {"key": "minecraft:stone", "states": {}},
            }))
            expect_error(peer, "UNSUPPORTED_FEATURE", 2)
            peer.sendall(request(3, "future", {}))
            expect_error(peer, "METHOD_NOT_FOUND", 3)
        checks.append("T06-not-implemented-no-false-block-ACK-and-READY-retained")
        with connect(port) as unready:
            started = time.monotonic()
            expect_close(unready, timeout=6.5)
            if time.monotonic() - started < 3.5:
                raise AssertionError("Unready connection deadline fired too early")
        # A/B have remained READY for longer than the server's handshake deadline.
        a.probe()
        b.probe()
        checks.append("unready-deadline-and-idle-READY-survives-beyond-five-seconds")
    return checks


def main() -> None:
    result_file = ROOT / ".work/t05-paper-results.json"
    result_file.parent.mkdir(parents=True, exist_ok=True)
    cases: list[dict] = []
    success = False
    port = free_port()

    def save() -> None:
        result_file.write_text(json.dumps({"paper": "26.2-133", "tcpPort": port,
                                          "cases": cases, "allPassed": success}, indent=2) + "\n", encoding="utf-8")

    save()
    toolchain = smoke_t02.prepare()
    if "eula=true" not in [line.strip() for line in (SERVER / "eula.txt").read_text(encoding="utf-8").splitlines()]:
        raise RuntimeError("Existing operator EULA consent is required")
    fixture = ROOT / "plugin/build/test-fixtures" / PROBE_NAME
    if not fixture.is_file():
        raise RuntimeError("Build worldMetadataProbeJar before this test")
    deployed_fixture = (SERVER / "plugins" / PROBE_NAME).resolve()
    if not deployed_fixture.is_relative_to((ROOT / ".work").resolve()):
        raise RuntimeError("Fixture path must remain inside the local workspace server")
    shutil.copy2(fixture, deployed_fixture)
    token = secrets.token_urlsafe(32)
    config = configuration(port, token)
    try:
        with PaperRun(toolchain, "handshake", config, token) as paper:
            paper.wait(f"TCP listener ready on port {port}.")
            worlds = read_worlds()
            default = next(world for world in worlds if world["name"] == "t02-world")
            checks = handshake_checks(port, token, worlds, default)
            with connect(port) as first, connect(port) as second:
                first_context = ready(first, token, default)
                second_context = ready(second, token, default)
                if first_context["sessionId"] == second_context["sessionId"]:
                    raise AssertionError("Simultaneous raw ID1 requests shared a context")
                paper.request_stop()
                expect_close(first, timeout=5)
                expect_close(second, timeout=5)
            checks.append("stop-closes-two-READY-sessions")
            result = paper.finish()
            result.update(checks=checks, worlds=worlds)
            cases.append(result)
        check_refused(port)
        alternate = next(world for world in worlds if world["uuid"] != default["uuid"])
        with PaperRun(toolchain, "alternate-default", configuration(port, token, alternate["name"]), token) as paper:
            paper.wait(f"TCP listener ready on port {port}.")
            current = next(world for world in read_worlds() if world["uuid"] == alternate["uuid"])
            with connect(port) as peer:
                ready(peer, token, current)
            with connect(port) as peer:
                peer.sendall(request(1, "system.hello", hello(token, default["name"])))
                expect_error(peer, "PERMISSION_DENIED", 1)
                expect_close(peer)
            cases.append({**paper.finish(), "checks": ["configured-alternate-default-selected-without-first-world-fallback"]})
        check_refused(port)
        with socket.socket() as occupied:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                occupied.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            occupied_port = occupied.getsockname()[1]
            message = "Cannot start TCP listener; check listenAddress and whether port is already in use."
            with PaperRun(toolchain, "occupied-port", configuration(occupied_port, token), token) as paper:
                paper.wait(message)
                cases.append(paper.finish(expected_error=message))
        for name, invalid, message in (
            ("blank-token", configuration(port, ""), "token must be a nonblank string"),
            ("missing-world", configuration(port, token, "__missing_world__"), "Configured defaultWorld is not loaded"),
            ("invalid-yaml", "token: [\n", "Cannot read config.yml"),
        ):
            with PaperRun(toolchain, name, invalid, token) as paper:
                paper.wait(message)
                check_refused(port)
                cases.append(paper.finish(expected_error=message))
        success = True
    finally:
        deployed_fixture.unlink(missing_ok=True)
        (SERVER / "plugins/Minebridge/config.yml").write_text(config, encoding="utf-8")
        save()
    print(json.dumps(json.loads(result_file.read_text(encoding="utf-8")), indent=2))


if __name__ == "__main__":
    main()
