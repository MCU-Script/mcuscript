# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0
"""Dimensions and their units — the table a profile supplies.

The language owns the *mechanism* and none of the table (ADR 0008,
§6.5.4): a literal may carry a suffix, a suffix belongs to a dimension,
a dimension normalizes to a base unit, and which dimensions exist is
somebody else's document. This module is the mechanism's data model, and
it deliberately has no file format — reading a profile off disk is M4's,
and nothing here should have to change when it arrives.

**Factors are exact.** They are `Fraction`, not `float`, and that is
load-bearing rather than tidy: §6.3.10 decides whether a conversion is
exact at compile time, and `°F` normalizes through 50/9. A binary float
cannot answer "is this a whole number of base units" and this has to.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from .opcodes import ValType

#: The data types a dimension may be held in. `bool` is not one of them:
#: a quantity that is a yes-or-no has no units to convert.
NUMERIC = (ValType.I32, ValType.I64, ValType.F32)


@dataclass(frozen=True)
class Unit:
    """One spelling, and what a number written with it means.

    A value written as `n` of this unit is `n * factor + offset` in the
    dimension's base unit. The offset is what `°F` needs and almost
    nothing else does.
    """

    spelling: str
    factor: Fraction = Fraction(1)
    offset: Fraction = Fraction(0)

    @property
    def is_affine(self) -> bool:
        return self.offset != 0


@dataclass(frozen=True)
class Dimension:
    """A quantity a profile declares, with the resolution it is held at.

    `type` and `base_unit` are one statement and not two (§6.5.4): they
    say how fine the quantity is, and every arithmetic result in this
    dimension carries them.
    """

    id: int
    name: str
    type: ValType
    base_unit: str
    units: tuple[Unit, ...] = ()
    #: Values wrap; comparisons lower as differences (§6.5.6).
    cyclic: bool = False
    #: A pure ratio: `%`, `‰`. Multiplies anything, and `x + 5%` is a
    #: relative change (§6.5.5.1).
    scale: bool = False
    #: `@"2026-08-18 13:25"` belongs to this dimension (§6.1.7). A
    #: profile that marks none makes such a literal an error saying so.
    #: What the fields normalize *to* needs an epoch, and that is the
    #: profile format's — M4's, not this model's.
    calendar: bool = False

    def __post_init__(self) -> None:
        if self.type not in NUMERIC:
            raise ValueError(f"dimension {self.name}: {self.type} is not numeric")
        if self.cyclic and self.scale:
            raise ValueError(f"dimension {self.name}: a ratio does not wrap")
        if self.calendar and self.scale:
            raise ValueError(f"dimension {self.name}: a ratio is not a calendar")
        spellings = [u.spelling for u in self.units]
        if len(set(spellings)) != len(spellings):
            raise ValueError(f"dimension {self.name}: a unit is spelled twice")

    def unit(self, spelling: str) -> Unit | None:
        for candidate in self.units:
            if candidate.spelling == spelling:
                return candidate
        return None

    @property
    def is_integer(self) -> bool:
        return self.type in (ValType.I32, ValType.I64)


@dataclass(frozen=True)
class Profile:
    """Every dimension a compilation knows about.

    A profile with no dimensions is legal and is not a degenerate case
    (§6.5.4): every number is then a bare number and every suffix is an
    error naming the profile.
    """

    name: str
    version: str
    dimensions: tuple[Dimension, ...] = ()
    #: What a container pins itself to (§2.4). The number is the
    #: profile's identity and the version is its own; both are here
    #: rather than in the file format M4 decides, because a container
    #: cannot be built without them and chapter 2 is what asks.
    id: int = 0
    _by_unit: dict[str, tuple[Dimension, Unit]] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )
    _by_name: dict[str, Dimension] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        for dimension in self.dimensions:
            if dimension.name in self._by_name:
                raise ValueError(f"dimension {dimension.name} is declared twice")
            self._by_name[dimension.name] = dimension
            for unit in dimension.units:
                if unit.spelling in self._by_unit:
                    other = self._by_unit[unit.spelling][0]
                    raise ValueError(
                        f"unit {unit.spelling!r} belongs to both "
                        f"{other.name} and {dimension.name}"
                    )
                self._by_unit[unit.spelling] = (dimension, unit)

    @property
    def major(self) -> int:
        return int(self.version.split(".")[0])

    @property
    def minor(self) -> int:
        parts = self.version.split(".")
        return int(parts[1]) if len(parts) > 1 else 0

    def find_unit(self, spelling: str) -> tuple[Dimension, Unit] | None:
        """The dimension a suffix belongs to, and what it scales by."""
        return self._by_unit.get(spelling)

    @property
    def calendar(self) -> Dimension | None:
        """The dimension `@"…"` belongs to, if the profile names one."""
        for dimension in self.dimensions:
            if dimension.calendar:
                return dimension
        return None

    def find_dimension(self, name: str) -> Dimension | None:
        """A dimension by the name an annotation would use (§6.5.3)."""
        return self._by_name.get(name)

    def by_id(self, identifier: int) -> Dimension | None:
        for dimension in self.dimensions:
            if dimension.id == identifier:
                return dimension
        return None

    @property
    def unit_spellings(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_unit))


EMPTY = Profile("none", "0")
"""A profile that declares nothing, which §6.5.4 says is legal."""
