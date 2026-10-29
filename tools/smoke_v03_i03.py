"""One disposable pinned Paper I03 acceptance; source Python, no release artifacts."""

import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from smoke_i03 import I03Harness, I03Paper
sys.path.insert(0, str(ROOT / "integration/tests"))
from conftest import require_port_free, sha256


def save(path, value): path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


class Worker:
    def __init__(self, harness, player):
        self.events, self.stderr, self.pending, self.sequence = queue.Queue(), [], None, 0
        self.closed_result = None
        environment = os.environ.copy(); environment.pop("MINEBRIDGE_TOKEN", None)
        command = [str(harness.python), "-I", str(ROOT / "integration/tests/v03_i03_worker.py"),
                   "--port", str(harness.port), "--player", player]
        self.process = subprocess.Popen(command, cwd=ROOT, env=environment, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        def output():
            for line in self.process.stdout:
                try: self.events.put(json.loads(line))
                except ValueError: self.events.put({"type": "fatal", "line": line[:200]})
            self.events.put({"type": "eof"})
        def errors():
            for line in self.process.stderr:
                if len(self.stderr) < 80: self.stderr.append(line)
        self.threads = [threading.Thread(target=output, daemon=True), threading.Thread(target=errors, daemon=True)]
        for thread in self.threads: thread.start()
        try:
            row = self.event(); assert row["type"] == "ready", row
            self.context = row["result"]
        except BaseException:
            self.abort()
            raise

    def event(self, timeout=45):
        try: row = self.events.get(timeout=timeout)
        except queue.Empty: raise AssertionError("I03 source worker deadline: " + "".join(self.stderr)[-2000:]) from None
        assert row["type"] not in ("fatal", "eof"), (row, self.stderr)
        return row

    def call(self, op, *, error=None, **params):
        assert self.pending is None
        self.sequence += 1; self.pending = self.sequence
        self.process.stdin.write(json.dumps({"id": self.sequence, "op": op, **params}) + "\n"); self.process.stdin.flush()
        row = self.event(timeout=90); assert row["id"] == self.pending, row
        self.pending = None
        if error:
            assert row.get("error", {}).get("type") == error, row
            return row["error"]
        assert "error" not in row, row
        return row["result"]

    def close(self):
        if self.process.poll() is None:
            self.closed_result = self.call("close")
            assert self.closed_result["remainingThreads"] == [], self.closed_result
            self.process.stdin.close(); self.process.wait(timeout=15)
        assert self.process.returncode == 0 and not self.stderr, self.stderr
        for thread in self.threads: thread.join(timeout=5)
        self.process.stdout.close(); self.process.stderr.close()
        return self.closed_result

    def abort(self):
        if self.process.poll() is None: self.process.kill(); self.process.wait(timeout=10)
        for thread in self.threads: thread.join(timeout=5)
        for pipe in (self.process.stdin, self.process.stdout, self.process.stderr):
            if pipe is not None and not pipe.closed: pipe.close()


def run():
    production = ROOT / "plugin/build/libs/minebridge-paper-0.3.0.dev3.jar"
    harness = I03Harness(production)
    harness.stage, harness.world_name = "V03-I03", "v03-i03-lesson"
    harness.workspace = ROOT / ".work" / ("v03-i03-" + harness.run_id)
    harness.server = harness.workspace / "server"
    harness.artifacts = ROOT / "integration/artifacts" / ("v03-i03-" + harness.run_id)
    harness.python = ROOT / ".venv-v021-314/Scripts/python.exe"
    harness.prepare()
    harness.manifest.update({"stage": "V03-I03", "contract": "v0.3-I03/protocol-2.0",
        "scope": "Local source I03 genuine-game-events acceptance; no wheel, LAN or classroom claim"})
    scripts = (Path(__file__), ROOT / "integration/tests/v03_i03_worker.py",
        ROOT / "integration/tests/v03_i03_acceptance.py", ROOT / "integration/tests/game_client.py",
        ROOT / "docs/contracts/V0_3_I03_CONTRACT.ru.md")
    harness.manifest["scripts"] = {str(path.relative_to(ROOT)): sha256(path) for path in scripts}
    harness.save_manifest()
    summary = {"allPassed": False, "manifest": str(harness.artifacts / "manifest.json")}
    games, workers = [], []
    print(json.dumps({"phase": "server-start", "workspace": str(harness.workspace), "runId": harness.run_id}), flush=True)
    try:
        with I03Paper(harness, control=True, mode="v03-i03-game-events") as paper:
            paper.wait_ready()
            from v03_i03_acceptance import acceptance
            def check(name, result):
                harness.manifest["checks"].append({"name": name, "passed": True, "result": result})
                harness.save_manifest(); print(json.dumps({"passed": name}), flush=True)
            acceptance(harness, paper, Worker, games, workers, check)
            harness.manifest["modes"].append(paper.finish()); require_port_free(harness.game_port)
        for rel, digest in harness.manifest["pythonSourceSha256"].items(): assert sha256(ROOT / "python/src" / rel) == digest, rel
        for rel, digest in harness.manifest["scripts"].items(): assert sha256(ROOT / rel) == digest, rel
        for row in harness.manifest["artifacts"].values(): assert sha256(Path(row["path"])) == row["sha256"]
        summary["allPassed"] = harness.manifest["allPassed"] = True
    finally:
        for game in games: game.close()
        for worker in workers: worker.abort()
        harness.manifest["finalGameClients"] = [game.evidence() for game in games]
        harness.save_manifest(); save(ROOT / ".work/v03-i03-paper-results.json", summary)
    return summary


if __name__ == "__main__": print(json.dumps(run(), indent=2))
