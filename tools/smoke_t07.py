"""Public installed-wheel facade on pinned Paper, including two Python processes.

Reuses existing EULA consent and the separate T06 console fixture. This is a
stage smoke; the complete observer and integration gate remain T08-T10.
"""

from __future__ import annotations

from contextlib import ExitStack
import json
import os
from pathlib import Path
import queue
import secrets
import shutil
import socket
import subprocess
import threading

import smoke_t02
from smoke_t04 import PaperRun as TransportPaperRun, check_refused, configuration, free_port
from smoke_t06 import PROBE_FOLDER, PROBE_NAME, X, Z, fixture, observe, read_worlds, trace_checks

ROOT = Path(__file__).resolve().parents[1]
SERVER = smoke_t02.SERVER


class PaperRun(TransportPaperRun):
    def __init__(self, *args: object) -> None:
        super().__init__(*args, jvm_options=("-Dminebridge.diagnostics=true",))
        self.log = ROOT / ".work" / f"t07-paper-{self.name}.log"

    def __enter__(self) -> PaperRun:
        (PROBE_FOLDER / "worlds.tsv").unlink(missing_ok=True)
        super().__enter__()
        return self


class FacadeClient:
    """One persistent, isolated Python interpreter and one public connection."""

    def __init__(self, port: int, token: str, mode: str) -> None:
        self.port, self.mode, self.token = port, mode, token
        self.process: subprocess.Popen | None = None
        self.events: queue.Queue[str | None] = queue.Queue()
        self.lines: list[str] = []
        self.errors: list[str] = []
        self.threads: list[threading.Thread] = []
        self.context: dict = {}
        self.closed = False

    def __enter__(self) -> FacadeClient:
        python = ROOT / ".venv-t01-314/Scripts/python.exe"
        if not python.is_file():
            raise RuntimeError("Install the T07 wheel in the existing Python 3.14 test environment")
        environment = os.environ.copy()
        environment.pop("MINEBRIDGE_TOKEN", None)
        environment.pop("MINEBRIDGE_T07_EXPLICIT_TOKEN", None)
        environment.update({"MINEBRIDGE_T07_PORT": str(self.port),
                            "MINEBRIDGE_T07_AUTH_MODE": self.mode})
        environment["MINEBRIDGE_TOKEN" if self.mode == "environment"
                    else "MINEBRIDGE_T07_EXPLICIT_TOKEN"] = self.token
        self.process = subprocess.Popen(
            [str(python), "-I", str(ROOT / "tools/check_t07_client.py")],
            cwd=ROOT, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

        def read_output() -> None:
            assert self.process is not None and self.process.stdout is not None
            for line in self.process.stdout:
                self.lines.append(line)
                self.events.put(line)
            self.events.put(None)

        def read_errors() -> None:
            assert self.process is not None and self.process.stderr is not None
            for line in self.process.stderr:
                # Always drain the pipe; bounded retained diagnostic evidence.
                if len(self.errors) < 32:
                    self.errors.append(line)

        self.threads = [threading.Thread(target=read_output, daemon=True),
                        threading.Thread(target=read_errors, daemon=True)]
        for thread in self.threads:
            thread.start()
        try:
            self.context = self.response()
            if self.context.get("ready") is not True:
                raise AssertionError("Installed facade client did not complete public create")
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def response(self) -> dict:
        try:
            line = self.events.get(timeout=12)
        except queue.Empty:
            raise AssertionError("Installed facade child response deadline elapsed") from None
        if line is None or len(line) > 8192 or self.token in line:
            raise AssertionError("Unsafe or missing installed facade child response")
        value = json.loads(line)
        if not isinstance(value, dict) or "fatal" in value:
            raise AssertionError("Installed facade child failed")
        return value

    def send(self, command: dict) -> None:
        assert self.process is not None and self.process.stdin is not None
        self.process.stdin.write(json.dumps(command, allow_nan=False) + "\n")
        self.process.stdin.flush()

    def call(self, position: list[int | float], kind: str, value: object, *,
             route: str = "root", data: int = 0, error: str | None = None,
             code: str | None = None, closed: bool = False) -> dict:
        self.send({"op": "set", "route": route, "position": position,
                   "block": {"kind": kind, "value": value}, "data": data})
        response = self.response()
        if error is None:
            if response != {"ok": True, "returnedNone": True, "closed": False}:
                raise AssertionError("Public setBlock did not return None after a successful ACK")
        elif (response.get("error") != error or response.get("code") != code
              or response.get("closed") is not closed
              or (code is not None and response.get("outcome") != "not-applied")):
            raise AssertionError("Unexpected public facade error metadata or connection state")
        return response

    def close(self) -> None:
        if self.closed:
            return
        self.send({"op": "close"})
        if self.response() != {"closed": True}:
            raise AssertionError("Public close was not idempotent")
        self.closed = True

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
                self.process.wait(timeout=6)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
            for thread in self.threads:
                thread.join(timeout=3)
            if self.process.stdout is not None:
                self.process.stdout.close()
            if self.process.stderr is not None:
                self.process.stderr.close()
        if any(thread.is_alive() for thread in self.threads):
            raise AssertionError("Installed facade child output capture did not terminate")
        if self.token in "".join(self.lines + self.errors):
            raise AssertionError("Lesson token appeared in installed facade child output")
        if self.process.returncode != 0 or self.errors:
            raise AssertionError("Installed facade child did not exit cleanly")


def facade_checks(paper: PaperRun, port: int, token: str, world: dict,
                  stack: ExitStack) -> tuple[list[str], dict, list[FacadeClient]]:
    checks: list[str] = []
    y = world["maxYExclusive"] - 8
    fixture(paper, "prepare", world, y)
    a = stack.enter_context(FacadeClient(port, token, "explicit"))
    b = stack.enter_context(FacadeClient(port, token, "environment"))
    if a.context["pid"] == b.context["pid"]:
        raise AssertionError("Smoke did not start two independent Python processes")
    if a.context["sessionId"] == b.context["sessionId"]:
        raise AssertionError("Independent Python processes shared a session")
    if a.context["world"] != world or b.context["world"] != world:
        raise AssertionError("Public create selected a world different from the independent fixture")
    checks.append("two-live-isolated-installed-wheel-processes-explicit-and-environment-token")

    position = [X, y, Z]
    for peer, route, kind, value, expected in (
        (a, "root", "id", 4, "minecraft:cobblestone"),
        (b, "blocks", "constant", "COBBLESTONE", "minecraft:cobblestone"),
        (a, "blocks", "constant", "AIR", "minecraft:air"),
        (b, "root", "constant", "STONE", "minecraft:stone"),
        (a, "root", "key", "minecraft:oak_planks", "minecraft:oak_planks"),
        (b, "blocks", "spec", "minecraft:stone", "minecraft:stone"),
    ):
        peer.call(position, kind, value, route=route)
        observe(paper, world, position, expected)
    checks.append("both-setBlock-routes-numeric-constant-modern-key-and-BlockSpec-after-ACK-world-read")
    # -16383.75 floors to -16384, whereas truncation would hit another block.
    # The separate fixture prepared the exact negative target in a loaded chunk.
    a.call([-X + 0.25, y + 0.75, Z + 0.5], "id", 4)
    observe(paper, world, [-X, y, Z], "minecraft:cobblestone")
    checks.append("fractional-negative-coordinate-floors-down-in-actual-world")

    for peer, at, kind, value, data, error, code in (
        (a, [True, y, Z], "id", 4, 0, "TypeError", None),
        (b, position, "id", 999999, 0, "UnsupportedLegacyBlockError", "UNSUPPORTED_LEGACY_BLOCK"),
        (a, position, "key", "minecraft:stone", 1, "ValueError", None),
        (b, position, "key", "minecraft:iron_sword", 0, "InvalidBlockError", "INVALID_BLOCK"),
        (a, [X, world["maxYExclusive"], Z], "id", 4, 0,
         "CoordinateOutOfBoundsError", "COORDINATE_OUT_OF_BOUNDS"),
    ):
        peer.call(at, kind, value, data=data, error=error, code=code)
        observe(paper, world, position, "minecraft:stone")
    checks.append("local-normalization-and-server-domain-errors-not-applied-both-sessions-retained")

    # Queue the commands in two independent processes before awaiting either
    # response. Both connections stay alive throughout this small overlap.
    for peer, at, value in ((a, [X + 2, y, Z], 4), (b, [X + 3, y, Z], 1)):
        peer.send({"op": "set", "route": "blocks", "position": at,
                   "block": {"kind": "id", "value": value}, "data": 0})
    for peer in (a, b):
        if peer.response() != {"ok": True, "returnedNone": True, "closed": False}:
            raise AssertionError("Overlapping public calls did not receive successful acknowledgements")
    observe(paper, world, [X + 2, y, Z], "minecraft:cobblestone")
    observe(paper, world, [X + 3, y, Z], "minecraft:stone")
    checks.append("two-process-overlapping-public-calls-independent-final-blocks")
    metadata = {"processes": 2, "sessions": [a.context["sessionId"], b.context["sessionId"]],
                "clients": [a.context, b.context], "successfulPublicSetCalls": 9}
    return checks, metadata, [a, b]


def main() -> None:
    result_file = ROOT / ".work/t07-paper-results.json"
    result_file.parent.mkdir(parents=True, exist_ok=True)
    port, token = free_port(), secrets.token_urlsafe(32)
    cases: list[dict] = []
    success = False

    def save() -> None:
        result_file.write_text(json.dumps({"paper": "26.2-133", "tcpPort": port,
                                          "cases": cases, "allPassed": success}, indent=2) + "\n", encoding="utf-8")

    save()
    toolchain = smoke_t02.prepare()
    if "eula=true" not in [line.strip() for line in (SERVER / "eula.txt").read_text(encoding="utf-8").splitlines()]:
        raise RuntimeError("Existing operator EULA consent is required")
    source_fixture = ROOT / "plugin/build/test-fixtures" / PROBE_NAME
    if not source_fixture.is_file():
        raise RuntimeError("Build blockSmokeProbeJar before this test")
    deployed_fixture = (SERVER / "plugins" / PROBE_NAME).resolve()
    if not deployed_fixture.is_relative_to((ROOT / ".work").resolve()):
        raise RuntimeError("Fixture deployment must remain inside the workspace test server")
    shutil.copy2(source_fixture, deployed_fixture)
    config = configuration(port, token)
    try:
        with PaperRun(toolchain, "facade", config, token) as paper:
            paper.wait(f"TCP listener ready on port {port}.")
            worlds = read_worlds()
            world = next(entry for entry in worlds if entry["name"] == "t02-world")
            with ExitStack() as stack:
                checks, metadata, clients = facade_checks(paper, port, token, world, stack)
                paper.request_stop()
                outcome = paper.finish()
                check_refused(port)
                for peer in clients:
                    peer.call([X, world["maxYExclusive"] - 8, Z], "id", 4,
                              error="ConnectionError", code="CONNECTION_LOST", closed=True)
                checks.append("Paper-stop-two-live-Python-objects-fail-bounded-without-reconnect")
            trace = trace_checks(paper)
            if trace["successfulMutations"] != metadata["successfulPublicSetCalls"]:
                raise AssertionError("Public successful calls differ from actual Paper apply trace count")
            trace["scope"] = "T07 facade smoke; complete observer/gate scenarios remain T08-T10"
            cases.append({**outcome, "checks": checks, **metadata, "worlds": worlds, "trace": trace})
        with PaperRun(toolchain, "restart", config, token) as paper:
            paper.wait(f"TCP listener ready on port {port}.")
            world = next(entry for entry in read_worlds() if entry["name"] == "t02-world")
            y = world["maxYExclusive"] - 8
            fixture(paper, "prepare", world, y)
            observe(paper, world, [X, y, Z], "minecraft:air")
            with FacadeClient(port, token, "environment") as peer:
                peer.call([X, y, Z], "constant", "COBBLESTONE")
                observe(paper, world, [X, y, Z], "minecraft:cobblestone")
            outcome = paper.finish()
            trace = trace_checks(paper)
            trace["scope"] = "T07 facade smoke; complete observer/gate scenarios remain T08-T10"
            if trace["successfulMutations"] != 1:
                raise AssertionError("Restart did not have exactly one successful public call")
            cases.append({**outcome, "checks": ["restart-same-port-public-create-and-independent-block-write-idempotent-close"],
                          "successfulPublicSetCalls": 1, "trace": trace})
        check_refused(port)
        with socket.socket() as occupied:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                occupied.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            message = "Cannot start TCP listener; check listenAddress and whether port is already in use."
            with PaperRun(toolchain, "occupied-port", configuration(occupied.getsockname()[1], token), token) as paper:
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
        check_refused(port)
        success = True
    finally:
        deployed_fixture.unlink(missing_ok=True)
        (SERVER / "plugins/Minebridge/config.yml").write_text(config, encoding="utf-8")
        save()
    print(json.dumps(json.loads(result_file.read_text(encoding="utf-8")), indent=2))


if __name__ == "__main__":
    main()
