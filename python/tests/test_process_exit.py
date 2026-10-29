"""A short teaching script must drain buffered writes before normal process exit."""

import os
from pathlib import Path
import subprocess
import sys
import threading
import unittest

import minebridge
from minebridge._protocol import encode_frame
from test_client import send_hello
from test_transport import peer, read_request, result


class ProcessExitTests(unittest.TestCase):
    def run_script(self, *, failure=False):
        body_done = threading.Event()
        release = threading.Event()
        observed = []

        def handle(connection, stopping):
            send_hello(connection, read_request(connection))
            requests = [read_request(connection), read_request(connection)]
            observed.extend(requests)
            body_done.set()
            if not release.wait(3):
                raise AssertionError("Test did not release replies")
            for request in requests:
                if request is None:
                    return
                frame = (encode_frame({"jsonrpc": "2.0", "id": request["id"], "error": {
                    "code": -32023, "message": "Server operation failed",
                    "data": {"code": "CHUNK_NOT_LOADED", "outcome": "not-applied"},
                }}) if failure and request is requests[0] else result(request["id"]))
                connection.sendall(frame)
            self.assertIsNone(read_request(connection))

        with peer(handle) as server:
            environment = os.environ.copy()
            environment.pop("MINEBRIDGE_TOKEN", None)
            environment["PYTHONPATH"] = str(Path(minebridge.__file__).resolve().parent.parent)
            script = (
                "from minebridge import Minecraft, block\n"
                f"mc = Minecraft.create('127.0.0.1', {server.port}, timeout=2)\n"
                "mc.setBlock(0, 0, 0, block.COBBLESTONE)\n"
                "mc.postToChat('hello')\n"
                "print('body complete', flush=True)\n"
            )
            process = subprocess.Popen([sys.executable, "-c", script], env=environment,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
            try:
                self.assertTrue(body_done.wait(3))
                self.assertEqual(process.stdout.readline().strip(), "body complete")
                with self.assertRaises(subprocess.TimeoutExpired):
                    process.wait(timeout=0.15)
            finally:
                release.set()
                stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, stderr)
            self.assertEqual([row["method"] for row in observed], ["blocks.set", "chat.post"])
            return stderr

    def test_normal_exit_waits_for_block_and_chat_ack_without_explicit_close(self):
        self.assertEqual(self.run_script(), "")

    def test_deferred_server_error_is_reported_at_exit_instead_of_silently_disappearing(self):
        stderr = self.run_script(failure=True)
        self.assertIn("Minebridge", stderr)
        self.assertIn("ChunkNotLoadedError", stderr)
        self.assertIn("blocks.set", stderr)
