"""Real Paper T04 checks. No successful handshake or game operation is claimed."""

from __future__ import annotations

import json
from pathlib import Path
import queue
import re
import secrets
import select
import socket
import subprocess
import threading
import time

import smoke_t02

ROOT = Path(__file__).resolve().parents[1]
SERVER = smoke_t02.SERVER


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def configuration(port: int, token: str, world: str = "t02-world") -> str:
    return smoke_t02.config_text(world, token).replace("port: 4711\n", f"port: {port}\n")


class PaperRun:
    def __init__(self, toolchain: dict, name: str, config: str, token: str, *,
                 jvm_options: tuple[str, ...] = ()) -> None:
        self.name = name
        self.log = ROOT / ".work" / f"t04-paper-{name}.log"
        self.token = token
        self.lines: list[str] = []
        self.events: queue.Queue[str] = queue.Queue()
        self.reader: threading.Thread | None = None
        self.process: subprocess.Popen | None = None
        self.stop_requested = False
        self.toolchain = toolchain
        self.config = config
        self.jvm_options = jvm_options

    def __enter__(self) -> PaperRun:
        (SERVER / "plugins/Minebridge/config.yml").write_text(self.config, encoding="utf-8")
        java = str(Path(self.toolchain["javaHome"]) / "bin/java.exe")
        self.process = subprocess.Popen(
            [java, "-Xms512M", "-Xmx1G", *self.jvm_options,
             "-jar", self.toolchain["paperJar"], "--nogui"],
            cwd=SERVER, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

        def read_output() -> None:
            assert self.process is not None and self.process.stdout is not None
            for line in self.process.stdout:
                self.lines.append(line)
                self.events.put(line)

        self.reader = threading.Thread(target=read_output, daemon=True)
        self.reader.start()
        return self

    def wait(self, expected: str) -> None:
        assert self.process is not None
        deadline = time.monotonic() + 240
        done = observed = False
        while time.monotonic() < deadline:
            try:
                line = self.events.get(timeout=0.2)
            except queue.Empty:
                if self.process.poll() is not None:
                    break
                continue
            done |= "Done (" in line
            observed |= expected in line
            if done and observed:
                return
        raise AssertionError(f"Missing Paper readiness/outcome for {self.name}; inspect {self.log}")

    def request_stop(self) -> None:
        assert self.process is not None
        if self.process.poll() is None and not self.stop_requested:
            assert self.process.stdin is not None
            self.process.stdin.write("stop\n")
            self.process.stdin.flush()
            self.stop_requested = True

    def finish(self, expected_error: str | None = None) -> dict:
        assert self.process is not None
        self.request_stop()
        self.process.wait(timeout=60)
        assert self.reader is not None
        self.reader.join(timeout=5)
        if self.reader.is_alive():
            raise AssertionError("Paper output capture did not terminate")
        if self.process.returncode != 0:
            raise AssertionError(f"Unclean exit for {self.name}; inspect {self.log}")
        output = "".join(self.lines)
        if self.token in output:
            raise AssertionError(f"Test token appeared in {self.name} log")
        for line in self.lines:
            if re.search(r"\b(?:ERROR|SEVERE|FATAL)\]:", line):
                if expected_error is None or expected_error not in line:
                    raise AssertionError(f"Unexpected server error for {self.name}; inspect {self.log}")
        if expected_error is None and "[Minebridge] Lifecycle stopped." not in output:
            raise AssertionError("Plugin did not complete disable")
        return {"case": self.name, "passed": True, "exitCode": 0, "log": str(self.log)}

    def __exit__(self, *_: object) -> None:
        assert self.process is not None
        if self.process.poll() is None:
            try:
                self.request_stop()
                self.process.wait(timeout=30)
            except (OSError, subprocess.TimeoutExpired):
                self.process.kill()
                self.process.wait(timeout=10)
        if self.reader is not None:
            self.reader.join(timeout=5)
        if self.process.stdin is not None:
            self.process.stdin.close()
        if self.process.stdout is not None:
            self.process.stdout.close()
        self.log.write_text("".join(self.lines).replace(self.token, "<redacted>"), encoding="utf-8")


def connect(port: int) -> socket.socket:
    return socket.create_connection(("127.0.0.1", port), timeout=2)


def expect_close(peer: socket.socket, timeout: float = 2) -> None:
    peer.settimeout(timeout)
    try:
        value = peer.recv(1)
    except ConnectionResetError:
        return
    if value != b"":
        raise AssertionError("Expected socket closure without another response")


def expect_error(peer: socket.socket, code: str, request_id: int | None) -> None:
    # A response fits one bounded frame; never use an unbounded readline here.
    payload = bytearray()
    deadline = time.monotonic() + 2
    while True:
        peer.settimeout(max(0.001, deadline - time.monotonic()))
        byte = peer.recv(1)
        if byte == b"\n":
            break
        if not byte or len(payload) >= 65536 or time.monotonic() >= deadline:
            raise AssertionError("Expected bounded protocol error response")
        payload.extend(byte)
    value = json.loads(payload.decode("utf-8"))
    if (value.get("jsonrpc") != "2.0" or value.get("id") != request_id
            or value.get("error", {}).get("data", {}).get("code") != code
            or value["error"]["data"].get("outcome") != "not-applied"):
        raise AssertionError("Unexpected protocol error envelope")


def request(request_id: int) -> bytes:
    return json.dumps({"jsonrpc": "2.0", "id": request_id,
                       "method": "future", "params": {}}, separators=(",", ":")).encode() + b"\n"


def check_refused(port: int) -> None:
    try:
        peer = connect(port)
    except OSError:
        return
    peer.close()
    raise AssertionError("Listener remained open after disable/stop")


def transport_checks(port: int, token: str) -> list[str]:
    checks: list[str] = []
    with connect(port) as slow, connect(port) as other:
        started = time.monotonic()
        slow.sendall(b'{"jsonrpc":')
        other.sendall(b"[]\n")
        expect_error(other, "INVALID_REQUEST", None)
        expect_close(other)
        if time.monotonic() - started >= 2 or select.select([slow], [], [], 0)[0]:
            raise AssertionError("Session B did not finish while partial session A remained open")
        checks.append("B-replied-while-A-partial-and-open")
    with connect(port) as bad, connect(port) as other:
        bad.sendall(b"\xff\n")
        expect_close(bad)
        other.sendall(b"[]\n")
        expect_error(other, "INVALID_REQUEST", None)
        expect_close(other)
        checks.append("invalid-UTF8-A-did-not-stop-B")
    with connect(port) as peer:
        peer.sendall(request(1) + request(1))
        expect_error(peer, "INVALID_REQUEST", 1)
        expect_close(peer)
        checks.append("repeated-ID-closed-only-that-session")
    with connect(port) as peer:
        peer.sendall(b"".join(request(i) for i in range(1, 10)))
        expect_error(peer, "LIMIT_EXCEEDED", 9)
        peer.sendall(request(9))
        expect_error(peer, "INVALID_REQUEST", 9)
        expect_close(peer)
        checks.append("input-queue-bounded-and-overflow-ID-consumed")
    with connect(port) as peer:
        peer.sendall(b'{"token":"' + token.encode() + b'",}\n')
        expect_error(peer, "PARSE_ERROR", None)
        expect_close(peer)
        checks.append("parser-diagnostic-does-not-log-auth-input")
    with connect(port) as peer:
        peer.sendall(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "system.hello", "params": {
            "protocol": {"major": 1, "minor": 0}, "token": token,
            "world": None, "coordinates": "absolute"}}, separators=(",", ":")).encode() + b"\n")
        started = time.monotonic()
        expect_close(peer, timeout=6.5)
        if time.monotonic() - started < 3.5:
            raise AssertionError("Unready connection closed before its configured deadline")
        checks.append("unready-deadline-no-successful-handshake")
    return checks


def main() -> None:
    result_file = ROOT / ".work/t04-paper-results.json"
    result_file.parent.mkdir(parents=True, exist_ok=True)
    result_file.write_text('{"paper":"26.2-133","cases":[],"allPassed":false}\n', encoding="utf-8")
    toolchain = smoke_t02.prepare()
    eula = (SERVER / "eula.txt").read_text(encoding="utf-8").splitlines()
    if "eula=true" not in [line.strip() for line in eula]:
        raise RuntimeError("Operator EULA consent is required for the local test server")
    port, token = free_port(), secrets.token_urlsafe(32)
    config = configuration(port, token)
    cases: list[dict] = []
    success = False

    def save() -> None:
        result_file.write_text(json.dumps({"paper": "26.2-133", "tcpPort": port,
                                          "cases": cases, "allPassed": success}, indent=2) + "\n", encoding="utf-8")

    save()
    try:
        with PaperRun(toolchain, "transport", config, token) as paper:
            paper.wait(f"TCP listener ready on port {port}.")
            checks = transport_checks(port, token)
            with connect(port) as first, connect(port) as second:
                first.sendall(request(1))
                second.sendall(b'{"jsonrpc":')
                paper.request_stop()
                expect_close(first)
                expect_close(second)
                checks.append("stop-closes-two-active-connections")
            result = paper.finish()
            result["checks"] = checks
            cases.append(result)
        check_refused(port)
        with PaperRun(toolchain, "restart", config, token) as paper:
            paper.wait(f"TCP listener ready on port {port}.")
            with connect(port) as peer:
                peer.sendall(b"[]\n")
                expect_error(peer, "INVALID_REQUEST", None)
                expect_close(peer)
            cases.append(paper.finish())
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
                if "TCP listener ready" in "".join(paper.lines):
                    raise AssertionError("Occupied port was reported as a successful bind")
                occupied_result = paper.finish(expected_error=message)
                occupied_result["occupiedPort"] = occupied_port
                cases.append(occupied_result)
        for name, invalid, message in (
            ("blank-token", configuration(port, ""), "token must be a nonblank string"),
            ("missing-world", configuration(port, token, "__missing_world__"), "Configured defaultWorld is not loaded"),
            ("invalid-yaml", "token: [\n", "Cannot read config.yml"),
        ):
            with PaperRun(toolchain, name, invalid, token) as paper:
                paper.wait(message)
                check_refused(port)
                cases.append(paper.finish(expected_error=message))
        check_refused(port)
        success = True
    finally:
        (SERVER / "plugins/Minebridge/config.yml").write_text(config, encoding="utf-8")
        save()
    print(json.dumps(json.loads(result_file.read_text(encoding="utf-8")), indent=2))


if __name__ == "__main__":
    main()
