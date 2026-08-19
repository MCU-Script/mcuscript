# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0
"""A plausible home profile and registry, for testing the front end.

This is **not** a draft of the profile format. It is the data model of
`profile.py` filled in by hand, so that inference has dimensions to work
against before M4 decides how a profile is written down. The numbers are
chosen to exercise the awkward cases rather than to be recommended:
temperature is held in hundredths of a degree so that `24.5°C` is exact
and `24.555°C` is not, and `°F` carries an offset as well as a factor.
"""

from __future__ import annotations

from fractions import Fraction

from mcuscript.opcodes import ValType
from mcuscript.profile import Dimension, Profile, Unit
from mcuscript.registry import Entity, HostFunction, Quantity, Registry

TEMPERATURE = Dimension(
    1,
    "temperature",
    ValType.I32,
    "c°C",
    (
        Unit("c°C", Fraction(1)),
        Unit("°C", Fraction(100)),
        # 1 °F is 5/9 °C, and the scale starts 32 °F lower.
        Unit("°F", Fraction(500, 9), Fraction(-16000, 9)),
    ),
)

HUMIDITY = Dimension(
    2,
    "humidity",
    ValType.I32,
    "d%",
    (Unit("d%", Fraction(1)), Unit("%", Fraction(10))),
)

DURATION = Dimension(
    3,
    "duration",
    ValType.I32,
    "ms",
    (
        Unit("ms", Fraction(1)),
        Unit("s", Fraction(1000)),
        Unit("min", Fraction(60_000)),
        Unit("h", Fraction(3_600_000)),
        Unit("d", Fraction(86_400_000)),
    ),
)

#: A scale factor (§6.5.5.1): a pure ratio whose units are multipliers.
RATIO = Dimension(
    4,
    "ratio",
    ValType.F32,
    "one",
    (
        Unit("one", Fraction(1)),
        Unit("pct", Fraction(1, 100)),
        Unit("ppm", Fraction(1, 10**6)),
    ),
    scale=True,
)

#: A dimension whose values wrap (§6.5.6): milliseconds since the device
#: started, held in an `i32`, so it returns to its start after 49.7 days.
#: The period is the type's — which is the whole rule, and the reason a
#: comparison of two of these lowers as a difference.
UPTIME = Dimension(
    6,
    "uptime",
    ValType.I32,
    "ms_up",
    (Unit("ms_up", Fraction(1)), Unit("s_up", Fraction(1000))),
    cyclic=True,
)

#: A clock, so that `@"…"` has somewhere to belong (§6.1.7). What the
#: fields normalize to needs an epoch, which is M4's.
INSTANT = Dimension(
    5, "instant", ValType.I64, "ms_utc", (Unit("ms_utc", Fraction(1)),), calendar=True
)

HOME = Profile(
    "home", "0.1", (TEMPERATURE, HUMIDITY, DURATION, RATIO, UPTIME, INSTANT), id=1
)

#: The same profile without a calendar, for the refusal §6.1.7 promises.
NO_CALENDAR = Profile("bare", "0.1", (TEMPERATURE, HUMIDITY, DURATION, RATIO), id=1)

T = Quantity(ValType.I32, TEMPERATURE)
H = Quantity(ValType.I32, HUMIDITY)
D = Quantity(ValType.I32, DURATION)
N = Quantity(ValType.I32)
B = Quantity(ValType.BOOL)

REGISTRY = Registry(
    entities=(
        Entity("sensor.temp", T),
        Entity("sensor.outside", T),
        Entity("sensor.humidity", H),
        Entity("sensor.count", N),
        Entity("clock.hour", N),
        Entity("fan.speed", N, writable=True),
        Entity("valve.open", B, writable=True),
        Entity("led.fault", B, readable=False, writable=True),
        Entity("state.latch", B, writable=True),
        Entity("setpoint.target", T, writable=True),
        # An embedder may declare a bare name, and some do.
        Entity("brightness", N, writable=True),
        Entity("timer.started", Quantity(ValType.I32, UPTIME)),
        Entity("timer.expires", Quantity(ValType.I32, UPTIME)),
    ),
    functions=(
        HostFunction("fan.on"),
        HostFunction("timer.after", (D,)),
        HostFunction("math.log", (Quantity(ValType.F32),), Quantity(ValType.F32)),
    ),
)
