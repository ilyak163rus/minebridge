"""A live long-running head keeps its FIFO followers alive without a fake ACK."""

import time
import unittest

from minebridge import errors
from minebridge._protocol import encode_frame
from minebridge._transport import TcpTransport
from test_transport import peer, read_request, result


PARAMS = {"world": "world", "position": [0, 80, 0],
          "block": {"key": "minecraft:stone", "states": {}}}


def progress(request_id):
    return encode_frame({"jsonrpc": "2.0", "method": "system.progress",
                         "params": {"requestId": request_id}})


class ProgressTests(unittest.TestCase):
    def test_live_head_keeps_queued_followers_alive_until_final_ack(self):
        def handle(connection, stopping):
            first, second = read_request(connection), read_request(connection)
            for _ in range(5):
                connection.sendall(progress(first["id"]))
                time.sleep(.06)
            connection.sendall(result(first["id"]) + result(second["id"]))
            self.assertIsNone(read_request(connection))

        with peer(handle) as server:
            transport = TcpTransport.connect("127.0.0.1", server.port, timeout=.15)
            try:
                started = time.monotonic()
                transport.submit("blocks.set", PARAMS)
                transport.submit("blocks.set", PARAMS)
                transport.flush()
                self.assertGreater(time.monotonic() - started, .24)
            finally:
                transport.close()

    def test_progress_and_responses_can_share_one_read(self):
        def handle(connection, stopping):
            first, second = read_request(connection), read_request(connection)
            connection.sendall(progress(first["id"]) + result(first["id"])
                               + progress(second["id"]) + result(second["id"]))
            self.assertIsNone(read_request(connection))

        with peer(handle) as server:
            transport = TcpTransport.connect("127.0.0.1", server.port)
            try:
                transport.submit("blocks.set", PARAMS)
                transport.submit("blocks.set", PARAMS)
                transport.flush()
            finally:
                transport.close()

    def test_unknown_progress_id_closes_without_retry(self):
        seen = []

        def handle(connection, stopping):
            request = read_request(connection)
            seen.append(request)
            connection.sendall(progress(request["id"] + 1))
            self.assertIsNone(read_request(connection))

        with peer(handle) as server:
            transport = TcpTransport.connect("127.0.0.1", server.port)
            try:
                with self.assertRaises(errors.ProtocolError) as caught:
                    transport.submit("blocks.set", PARAMS)
                    transport.flush()
                self.assertEqual(caught.exception.outcome, "unknown")
                self.assertEqual(len(seen), 1)
                self.assertTrue(transport.closed)
            finally:
                transport.close()


if __name__ == "__main__":
    unittest.main()
