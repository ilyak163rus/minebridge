"""Tiny real game-protocol clients for the pinned Paper acceptance fixture.

No simulated Bukkit players, user accounts, GUI or game-library dependency.
Packet IDs are exported by the separate observer from the exact test server.
Only login/configuration, liveness and teleport acknowledgements are decoded;
chat evidence is the actual clientbound packet bytes, never a bridge response.
"""

from __future__ import annotations

import hashlib
import io
import socket
import struct
import threading
import time
import uuid
import zlib


def varint(value: int) -> bytes:
    result = bytearray()
    value &= 0xffffffff
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def read_varint(stream) -> int:
    result = 0
    for shift in range(0, 35, 7):
        byte = stream.read(1)
        if not byte:
            raise EOFError("Game connection ended")
        value = byte[0]
        result |= (value & 127) << shift
        if value < 128:
            return result
    raise ValueError("Invalid game VarInt")


def string(value: str) -> bytes:
    raw = value.encode("utf-8")
    return varint(len(raw)) + raw


class _SocketReader:
    def __init__(self, connection):
        self.connection = connection

    def read(self, count):
        result = bytearray()
        while len(result) < count:
            chunk = self.connection.recv(count - len(result))
            if not chunk:
                raise EOFError("Game connection ended")
            result.extend(chunk)
        return bytes(result)


class GameClient:
    def __init__(self, port: int, name: str, protocol: dict):
        self.name, self.protocol = name, protocol
        self.uuid = str(uuid.UUID(bytes=hashlib.md5(("OfflinePlayer:" + name).encode()).digest(), version=3))
        self.entity_id = None
        self.position_packets: list[dict] = []
        self.chat_packets: list[bytes] = []
        self.sent_chat_packets: list[dict] = []
        self.sent_action_packets: list[dict] = []
        self._action_sequence = 0
        self.errors: list[str] = []
        self.state, self.compression = "login", None
        self._closed = False
        self._send_lock = threading.Lock()
        self._ready = threading.Event()
        self._connection = socket.create_connection(("127.0.0.1", port), timeout=15)
        self._connection.settimeout(60)
        self._reader = _SocketReader(self._connection)
        # Minecraft 26.2 is protocol 776, also checked by the real server during login.
        self._send_raw(varint(0) + varint(776) + string("127.0.0.1") + struct.pack(">H", port) + varint(2))
        self._send("hello", string(name) + uuid.UUID(self.uuid).bytes)
        self._thread = threading.Thread(target=self._receive, name="game-fixture-" + name, daemon=True)
        self._thread.start()

    def _id(self, direction, name):
        return self.protocol[self.state + "." + direction]["minecraft:" + name]

    def _send_raw(self, payload):
        with self._send_lock:
            if self.compression is not None:
                payload = (varint(len(payload)) + zlib.compress(payload) if len(payload) >= self.compression
                           else b"\0" + payload)
            self._connection.sendall(varint(len(payload)) + payload)

    def _send(self, name, data=b""):
        self._send_raw(varint(self._id("serverbound", name)) + data)

    def _receive(self):
        try:
            while not self._closed:
                length = read_varint(self._reader)
                if length > 8 * 1024 * 1024:
                    raise ValueError("Oversized game fixture packet")
                raw = self._reader.read(length)
                if self.compression is not None:
                    envelope = io.BytesIO(raw)
                    unpacked = read_varint(envelope)
                    raw = zlib.decompress(envelope.read()) if unpacked else envelope.read()
                    if unpacked and len(raw) != unpacked:
                        raise ValueError("Game compression length mismatch")
                payload = io.BytesIO(raw)
                packet_id = read_varint(payload)
                names = self.protocol[self.state + ".clientbound"]
                name = next((key.split(":", 1)[1] for key, value in names.items() if value == packet_id), None)
                body = payload.read()
                if name in ("disconnect", "login_disconnect"):
                    raise AssertionError("Game server disconnected fixture: " + repr(body[:200]))
                if self.state == "login":
                    if name == "login_compression":
                        self.compression = read_varint(io.BytesIO(body))
                    elif name == "login_finished":
                        actual = str(uuid.UUID(bytes=body[:16]))
                        if actual != self.uuid:
                            raise AssertionError("Unexpected offline player UUID")
                        self._send("login_acknowledged")
                        self.state = "configuration"
                elif self.state == "configuration":
                    if name == "select_known_packs":
                        self._send("select_known_packs", varint(0))
                    elif name == "finish_configuration":
                        self._send("finish_configuration")
                        self.state = "game"
                    elif name == "keep_alive":
                        self._send("keep_alive", body)
                    elif name == "ping":
                        self._send("pong", body)
                else:
                    if name == "login":
                        self.entity_id = struct.unpack(">i", body[:4])[0]
                    elif name == "player_position":
                        content = io.BytesIO(body)
                        teleport_id = read_varint(content)
                        x, y, z = struct.unpack(">ddd", content.read(24))
                        self.position_packets.append({"id": teleport_id, "x": x, "y": y, "z": z})
                        self._send("accept_teleportation", varint(teleport_id))
                        # 26.2 gates native actions on hasClientLoaded(). A
                        # teleport ACK alone leaves the initial/respawn load
                        # timer active; the headless client must acknowledge
                        # its completed world load explicitly as real clients do.
                        self._send("player_loaded")
                        self._ready.set()
                    elif name in ("system_chat", "disguised_chat", "player_chat"):
                        self.chat_packets.append(body)
                    elif name == "keep_alive":
                        self._send("keep_alive", body)
                    elif name == "ping":
                        self._send("pong", body)
                    elif name == "chunk_batch_finished":
                        self._send("chunk_batch_received", struct.pack(">f", 64.0))
        except (OSError, EOFError) as failure:
            if not self._closed:
                self.errors.append(str(failure))
        except Exception as failure:
            self.errors.append(type(failure).__name__ + ": " + str(failure))
        finally:
            self._ready.set()

    def wait_ready(self, timeout=30):
        if not self._ready.wait(timeout) or self.errors or self.entity_id is None:
            raise AssertionError((self.name, self.state, self.entity_id, self.errors))
        return self

    def wait_chat(self, message: str, timeout=10):
        expected, deadline = message.encode("utf-8"), time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.errors:
                raise AssertionError(self.errors)
            for packet in self.chat_packets:
                if expected in packet:
                    return {"utf8": message, "packetSha256": hashlib.sha256(packet).hexdigest(),
                            "packetBytes": len(packet)}
            time.sleep(.01)
        raise AssertionError("Game client did not receive chat: " + self.name)

    def send_chat(self, message: str):
        """Send a real unsigned 26.2 player-chat packet in the offline fixture.

        The pinned server's ServerboundChatPacket codec includes the newer
        LastSeenMessages.Update checksum byte. All fixture players are unsigned,
        so no received signatures enter the server's acknowledgement window.
        A zero checksum is its explicit IGNORE_CHECKSUM value.
        """
        if self.state != "game" or not self._ready.is_set() or self.errors:
            raise AssertionError("Chat requires a connected game fixture")
        if not isinstance(message, str) or not message or len(message) > 256:
            raise ValueError("Game fixture chat must contain 1..256 characters")
        timestamp = time.time_ns() // 1_000_000
        salt = uuid.uuid4().int & ((1 << 63) - 1)
        payload = (string(message) + struct.pack(">qq", timestamp, salt)
                   + b"\0" + varint(0) + b"\0\0\0" + b"\0")
        self._send("chat", payload)
        self.sent_chat_packets.append({"message": message, "epochMillis": timestamp,
                                       "payloadSha256": hashlib.sha256(payload).hexdigest()})

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self._connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._connection.close()
        self._thread.join(timeout=5)
        if self._thread.is_alive():
            raise AssertionError("Game fixture worker leaked")

    def _action(self, name, payload, detail):
        if self.state != "game" or self.errors:
            raise AssertionError("Action requires a connected game fixture")
        self._send(name, payload)
        self.sent_action_packets.append({"packet": name, **detail,
                                        "payloadSha256": hashlib.sha256(payload).hexdigest()})

    def _sequence(self):
        self._action_sequence += 1
        return self._action_sequence

    @staticmethod
    def _block_pos(position):
        x, y, z = position
        packed = ((x & 0x3ffffff) << 38) | ((z & 0x3ffffff) << 12) | (y & 0xfff)
        return struct.pack(">Q", packed)

    def break_block(self, position, *, action=0, face=1):
        """Native START/ABORT/STOP_DESTROY_BLOCK (verified pinned 26.2 codec)."""
        self._action("player_action", varint(action) + self._block_pos(position)
                     + bytes([face]) + varint(self._sequence()),
                     {"action": action, "position": list(position), "face": face})

    def use_block(self, position, *, hand=0, face=1):
        # 26.2 BlockHitResult has TWO booleans: inside and world-border hit.
        payload = (varint(hand) + self._block_pos(position) + varint(face)
                   + struct.pack(">fff", .5, 1.0 if face == 1 else .5, .5)
                   + b"\0\0" + varint(self._sequence()))
        self._action("use_item_on", payload, {"position": list(position), "face": face, "hand": hand})

    def use_item(self, *, hand=0, yaw=0.0, pitch=0.0):
        self._action("use_item", varint(hand) + varint(self._sequence())
                     + struct.pack(">ff", yaw, pitch), {"hand": hand, "yaw": yaw, "pitch": pitch})

    def release_item(self):
        self.break_block((0, 0, 0), action=5, face=0)

    def attack(self, entity_id):
        # Since 26.2 attack has its own packet; old InteractPacket action=1 is invalid.
        self._action("attack", varint(entity_id), {"entityId": entity_id})

    def respawn(self):
        self._action("client_command", varint(0), {"action": "PERFORM_RESPAWN"})

    def evidence(self):
        return {"name": self.name, "uuid": self.uuid, "entityId": self.entity_id,
                "positionPackets": self.position_packets, "receivedChatPackets": len(self.chat_packets),
                "sentChatPackets": list(self.sent_chat_packets),
                "sentActionPackets": list(self.sent_action_packets),
                "errors": list(self.errors), "realTcpGameConnection": True}
