"""Public access to cached, negotiated connection metadata."""

from typing import Literal
from uuid import UUID

from .._transport import TcpTransport
from ..errors import ProtocolError
from ..models.controls import ConnectionInfo, WorldInfo

__all__ = ["Server"]


class Server:
    """These methods use hello metadata and never issue a network request."""

    __slots__ = ("_info",)

    def __init__(self, transport: TcpTransport, write_mode: Literal["buffered", "sync"],
                 logging: bool = False) -> None:
        context = transport.context
        if context is None:
            raise ProtocolError("A successful handshake is required")
        self._info = ConnectionInfo(
            UUID(context.session_id), context.plugin_version, context.server_version,
            context.protocol.major, context.protocol.minor,
            WorldInfo(context.world.name, context.world.key, UUID(context.world.uuid),
                      context.world.min_y, context.world.max_y_exclusive),
            write_mode, logging, context.capabilities,
        )

    def getInfo(self) -> ConnectionInfo:
        """Return immutable metadata from hello, including the configured write mode."""
        return self._info

    def getCapabilities(self) -> tuple[str, ...]:
        """Return the negotiated capability names without opening another RPC."""
        return self._info.capabilities
