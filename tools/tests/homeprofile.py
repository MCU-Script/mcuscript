# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0
"""The world the front end's tests compile against.

The tables are `home.toml`, `bare.toml` and `home-registry.toml` beside
this file, in the format §7 defines, and this module is nothing but the
reader called on them. That is deliberate rather than tidy: every test
that writes `24.5°C` or reads `sensor.temp` is now also a test that the
reader read a real file, and the numbers a script compiles to are the
numbers a profile author would get.

What the tables are chosen for is the awkward cases rather than good
advice — a temperature held in hundredths of a degree, a `°F` with an
offset, a dimension that wraps, and both calendar roles.
"""

from __future__ import annotations

from pathlib import Path

from mcuscript.opcodes import ValType
from mcuscript.profile import Dimension
from mcuscript.registry import Quantity
from mcuscript.world import read_profile, read_registry

_HERE = Path(__file__).parent

HOME = read_profile(_HERE / "home.toml")
#: The same profile with neither calendar role.
NO_CALENDAR = read_profile(_HERE / "bare.toml")
REGISTRY = read_registry(_HERE / "home-registry.toml", HOME)


def dimension(name: str) -> Dimension:
    found = HOME.find_dimension(name)
    assert found is not None, name
    return found


TEMPERATURE = dimension("temperature")
HUMIDITY = dimension("humidity")
DURATION = dimension("duration")
RATIO = dimension("ratio")
INSTANT = dimension("instant")
UPTIME = dimension("uptime")
DAYTIME = dimension("daytime")

T = Quantity(ValType.I32, TEMPERATURE)
H = Quantity(ValType.I32, HUMIDITY)
D = Quantity(ValType.I32, DURATION)
N = Quantity(ValType.I32)
B = Quantity(ValType.BOOL)
