"""Time, weather and typed game rules in loaded Paper worlds."""

from __future__ import annotations

from typing import Any, TypeVar, cast, overload

from .._capabilities import require_capability
from .._transport import TcpTransport
from ..errors import ProtocolError
from ..models.controls import GameRuleKey, Weather
from .players import _integer

__all__ = ["Worlds"]

RuleValue = TypeVar("RuleValue", bool, int)


def _rule_name(rule: GameRuleKey[Any] | str) -> str:
    value = rule.key if isinstance(rule, GameRuleKey) else rule
    if not isinstance(value, str):
        raise TypeError("rule must be GameRuleKey or a rule key string")
    if not value.strip() or "\x00" in value or len(value) > 256:
        raise ValueError("rule key must contain 1–256 characters and no NUL")
    return value


def _known_rule(rule: GameRuleKey[Any] | str) -> GameRuleKey[Any] | None:
    if isinstance(rule, GameRuleKey):
        return rule
    from .. import gamerule
    return gamerule._BY_KEY.get(rule)


class Worlds:
    """Default to the world negotiated by create; explicit world names/keys are optional."""

    __slots__ = ("_transport", "_world")

    def __init__(self, transport: TcpTransport, world: str) -> None:
        self._transport = transport
        self._world = world

    def _parameters(self, world: str | None) -> dict[str, object]:
        if world is not None and not isinstance(world, str):
            raise TypeError("world must be a name/key string or None")
        if world is not None and (not world.strip() or "\x00" in world):
            raise ValueError("world must be nonempty and contain no NUL")
        return {"world": self._world if world is None else world}

    def _call(self, method: str, parameters: dict[str, object], *, mutation: bool = False) -> dict[str, Any]:
        require_capability(self._transport, method)
        return cast(dict[str, Any], self._transport.exchange(method, parameters, mutation=mutation).result)

    def getTime(self, *, world: str | None = None) -> int:
        """Read relative game-time ticks (zero through 23999), not real seconds."""
        return _integer(self._call("worlds.getTime", self._parameters(world))["time"])

    def setTime(self, time: int, *, world: str | None = None) -> None:
        """Set relative time using Paper semantics; an earlier time can advance the day."""
        if isinstance(time, bool) or not isinstance(time, int):
            raise TypeError("time must be an integer number of game-time ticks")
        if not 0 <= time <= 23999:
            raise ValueError("time must be between 0 and 23999")
        parameters = self._parameters(world)
        parameters["time"] = time
        self._call("worlds.setTime", parameters, mutation=True)

    def getWeather(self, *, world: str | None = None) -> Weather:
        """Read clear/rain/thunder at the time of the server request."""
        return Weather(self._call("worlds.getWeather", self._parameters(world))["weather"])

    def setWeather(self, weather: Weather | str, *, world: str | None = None) -> None:
        """Set current weather; normal weather cycles may change it later."""
        if not isinstance(weather, (Weather, str)):
            raise TypeError("weather must be Weather or clear/rain/thunder")
        try:
            value = Weather(weather)
        except ValueError:
            raise ValueError("weather must be clear, rain or thunder") from None
        parameters = self._parameters(world)
        parameters["weather"] = value.value
        self._call("worlds.setWeather", parameters, mutation=True)

    @overload
    def getGameRule(self, rule: GameRuleKey[RuleValue], *, world: str | None = None) -> RuleValue: ...
    @overload
    def getGameRule(self, rule: str, *, world: str | None = None) -> bool | int: ...

    def getGameRule(self, rule: GameRuleKey[Any] | str, *, world: str | None = None) -> bool | int:
        """Read a typed game-rule value; no type is inferred from truthiness."""
        name = _rule_name(rule)
        parameters = self._parameters(world)
        parameters["rule"] = name
        value = self._call("worlds.getGameRule", parameters)
        if value["rule"] != name:
            self._transport.close()
            raise ProtocolError("Game rule result does not match the requested rule")
        result = value["value"]
        decoded: bool | int = result if type(result) is bool else _integer(result)
        specification = _known_rule(rule)
        if specification is not None and type(decoded) is not specification.valueType:
            self._transport.close()
            raise ProtocolError("Game rule result does not match the declared value type")
        return decoded

    @overload
    def setGameRule(self, rule: GameRuleKey[RuleValue], value: RuleValue, *, world: str | None = None) -> None: ...
    @overload
    def setGameRule(self, rule: str, value: bool | int, *, world: str | None = None) -> None: ...

    def setGameRule(self, rule: GameRuleKey[Any] | str, value: bool | int, *, world: str | None = None) -> None:
        """Set one bool/int game rule; the server validates rule-specific constraints."""
        name = _rule_name(rule)
        if type(value) not in (bool, int):
            raise TypeError("game rule value must be bool or int")
        specification = _known_rule(rule)
        if specification is not None and type(value) is not specification.valueType:
            raise TypeError("game rule value must match the rule's valueType")
        if type(value) is int and not -(2**31) <= value <= 2**31 - 1:
            raise ValueError("integer game rule value must fit int32")
        parameters = self._parameters(world)
        parameters.update({"rule": name, "value": value})
        self._call("worlds.setGameRule", parameters, mutation=True)
