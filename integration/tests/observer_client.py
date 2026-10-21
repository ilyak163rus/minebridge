"""Local console/file observer transport, independent of the production socket."""

from __future__ import annotations

import json
from pathlib import Path
import re
import time
import uuid


class ObserverError(AssertionError):
    def __init__(self, code: str, envelope: dict) -> None:
        super().__init__("Observer rejected operation: " + code)
        self.code, self.envelope = code, envelope


class ObserverClient:
    """One writer owned by the orchestrator; each command has a unique result file.

    Results are never deleted/reused. Atomic publication in the Java observer is
    the completion barrier; polling only awaits that barrier with a deadline.
    """

    def __init__(self, paper: object, evidence: Path) -> None:
        self.paper, self.evidence = paper, evidence
        self.results = paper.server / "plugins/MinebridgeObserver/results"
        self.envelopes: list[dict] = []
        self.last_sequence = 0

    @staticmethod
    def case_id() -> str:
        return uuid.uuid4().hex

    def call(self, case_id: str, action: str, *arguments: object,
             timeout: float = 25.0, expected_error: str | None = None) -> dict:
        if not re.fullmatch(r"[0-9a-f]{32}", case_id):
            raise ValueError("A new lowercase hexadecimal case ID is required")
        request_id = uuid.uuid4().hex
        words = ["mbobserve", case_id, request_id, action, *map(str, arguments)]
        if any(not word or any(ch.isspace() for ch in word) for word in words):
            raise ValueError("Observer console arguments must be individual words")
        target = self.results / (request_id + ".json")
        if target.exists():
            raise AssertionError("Observer correlation file already exists")
        self.paper.command(" ".join(words))
        deadline = time.monotonic() + timeout
        while not target.is_file():
            if self.paper.process.poll() is not None:
                raise AssertionError("Paper stopped before the observer completed")
            if time.monotonic() >= deadline:
                raise AssertionError("Observer completion deadline elapsed for " + action)
            time.sleep(0.02)
        payload = target.read_bytes()
        if len(payload) > 1024 * 1024:
            raise AssertionError("Observer result exceeds the test bound")
        envelope = json.loads(payload.decode("utf-8"))
        if (envelope.get("schemaVersion") != 1 or envelope.get("caseId") != case_id
                or envelope.get("requestId") != request_id or envelope.get("action") != action
                or envelope.get("primaryThread") is not True
                or type(envelope.get("sequence")) is not int
                or envelope["sequence"] <= self.last_sequence
                or type(envelope.get("tick")) is not int):
            raise AssertionError("Observer result correlation/thread/sequence is invalid")
        self.last_sequence = envelope["sequence"]
        self.envelopes.append(envelope)
        self.evidence.write_text(json.dumps(self.envelopes, indent=2) + "\n", encoding="utf-8")
        if envelope.get("status") == "error":
            error = envelope.get("error")
            code = error.get("code") if isinstance(error, dict) else error
            if expected_error is not None and code == expected_error:
                return envelope
            raise ObserverError(str(code), envelope)
        if expected_error is not None or envelope.get("status") != "ok":
            raise AssertionError("Unexpected observer completion status")
        if not isinstance(envelope.get("result"), dict):
            raise AssertionError("Observer did not return an object result")
        return envelope

    def result(self, case_id: str, action: str, *arguments: object, **options: object) -> dict:
        return self.call(case_id, action, *arguments, **options)["result"]

    def await_value(self, case_id: str, action: str, arguments: tuple,
                    predicate: object, *, timeout: float = 8.0) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            result = self.result(case_id, action, *arguments)
            if predicate(result):
                return result
            if time.monotonic() >= deadline:
                raise AssertionError("Observer state deadline elapsed for " + action)
            # There is no timing assertion here: the observed state is the barrier.
            time.sleep(0.02)
