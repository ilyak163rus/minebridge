"""Local feature checks for additive APIs on older Minebridge servers."""

from ._transport import TcpTransport
from .errors import ConnectionError, ProtocolError, UnsupportedFeatureError


def require_capability(transport: TcpTransport, method: str) -> None:
    if transport.closed:
        raise ConnectionError("TCP connection is closed")
    context = transport.context
    if context is None:
        raise ProtocolError("A successful handshake is required")
    if method not in context.capabilities:
        raise UnsupportedFeatureError(f"Server does not support {method}; update the Minebridge plugin")
