"""Bounded standard-library peer for adversarial real-Paper protocol tests.

This helper intentionally bypasses the public client validator.  Evidence never
contains hello credentials or arbitrary malformed payloads.
"""

from __future__ import annotations

import hashlib
import json
import socket
import time


class RawPeer:
    MAX_FRAME_BYTES = 65536

    def __init__(self, host: str = "127.0.0.1", port: int = 4711,
                 *, token: str | None = None, timeout: float = 8.0) -> None:
        self.host, self.port, self.token, self.timeout = host, port, token, timeout
        self.socket: socket.socket | None = None
        self.buffer = bytearray()
        self.context: dict = {}
        self.events: list[dict] = []
        self.eof = False

    @property
    def session_id(self) -> str:
        return self.context["sessionId"]

    def __enter__(self) -> RawPeer:
        self.socket = socket.create_connection((self.host, self.port), timeout=self.timeout)
        return self

    def _safe(self, value):
        if isinstance(value, dict):
            return {key: ("<redacted>" if key == "token" else self._safe(item))
                    for key, item in value.items()}
        if isinstance(value, list):
            return [self._safe(item) for item in value]
        if isinstance(value, str) and self.token:
            return value.replace(self.token, "<redacted>")
        return value

    @staticmethod
    def hello_frame(token: str, /, **overrides) -> dict:
        params = {"protocol": {"major": 1, "minor": 0}, "token": token,
                  "world": None, "coordinates": "absolute"}
        params.update(overrides)
        return {"jsonrpc": "2.0", "id": 1, "method": "system.hello", "params": params}

    def hello(self, token: str | None = None, **overrides) -> dict:
        selected = token if token is not None else self.token
        if selected is None:
            raise ValueError("Explicit test credentials are required")
        self.token = selected
        self.send(self.hello_frame(selected, **overrides))
        response = self.receive()
        if response.get("id") != 1 or not isinstance(response.get("result"), dict):
            raise AssertionError("Raw peer hello did not complete successfully")
        self.context = response["result"]
        return self.context

    def send(self, frame: dict) -> None:
        payload = json.dumps(frame, ensure_ascii=True, allow_nan=False,
                             separators=(",", ":")).encode("utf-8") + b"\n"
        self.events.append({"direction": "request", "frame": self._safe(frame)})
        self._send(payload)

    def send_bytes(self, payload: bytes) -> None:
        self.events.append({"direction": "raw-request", "bytes": len(payload),
                            "sha256": hashlib.sha256(payload).hexdigest()})
        self._send(payload)

    def _send(self, payload: bytes) -> None:
        if self.socket is None:
            raise AssertionError("Raw peer is not connected")
        self.socket.settimeout(self.timeout)
        self.socket.sendall(payload)

    def receive(self, timeout: float | None = None) -> dict:
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        while True:
            split = self.buffer.find(b"\n")
            if split >= 0:
                if split > self.MAX_FRAME_BYTES:
                    raise AssertionError("Raw response exceeds the frame bound")
                payload = bytes(self.buffer[:split])
                del self.buffer[:split + 1]
                frame = json.loads(payload.decode("utf-8"))
                if not isinstance(frame, dict):
                    raise AssertionError("Raw response is not an object")
                self.events.append({"direction": "response", "frame": self._safe(frame)})
                return frame
            if len(self.buffer) > self.MAX_FRAME_BYTES:
                raise AssertionError("Unterminated raw response exceeds the frame bound")
            if self.eof:
                if self.buffer:
                    raise AssertionError("Server closed with an incomplete response frame")
                raise EOFError("Raw peer reached EOF")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Raw peer receive deadline elapsed")
            self.socket.settimeout(remaining)
            try:
                payload = self.socket.recv(4096)
            except socket.timeout:
                raise TimeoutError("Raw peer receive deadline elapsed") from None
            except ConnectionResetError:
                payload = b""
            if not payload:
                self.eof = True
                self.events.append({"direction": "eof"})
            else:
                self.buffer.extend(payload)

    def expect_eof(self, timeout: float | None = None) -> list[dict]:
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        frames: list[dict] = []
        while True:
            try:
                frames.append(self.receive(timeout=max(.001, deadline - time.monotonic())))
            except EOFError:
                return frames

    def close(self) -> None:
        if self.socket is not None:
            self.socket.close()
            self.socket = None

    def __exit__(self, *_: object) -> None:
        self.close()
