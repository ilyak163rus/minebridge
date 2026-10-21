"""Installed Python transport against the real Java transport, without Paper/game dispatch."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import queue
import select
import socket
import subprocess
import threading
import time

from minebridge._transport import TcpTransport
from minebridge.errors import UnsupportedFeatureError

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    toolchain = json.loads((ROOT / ".tools/t02-toolchain.json").read_text(encoding="utf-8"))
    result_file = ROOT / ".work/t04-loopback-results.json"
    result_file.write_text('{"allPassed":false}\n', encoding="utf-8")
    process = subprocess.Popen(
        [str(Path(toolchain["javaHome"]) / "bin/java.exe"), "-cp",
         "plugin/build/classes/java/test;plugin/build/libs/minebridge-paper-0.1.0-dev.jar",
         "dev.minebridge.transport.TransportHarness"],
        cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    events: queue.Queue[str] = queue.Queue()
    lines: list[str] = []

    def read_output() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            lines.append(line)
            events.put(line)

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    try:
        first = events.get(timeout=5)
        port = json.loads(first)["port"]

        def exchange(transport: TcpTransport) -> None:
            try:
                transport.exchange("future", {"label": "мир🌍"})
            except UnsupportedFeatureError as error:
                if error.code != "METHOD_NOT_FOUND" or error.outcome != "not-applied":
                    raise AssertionError("Unexpected error classification") from None
            else:
                raise AssertionError("Test consumer must never report a game operation as applied")

        with socket.create_connection(("127.0.0.1", port), timeout=2) as partial:
            partial.sendall(b'{"jsonrpc":')
            first_transport = TcpTransport.connect("127.0.0.1", port)
            second_transport = None
            try:
                second_transport = TcpTransport.connect("127.0.0.1", port)
                barrier = threading.Barrier(2)

                def run(transport: TcpTransport) -> None:
                    barrier.wait(timeout=2)
                    for _ in range(12):
                        exchange(transport)

                started = time.monotonic()
                with ThreadPoolExecutor(max_workers=2) as workers:
                    futures = [workers.submit(run, transport) for transport in (first_transport, second_transport)]
                    for future in futures:
                        future.result(timeout=4)
                if time.monotonic() - started >= 4 or select.select([partial], [], [], 0)[0]:
                    raise AssertionError("Healthy sessions did not progress while partial session remained open")
            finally:
                first_transport.close()
                if second_transport is not None:
                    second_transport.close()
        assert process.stdin is not None
        process.stdin.write("stop\n")
        process.stdin.flush()
        process.wait(timeout=5)
        reader.join(timeout=2)
        if reader.is_alive():
            raise AssertionError("Java harness output capture did not terminate")
        if process.returncode != 0:
            raise AssertionError("Java test harness did not exit cleanly")
        summary = json.loads(events.get(timeout=1))
        if summary != {"handled": 24, "respondingSessions": 2, "terminated": True}:
            raise AssertionError("Unexpected cross-language session counts")
        result = {"allPassed": True, "requests": 24, "sessions": 2,
                  "partialThirdSessionDidNotBlock": True, "javaExitCode": 0}
        result_file.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2))
    finally:
        if process.poll() is None:
            try:
                assert process.stdin is not None
                process.stdin.write("stop\n")
                process.stdin.flush()
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                process.kill()
                process.wait(timeout=5)
        reader.join(timeout=2)
        if process.stdin is not None:
            process.stdin.close()
        if process.stdout is not None:
            process.stdout.close()
        (ROOT / ".work/t04-loopback.log").write_text("".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
