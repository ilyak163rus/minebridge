"""Raw blocks.set smoke on pinned Paper; independent, separate console fixture.

Reuses existing operator EULA consent. No public Python facade, production RPC,
trace ordering oracle or T08 gate is introduced by this stage-local harness.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
import queue
import re
import secrets
import shutil
import socket
import threading
import time
from uuid import UUID, uuid4

import smoke_t02
from smoke_t04 import (PaperRun as TransportPaperRun, check_refused, configuration,
                       connect, expect_close, free_port)
from smoke_t05 import read_response, ready, request

ROOT = Path(__file__).resolve().parents[1]
SERVER = smoke_t02.SERVER
PROBE_NAME = "minebridge-block-smoke-probe-0.1.0-dev.jar"
PROBE_FOLDER = SERVER / "plugins/MinebridgeBlockSmokeProbe"
X, Z = 16_384, 16_384


class PaperRun(TransportPaperRun):
    def __init__(self, *args: object) -> None:
        super().__init__(*args, jvm_options=("-Dminebridge.diagnostics=true",))
        self.log = ROOT / ".work" / f"t06-paper-{self.name}.log"

    def __enter__(self) -> PaperRun:
        (PROBE_FOLDER / "worlds.tsv").unlink(missing_ok=True)
        super().__enter__()
        return self


def read_worlds() -> list[dict]:
    worlds = []
    for row in (PROBE_FOLDER / "worlds.tsv").read_text(encoding="utf-8").splitlines():
        name, world_id, minimum, maximum = row.split("\t")
        worlds.append({"name": base64.b64decode(name, validate=True).decode("utf-8"),
                       "uuid": str(UUID(world_id)), "minY": int(minimum), "maxYExclusive": int(maximum)})
    if not worlds:
        raise AssertionError("Independent block fixture reported no loaded world")
    return worlds


def fixture(paper: PaperRun, operation: str, world: dict, *arguments: object) -> list[str]:
    """One console request, bounded file result correlated independently of RPC IDs."""
    marker = uuid4().hex
    result_file = PROBE_FOLDER / "results" / f"{marker}.tsv"
    assert paper.process is not None and paper.process.stdin is not None
    command = ["mbblockprobe", marker, operation, world["uuid"], *(str(value) for value in arguments)]
    paper.process.stdin.write(" ".join(command) + "\n")
    paper.process.stdin.flush()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            row = result_file.read_text(encoding="utf-8").strip().split("\t")
        except (FileNotFoundError, PermissionError):
            row = []
        if row and row[0] == marker:
            # read_text has closed its handle before deleting this immutable
            # publication; the server never replaces a path being polled.
            result_file.unlink(missing_ok=True)
            if len(row) < 3 or row[1] != "ok":
                raise AssertionError("Independent console fixture rejected operation")
            return row[2:]
        if paper.process.poll() is not None:
            raise AssertionError("Paper exited during console fixture request")
        time.sleep(0.025)
    raise AssertionError("Independent console fixture result deadline elapsed")


def observe(paper: PaperRun, world: dict, position: list[int], expected: str) -> None:
    if fixture(paper, "read", world, *position) != [expected, "true"]:
        raise AssertionError("Actual world block differs from independently expected block after ACK")


def params(world: dict, position: list[int], key: str = "minecraft:stone") -> dict:
    return {"world": world["name"], "position": position, "block": {"key": key, "states": {}}}


class BlockPeer:
    def __init__(self, port: int, token: str, world: dict) -> None:
        self.peer = connect(port)
        try:
            self.context = ready(self.peer, token, world)
        except BaseException:
            self.peer.close()
            raise
        self.next_id = 2

    def call(self, payload: dict, error: str | None = None) -> dict:
        request_id = self.next_id
        self.next_id += 1
        self.peer.sendall(request(request_id, "blocks.set", payload))
        response = read_response(self.peer)
        check_response(response, request_id, error)
        return response

    def __enter__(self) -> BlockPeer:
        return self

    def __exit__(self, *_: object) -> None:
        self.peer.close()


def check_response(response: dict, request_id: int, error: str | None = None) -> None:
    if response.get("jsonrpc") != "2.0" or response.get("id") != request_id:
        raise AssertionError("Unexpected blocks.set response correlation")
    if error is None:
        if "error" in response or response.get("result", {}).get("applied") is not True:
            raise AssertionError("blocks.set did not confirm applied=true")
    elif ("result" in response or response.get("error", {}).get("data", {}).get("code") != error
          or response["error"]["data"].get("outcome") != "not-applied"):
        raise AssertionError("Unexpected blocks.set error/outcome")


def block_checks(paper: PaperRun, port: int, token: str, worlds: list[dict], world: dict) -> list[str]:
    checks: list[str] = []
    y = world["maxYExclusive"] - 8
    position = [X, y, Z]
    fixture(paper, "prepare", world, y)
    observe(paper, world, position, "minecraft:air")
    with BlockPeer(port, token, world) as peer:
        for key in ("minecraft:stone", "minecraft:cobblestone", "minecraft:air", "minecraft:oak_planks"):
            peer.call(params(world, position, key))
            observe(paper, world, position, key)
            checks.append("ACK-then-independent-world-read-" + key)
        peer.call(params(world, position, "minecraft:oak_planks"))
        observe(paper, world, position, "minecraft:oak_planks")
        checks.append("same-block-no-op-success")
        # Pinning/generation can keep a halo of adjacent chunks loaded on real
        # Paper. Use a distant negative target with independently verified state.
        # The exact floorDiv-versus-truncation distinction is covered by units;
        # this real-server case proves loaded-only rejection without loading it.
        unloaded_chunk = [-4097, 4096]
        if fixture(paper, "chunk", world, *unloaded_chunk) != ["false"]:
            raise AssertionError("Distant negative target must start unloaded")
        peer.call(params(world, [-4 * X - 1, y, 4 * Z]), "CHUNK_NOT_LOADED")
        if fixture(paper, "chunk", world, *unloaded_chunk) != ["false"]:
            raise AssertionError("Rejected loaded-only operation loaded its target chunk")
        checks.append("negative-unloaded-chunk-remained-unloaded")
        negative = [-X, y, Z]
        peer.call(params(world, negative, "minecraft:cobblestone"))
        observe(paper, world, negative, "minecraft:cobblestone")
        checks.append("negative-loaded-chunk-block-write")

        forbidden = next((entry for entry in worlds if entry["uuid"] != world["uuid"]), None)
        if forbidden is None:
            raise AssertionError("A second real loaded world is required for wrong-world test")
        wrong_existing = params(world, position)
        wrong_existing["world"] = forbidden["name"]
        wrong_missing = params(world, position)
        wrong_missing["world"] = "__t06_missing_world__"
        nonempty_states = params(world, position)
        nonempty_states["block"]["states"] = {"axis": "y"}
        extra_field = params(world, position)
        extra_field["unexpected"] = True
        bad_block_field = params(world, position)
        bad_block_field["block"]["unexpected"] = True
        invalids = [
            ("wrong-existing-world", wrong_existing, "PERMISSION_DENIED"),
            ("wrong-missing-world", wrong_missing, "WORLD_NOT_FOUND"),
            ("missing-material", params(world, position, "minecraft:__t06_absent_block__"), "INVALID_BLOCK"),
            ("item-instead-of-block", params(world, position, "minecraft:iron_sword"), "INVALID_BLOCK"),
            ("foreign-namespace-not-stripped", params(world, position, "t06:stone"), "INVALID_BLOCK"),
            ("malformed-key", params(world, position, "STONE"), "INVALID_BLOCK"),
            ("unsupported-states", nonempty_states, "UNSUPPORTED_FEATURE"),
            ("below-min-y", params(world, [X, world["minY"] - 1, Z]), "COORDINATE_OUT_OF_BOUNDS"),
            ("at-exclusive-max-y", params(world, [X, world["maxYExclusive"], Z]), "COORDINATE_OUT_OF_BOUNDS"),
            ("fractional-raw-coordinate", params(world, [X + 0.5, y, Z]), "INVALID_PARAMS"),
            ("boolean-raw-coordinate", params(world, [True, y, Z]), "INVALID_PARAMS"),
            ("raw-int32-overflow", params(world, [2 ** 31, y, Z]), "INVALID_PARAMS"),
            ("raw-position-length", params(world, [X, y]), "INVALID_PARAMS"),
            ("unknown-param", extra_field, "INVALID_PARAMS"),
            ("unknown-block-field", bad_block_field, "INVALID_PARAMS"),
        ]
        for label, payload, code in invalids:
            peer.call(payload, code)
            observe(paper, world, position, "minecraft:oak_planks")
            checks.append(label + "-not-applied-READY-retained")
        # Border uses the center of the target block, not a chunk's bounds.
        fixture(paper, "border", world, 16, X + 0.5, Z + 0.5)
        try:
            peer.call(params(world, [X + 9, y, Z]), "COORDINATE_OUT_OF_BOUNDS")
            peer.call(params(world, [X + 7, y, Z], "minecraft:stone"))
            observe(paper, world, [X + 7, y, Z], "minecraft:stone")
            # Sub-block borders catch an implementation which floors Location
            # coordinates before checking the contract's exact block center.
            fixture(paper, "border", world, 1, X, Z + 0.5)
            peer.call(params(world, position), "COORDINATE_OUT_OF_BOUNDS")
            observe(paper, world, position, "minecraft:oak_planks")
            fixture(paper, "border", world, 1, X + 0.5, Z)
            peer.call(params(world, position), "COORDINATE_OUT_OF_BOUNDS")
            observe(paper, world, position, "minecraft:oak_planks")
            fixture(paper, "border", world, 1, X + 0.5, Z + 0.5)
            peer.call(params(world, position, "minecraft:oak_planks"))
            observe(paper, world, position, "minecraft:oak_planks")
        finally:
            fixture(paper, "restore-border", world)
        checks.append("actual-world-border-block-center-policy-and-READY-retained")
        checks.append("size-one-fractional-border-exact-upper-X-and-Z-edges-rejected-center-accepted")

    # Each connection has FIFO order; no cross-connection winner is assumed.
    with BlockPeer(port, token, world) as a, BlockPeer(port, token, world) as b:
        if a.context["sessionId"] == b.context["sessionId"]:
            raise AssertionError("Two concurrent connections shared a session ID")
        barrier = threading.Barrier(2)
        results: queue.Queue[tuple[str, str | None]] = queue.Queue()

        def batch(label: str, connection: BlockPeer, at: list[int], keys: list[str]) -> None:
            try:
                barrier.wait(timeout=5)
                connection.peer.sendall(b"".join(request(i + 2, "blocks.set", params(world, at, key))
                                                  for i, key in enumerate(keys)))
                for request_id in (2, 3, 4):
                    check_response(read_response(connection.peer), request_id)
                results.put((label, None))
            except BaseException as failure:
                results.put((label, type(failure).__name__))

        threads = [threading.Thread(target=batch, args=("A", a, [X + 2, y, Z],
                    ["minecraft:stone", "minecraft:cobblestone", "minecraft:stone"])),
                   threading.Thread(target=batch, args=("B", b, [X + 3, y, Z],
                    ["minecraft:cobblestone", "minecraft:stone", "minecraft:cobblestone"]))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        if any(thread.is_alive() for thread in threads):
            a.peer.close()
            b.peer.close()
            for thread in threads:
                thread.join(timeout=6)
            raise AssertionError("Concurrent bounded RPC smoke did not terminate")
        if sorted(results.get_nowait() for _ in range(2)) != [("A", None), ("B", None)]:
            raise AssertionError("Concurrent sessions did not receive ordered acknowledgements")
        observe(paper, world, [X + 2, y, Z], "minecraft:stone")
        observe(paper, world, [X + 3, y, Z], "minecraft:cobblestone")
        checks.append("two-concurrent-raw-sessions-distinct-ID1-contexts-six-FIFO-ACKs-and-final-blocks")
    return checks


def trace_checks(paper: PaperRun) -> dict:
    """Inspect values recorded at production event points, not stdout arrival time."""
    pattern = re.compile(r"TRACE seq=(\d+) phase=(QUEUED|APPLY_BEGIN|APPLY_DONE|ERROR|CANCELLED|ACK_ENQUEUED) "
                         r"sessionId=([a-fA-F0-9-]{36}) requestId=(\d+) applySequence=(\d+) "
                         r"threadId=(\d+) primaryThread=(true|false)")
    events = []
    for line in paper.lines:
        if "TRACE seq=" not in line:
            continue
        match = pattern.search(line)
        if match is None:
            raise AssertionError("Malformed local production trace event")
        sequence, phase, session_id, request_id, apply_sequence, thread_id, primary = match.groups()
        events.append({"sequence": int(sequence), "phase": phase, "sessionId": str(UUID(session_id)),
                       "requestId": int(request_id), "applySequence": int(apply_sequence),
                       "threadId": int(thread_id), "primaryThread": primary == "true"})
    setter_phases = {"APPLY_BEGIN", "APPLY_DONE", "ACK_ENQUEUED"}
    if not events or any(not event["primaryThread"] for event in events if event["phase"] in setter_phases):
        raise AssertionError("Production block trace did not confirm the actual main-thread event points")
    sequences = [event["sequence"] for event in events]
    if len(sequences) != len(set(sequences)):
        raise AssertionError("Production trace repeated an eventSequence")
    groups: dict[tuple[str, int], dict] = {}
    for event in events:
        key = (event["sessionId"], event["requestId"])
        group = groups.setdefault(key, {})
        if event["phase"] in group:
            raise AssertionError("Production trace repeated a mutation phase")
        group[event["phase"]] = event
    successful = 0
    for group in groups.values():
        if "ACK_ENQUEUED" not in group:
            if not {"ERROR", "CANCELLED"}.intersection(group):
                raise AssertionError("Smoke request lacks a terminal trace event")
            continue
        if not setter_phases.issubset(group):
            raise AssertionError("Successful smoke mutation lacks the complete diagnostic trace")
        successful += 1
        begin, done, ack = (group[phase] for phase in ("APPLY_BEGIN", "APPLY_DONE", "ACK_ENQUEUED"))
        if not begin["sequence"] < done["sequence"] < ack["sequence"]:
            raise AssertionError("ACK was recorded before the setter completed")
        if len({group[phase]["applySequence"] for phase in setter_phases}) != 1:
            raise AssertionError("Production trace mutation correlation changed between phases")
    return {"successfulMutations": successful, "events": successful * 3, "lifecycleEvents": len(events),
            "primaryThreadAtEventPoints": True, "applyDoneBeforeAckEnqueuedByEventSequence": True,
            "scope": "T06 smoke; complete observer/gate scenarios remain T08-T10"}


def main() -> None:
    result_file = ROOT / ".work/t06-paper-results.json"
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
        with PaperRun(toolchain, "blocks", config, token) as paper:
            paper.wait(f"TCP listener ready on port {port}.")
            worlds = read_worlds()
            world = next(entry for entry in worlds if entry["name"] == "t02-world")
            checks = block_checks(paper, port, token, worlds, world)
            with BlockPeer(port, token, world) as a, BlockPeer(port, token, world) as b:
                paper.request_stop()
                expect_close(a.peer, timeout=5)
                expect_close(b.peer, timeout=5)
            checks.append("stop-closes-two-READY-sessions")
            outcome = paper.finish()
            cases.append({**outcome, "checks": checks, "worlds": worlds, "trace": trace_checks(paper)})
        check_refused(port)
        with PaperRun(toolchain, "restart", config, token) as paper:
            paper.wait(f"TCP listener ready on port {port}.")
            world = next(entry for entry in read_worlds() if entry["name"] == "t02-world")
            y = world["maxYExclusive"] - 8
            fixture(paper, "prepare", world, y)
            # This is the independently prepared initial state of this case;
            # restoration itself is fixture cleanup, not an assertion here.
            observe(paper, world, [X, y, Z], "minecraft:air")
            with BlockPeer(port, token, world) as peer:
                peer.call(params(world, [X, y, Z], "minecraft:stone"))
                observe(paper, world, [X, y, Z], "minecraft:stone")
            outcome = paper.finish()
            cases.append({**outcome, "checks": ["restart-same-port-and-independent-block-write"],
                          "trace": trace_checks(paper)})
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
        success = True
    finally:
        deployed_fixture.unlink(missing_ok=True)
        (SERVER / "plugins/Minebridge/config.yml").write_text(config, encoding="utf-8")
        save()
    print(json.dumps(json.loads(result_file.read_text(encoding="utf-8")), indent=2))


if __name__ == "__main__":
    main()
