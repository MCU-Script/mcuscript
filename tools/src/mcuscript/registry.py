# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0
"""What a script may reach — the embedder's declaration.

Kept apart from `profile.py` because they have different owners
(ADR 0001): which dimensions exist is a profile's, and which entities
and functions a script may touch is the **embedder's**. A compiler needs
both and they arrive from different places.

This is richer than the container's `HOST` table and has to be. That
table carries one dimension per import (§4.4) because units are gone by
then and all a loader checks is that the host agrees about an entity's
dimension. A *compiler* has to check the dimension of every argument to
every call, and the container has nowhere to record those — which is
worth knowing rather than discovering: `timer.after(5s)` compiled
against a registry that says seconds, and run against a host that meant
milliseconds, is not caught by anything at load.
"""

from __future__ import annotations

from dataclasses import dataclass

from .opcodes import ValType
from .profile import Dimension


@dataclass(frozen=True)
class Quantity:
    """A type and, if it has one, a dimension. Both halves matter.

    A dimension is a type (§6.5.3), so a temperature is not an `i32`
    even where a profile holds it in one, and `dimension` is not a
    decoration on `type` — it is half of what the value *is*.
    """

    type: ValType
    dimension: Dimension | None = None

    def __str__(self) -> str:
        return self.dimension.name if self.dimension else str(self.type)

    @property
    def is_scale(self) -> bool:
        return self.dimension is not None and self.dimension.scale


@dataclass(frozen=True)
class Entity:
    """A value the host owns: read, written, or both."""

    name: str
    quantity: Quantity
    readable: bool = True
    writable: bool = False

    @property
    def kind(self) -> str:
        return "entity"


@dataclass(frozen=True)
class HostFunction:
    """Something a script calls. `returns` is `None` for no value."""

    name: str
    params: tuple[Quantity, ...] = ()
    returns: Quantity | None = None

    @property
    def kind(self) -> str:
        return "function"


@dataclass(frozen=True)
class Registry:
    """Every name a script may use that it did not declare itself."""

    entities: tuple[Entity, ...] = ()
    functions: tuple[HostFunction, ...] = ()

    def find(self, name: str) -> Entity | HostFunction | None:
        for entity in self.entities:
            if entity.name == name:
                return entity
        for function in self.functions:
            if function.name == name:
                return function
        return None

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(
            sorted([e.name for e in self.entities] + [f.name for f in self.functions])
        )


EMPTY = Registry()
"""A world a script can reach nothing in. Useful for testing arithmetic."""


def nearest(name: str, candidates: tuple[str, ...], limit: int = 3) -> list[str]:
    """The known names closest to a misspelling.

    §6.7's first obligation is to name the thing and say what to do, and
    *"there is no `sensor.tmp`, did you mean `sensor.temp`?"* is the
    example the project has used for this since before there was a
    compiler. The distance is plain Levenshtein, computed here rather
    than imported, because this distribution has no dependencies.
    """
    scored = [(_distance(name, other), other) for other in candidates]
    scored.sort()
    cutoff = max(2, len(name) // 3)
    return [other for score, other in scored[:limit] if score <= cutoff]


def _distance(a: str, b: str) -> int:
    if a == b:
        return 0
    previous = list(range(len(b) + 1))
    for i, left in enumerate(a, start=1):
        current = [i]
        for j, right in enumerate(b, start=1):
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + (left != right),
                )
            )
        previous = current
    return previous[-1]
