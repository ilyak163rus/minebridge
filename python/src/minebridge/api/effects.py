"""Effects on one prevalidated set of living entities."""

from __future__ import annotations

import math
from typing import Any, cast
from uuid import UUID

from .._transport import TcpTransport
from .._capabilities import require_capability
from ..models import EffectKey, TargetOutcome, TargetResult
from .players import TargetSpec, _integer, _target_result, normalize_targets

__all__ = ["Effects"]


class Effects:
    """Apply effects in game seconds; level=1 means the first effect level."""

    __slots__ = ("_transport", "_world", "_executor")

    def __init__(self, transport: TcpTransport, world: str, executor: UUID | None = None) -> None:
        self._transport = transport
        self._world = world
        self._executor = executor

    def add(self, targets: TargetSpec, effect: EffectKey | str, duration: int | float,
            level: int = 1, *, particles: bool = True) -> TargetResult:
        """Apply an effect once to each selected living entity and return outcomes.

        Positive durations round upward to whole ticks. The operation waits for
        its result in either write mode and also drains earlier buffered writes.
        """
        if isinstance(effect, str):
            effect = EffectKey(effect)
        if not isinstance(effect, EffectKey):
            raise TypeError("effect must be EffectKey or a namespace:path string")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)):
            raise TypeError("Effect duration must be a number of game seconds")
        if not 0 < duration <= 2147483647 / 20 or not math.isfinite(duration):
            raise ValueError("Effect duration must be finite, positive and fit int32 ticks")
        ticks = math.ceil(duration * 20)
        if isinstance(level, bool) or not isinstance(level, int):
            raise TypeError("Effect level must be an integer")
        if not 1 <= level <= 256:
            raise ValueError("Effect level must be between 1 and 256")
        if not isinstance(particles, bool):
            raise TypeError("particles must be bool")
        response = self._transport.exchange("effects.add", {
            "world": self._world,
            "executor": str(self._executor) if self._executor is not None else None,
            "targets": normalize_targets(targets),
            "effect": {"key": effect.key, "durationTicks": ticks,
                       "level": level, "particles": particles},
        }, mutation=True)
        value = cast(dict[str, Any], response.result)
        return TargetResult(_integer(value["matched"]), _integer(value["applied"]), tuple(
            TargetOutcome(UUID(target["uuid"]), target["applied"], target["code"])
            for target in value["targets"]))

    def remove(self, targets: TargetSpec, effect: EffectKey | str) -> TargetResult:
        """Remove one effect from a prevalidated set of living entities."""
        if isinstance(effect, str):
            effect = EffectKey(effect)
        if not isinstance(effect, EffectKey):
            raise TypeError("effect must be EffectKey or a namespace:path string")
        return self._remove("effects.remove", targets, {"effect": {"key": effect.key}})

    def clear(self, targets: TargetSpec) -> TargetResult:
        """Remove all active effects; an already clear target is a completed operation."""
        return self._remove("effects.clear", targets, {})

    def _remove(self, method: str, targets: TargetSpec,
                extra: dict[str, object]) -> TargetResult:
        parameters: dict[str, object] = {
            "world": self._world,
            "executor": str(self._executor) if self._executor is not None else None,
            "targets": normalize_targets(targets),
        }
        parameters.update(extra)
        require_capability(self._transport, method)
        response = self._transport.exchange(method, parameters, mutation=True)
        return _target_result(cast(dict[str, Any], response.result))
