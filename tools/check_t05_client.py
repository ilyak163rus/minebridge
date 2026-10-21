"""Persistent installed-wheel client for the T05 Paper harness (not a product API)."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import sys

from minebridge._transport import TcpTransport
from minebridge.errors import MinecraftError


def emit(value: dict) -> None:
    print(json.dumps(value, default=str), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--world")
    arguments = parser.parse_args()
    connection = TcpTransport.connect_and_handshake(
        "127.0.0.1", arguments.port, world=arguments.world,
    )
    try:
        assert connection.context is not None
        emit({"event": "ready", "context": asdict(connection.context)})
        for line in sys.stdin:
            if line.strip() == "close":
                break
            if line.strip() != "probe":
                raise AssertionError("Unknown harness command")
            try:
                connection.exchange("future.t05.probe", {})
            except MinecraftError as failure:
                if failure.code != "METHOD_NOT_FOUND" or failure.outcome != "not-applied":
                    raise AssertionError("Unexpected probe result") from None
                emit({"event": "probe", "code": failure.code})
            else:
                raise AssertionError("Unknown method unexpectedly succeeded")
    finally:
        connection.close()
    emit({"event": "closed"})


if __name__ == "__main__":
    main()
