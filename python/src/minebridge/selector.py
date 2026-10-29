"""Typed selector constants; Minecraft itself parses selector expressions."""

from dataclasses import dataclass
import re
from typing import Final

__all__ = ["Selector", "playerByName", "ALL_PLAYERS", "RANDOM_PLAYER", "NEAREST_PLAYER", "SELF", "ALL_ENTITIES"]

_PLAYER_NAME = re.compile(r"[A-Za-z0-9_]{1,16}\Z", re.ASCII)


@dataclass(frozen=True, slots=True)
class Selector:
    """A vanilla selector, for example Selector('@a[tag=builders]')."""

    expression: str

    def __post_init__(self) -> None:
        if not isinstance(self.expression, str):
            raise TypeError("Selector expression must be a string")
        if not self.expression.startswith("@") or len(self.expression) > 2048 or "\x00" in self.expression:
            raise ValueError("Selector must start with @ and contain at most 2048 characters")

    def __str__(self) -> str:
        return self.expression


def playerByName(name: str) -> Selector:
    """Select at most one online player by their current, case-sensitive name.

    Construction is local and needs no connection or SELF context. The server
    resolves the name on each use; an offline name selects no players. Names
    must contain 1–16 ASCII letters, digits or underscores.
    """
    if not isinstance(name, str):
        raise TypeError("Player name must be a string")
    if _PLAYER_NAME.fullmatch(name) is None:
        raise ValueError("Player name must contain 1–16 ASCII letters, digits or underscores")
    return Selector(f"@a[name={name},limit=1]")


ALL_PLAYERS: Final[Selector] = Selector("@a")
RANDOM_PLAYER: Final[Selector] = Selector("@r")
NEAREST_PLAYER: Final[Selector] = Selector("@p")
SELF: Final[Selector] = Selector("@s")
ALL_ENTITIES: Final[Selector] = Selector("@e")
