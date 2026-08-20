# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0
"""Dimensions and their units — the table a profile supplies.

The language owns the *mechanism* and none of the table (ADR 0008,
§6.5.4): a literal may carry a suffix, a suffix belongs to a dimension,
a dimension normalizes to a base unit, and which dimensions exist is
somebody else's document. This module is the mechanism's data model; the
form that document takes is §7, and reading one is `world.py`.

**Factors are exact.** They are `Fraction`, not `float`, and that is
load-bearing rather than tidy: §6.3.10 decides whether a conversion is
exact at compile time, and `°F` normalizes through 50/9. A binary float
cannot answer "is this a whole number of base units" and this has to.
"""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date
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


#: Written out rather than taken from `calendar.month_name`, which is
#: whatever locale the build machine had.
_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

_UNIX_EPOCH = date(1970, 1, 1).toordinal()


def day_seconds(time: str) -> int:
    """`13:25` or `13:25:30` as seconds since midnight.

    Raises `ValueError` carrying a sentence: both callers — a script's
    literal and a profile's epoch — have a better place to say it than
    this function does.
    """
    parts = time.split(":")
    hour, minute = int(parts[0]), int(parts[1])
    second = int(parts[2]) if len(parts) > 2 else 0
    if hour > 23:
        raise ValueError(f"there is no hour {hour}")
    if minute > 59:
        raise ValueError(f"there is no minute {minute}")
    if second > 59:
        raise ValueError(
            f"there is no second {second}, and this calendar has no leap seconds"
        )
    return hour * 3600 + minute * 60 + second


def civil_seconds(day: str, time: str) -> int:
    """A date, and optionally a time, as seconds from 1970-01-01T00:00:00.

    The arithmetic §7.2.4 fixes: the proleptic Gregorian calendar, 86400
    seconds in every day, no leap seconds, and no time zone at either
    end. Negative before 1970.
    """
    year, month, number = (int(part) for part in day.split("-"))
    try:
        ordinal = date(year, month, number).toordinal()
    except ValueError as bad:
        raise ValueError(_impossible(year, month, number)) from bad
    return (ordinal - _UNIX_EPOCH) * 86400 + (day_seconds(time) if time else 0)


def _impossible(year: int, month: int, number: int) -> str:
    """Why a date that matched §6.1.7's shape is not a day."""
    if not 1 <= year <= 9999:
        return f"the year {year:04d} is outside 0001 to 9999"
    if not 1 <= month <= 12:
        return f"there is no month {month:02d}"
    if number < 1:
        return f"there is no day {number:02d}"
    return f"{_MONTHS[month - 1]} {year} has {monthrange(year, month)[1]} days"


@dataclass(frozen=True)
class Clock:
    """What a date-and-time literal counts, for a dimension that takes one.

    A profile marks at most two dimensions with one of these (§7.2.4).
    The one **with** an epoch takes every literal that carries a date;
    the one **without** takes the times of day, which count from
    midnight and are not points in history for an epoch to be measured
    from.

    `second` is what one second is worth in the base unit, exact for the
    reason every factor is.
    """

    second: Fraction
    #: Seconds from 1970-01-01T00:00:00 to the epoch, or `None` for a
    #: time of day. A number and not the fields, because nothing needs
    #: the fields again: what a literal is worth is one subtraction.
    epoch: int | None = None

    @property
    def is_time_of_day(self) -> bool:
        return self.epoch is None


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
    #: `@"2026-08-18 13:25"` belongs to this dimension, or `@"13:25"`
    #: does (§6.1.7, §7.2.4). A profile that marks none makes such a
    #: literal an error saying so.
    clock: Clock | None = None

    def __post_init__(self) -> None:
        if self.type not in NUMERIC:
            raise ValueError(f"dimension {self.name}: {self.type} is not numeric")
        if self.cyclic and self.scale:
            raise ValueError(f"dimension {self.name}: a ratio does not wrap")
        if self.clock is not None and self.scale:
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
    #: profile's identity and the version is its own, and a container
    #: cannot be built without either.
    id: int = 0
    _by_unit: dict[str, tuple[Dimension, Unit]] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )
    _by_name: dict[str, Dimension] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        roles: set[bool] = set()
        for dimension in self.dimensions:
            if dimension.clock is not None:
                role = dimension.clock.is_time_of_day
                if role in roles:
                    kind = "a time of day" if role else "a date"
                    raise ValueError(f"two dimensions take {kind}")
                roles.add(role)
            if dimension.name in self._by_name:
                raise ValueError(f"dimension {dimension.name} is declared twice")
            twin = self.by_id(dimension.id)
            if twin is not None and twin is not dimension:
                raise ValueError(
                    f"{twin.name} and {dimension.name} are both dimension "
                    f"{dimension.id}"
                )
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
    def instant(self) -> Dimension | None:
        """Where a literal carrying a date belongs, if anywhere (§7.2.4)."""
        return self._clock(time_of_day=False)

    @property
    def time_of_day(self) -> Dimension | None:
        """Where a literal that is only a time belongs, if anywhere."""
        return self._clock(time_of_day=True)

    def _clock(self, *, time_of_day: bool) -> Dimension | None:
        for dimension in self.dimensions:
            clock = dimension.clock
            if clock is not None and clock.is_time_of_day is time_of_day:
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
