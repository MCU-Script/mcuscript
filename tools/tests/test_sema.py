# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0
"""Types, dimensions and units — specification §6.5 and §6.5.5."""

from __future__ import annotations

from fractions import Fraction

import pytest
from homeprofile import HOME, NO_CALENDAR, REGISTRY

from mcuscript.diagnostics import CompileError
from mcuscript.parser import parse
from mcuscript.sema import analyse


def analyse_source(source: str, profile=HOME):
    return analyse(parse(source, "t.mcs"), profile, REGISTRY)


def in_entry(body: str, profile=HOME):
    return analyse_source("on e {\n" + body + "\n}", profile)


def refuse(body: str, profile=HOME) -> CompileError:
    with pytest.raises(CompileError) as caught:
        in_entry(body, profile)
    return caught.value


def message(body: str, profile=HOME) -> str:
    error = refuse(body, profile)
    return error.first.message + " " + " ".join(error.first.notes)


def quantity(expression: str) -> str:
    """The type of a file that is a single expression (§6.2.2)."""
    program = parse(expression, "t.mcs")
    analysis = analyse(program, HOME, REGISTRY)
    return str(analysis.type_of(program.expression))


# -- §6.5.5 the data type follows the dimension ------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("sensor.temp", "temperature"),
        ("sensor.temp + 2°C", "temperature"),
        ("sensor.temp - sensor.outside", "temperature"),
        ("(sensor.temp + sensor.outside) / 2", "temperature"),
        ("sensor.temp * 2", "temperature"),
        # Two of one dimension cancel, so nothing is left to declare a
        # resolution and the ratio is a decimal.
        ("sensor.temp / sensor.outside", "f32"),
        ("sensor.count / 2", "f32"),
        ("sensor.count + 1", "i32"),
        ("sensor.temp > 25°C", "bool"),
        ("clock.hour", "i32"),
        ("3h 45min", "duration"),
        ("24.5°C", "temperature"),
        ("75%", "humidity"),
    ],
)
def test_the_type_of_an_expression(source, expected):
    assert quantity(source) == expected


def test_a_dimension_and_a_bare_number_do_not_mix():
    assert "different kinds" in message("let x = sensor.temp + 5")


def test_two_dimensions_do_not_mix():
    assert "temperature and humidity" in message(
        "let x = sensor.temp + sensor.humidity"
    )


def test_two_dimensions_do_not_multiply():
    assert "not a quantity" in message("let x = sensor.temp * sensor.humidity")


def test_a_comparison_needs_one_kind():
    assert "different kinds" in message("let x = sensor.temp > 25")


# -- §6.5.5.1 scale factors --------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("sensor.temp * 5pct", "temperature"),
        ("sensor.temp / 5pct", "temperature"),
        ("sensor.temp + 5pct", "temperature"),
        ("sensor.temp - 5pct", "temperature"),
        ("5pct + 3pct", "ratio"),
    ],
)
def test_a_ratio_scales_and_shifts(source, expected):
    assert quantity(source) == expected


def test_a_ratio_is_not_commutative_under_plus():
    # §6.5.5.1: `x + 5%` is a relative change; the other way round is a
    # category error and is refused rather than guessed at.
    assert "no meaning" in message("let x = 5pct + sensor.temp")


def test_a_bare_number_is_not_a_ratio():
    assert "different kinds" in message("let x = sensor.temp + 0.05")


# -- §6.1.5 and §6.1.6 literals and their units ------------------------


def test_a_literal_normalizes_to_base_units():
    program = parse("24.5°C", "t.mcs")
    analysis = analyse(program, HOME, REGISTRY)
    assert analysis.values[id(program.expression)] == Fraction(2450)


def test_a_literal_finer_than_the_profile_is_refused():
    text = message("let x = 24.555°C")
    assert "24.555°C is finer" in text
    assert "0.01°C" in text


def test_fahrenheit_carries_its_offset():
    program = parse("32°F", "t.mcs")
    analysis = analyse(program, HOME, REGISTRY)
    assert analysis.values[id(program.expression)] == Fraction(0)


def test_a_duration_sums_its_parts():
    program = parse("3h 45min", "t.mcs")
    analysis = analyse(program, HOME, REGISTRY)
    assert analysis.values[id(program.expression)] == Fraction(13_500_000)


def test_duration_parts_descend():
    assert "not smaller" in message("let d = 45min 3h")


def test_duration_parts_share_one_dimension():
    assert "duration" in message("let d = 3h 45%")


def test_an_unknown_unit_suggests_a_known_one():
    assert "`min`" in message("let d = 5mim")


# -- §6.5.3 annotations ------------------------------------------------


def test_an_annotation_pins_a_literal():
    program = parse("on e {\n let total: i64 = 0\n}", "t.mcs")
    analysis = analyse(program, HOME, REGISTRY)
    let = program.entries[0].body.statements[0]
    assert str(analysis.type_of(let.value)) == "i64"


def test_a_dimension_is_not_its_data_type():
    # §6.5.3: a temperature is not an i32 even where a profile holds it
    # in one, which is the same rule `if temp > 5min` enforces.
    assert "temperature where i32" in message("let x: i32 = 20°C")


def test_an_annotation_may_name_a_dimension():
    in_entry("let target: temperature = 20°C")


def test_an_unknown_type_is_refused():
    assert "not a type" in message("let x: i33 = 0")


# -- §6.3.10 crossing between a dimension and a number ------------------


def test_a_conversion_gives_a_plain_number():
    assert quantity("to_i32(sensor.temp, °C, 100)") == "i32"
    assert quantity("to_f32(sensor.temp, °C)") == "f32"
    assert quantity("to_i64(sensor.count)") == "i64"


def test_a_conversion_of_a_quantity_needs_its_unit():
    assert "which unit" in message("let n = to_i32(sensor.temp)")


def test_a_conversion_of_a_plain_number_takes_no_unit():
    assert "no unit to count in" in message("let n = to_i32(clock.hour, °C)")


def test_the_unit_must_belong_to_the_quantity():
    assert "humidity" in message("let n = to_i32(sensor.temp, %)")


def test_to_unit_builds_a_quantity():
    assert quantity("to_unit(3250, °C, 100)") == "temperature"


def test_to_unit_refuses_a_quantity():
    assert "already temperature" in message("let x = to_unit(sensor.temp, °C)")


def test_a_resolution_is_a_plain_number():
    assert "plain number" in message("let n = to_i32(sensor.temp, °C, 100°C)")


# -- §6.1.7 a date needs a calendar ------------------------------------


def test_a_date_belongs_to_the_profiles_calendar():
    assert quantity('@"2026-08-18 13:25"') == "instant"


def test_without_a_calendar_a_date_is_refused():
    assert "no calendar" in message('let x = @"2026-08-18"', NO_CALENDAR)


# -- §6.3.5 and §6.3.4 match and if ------------------------------------


def test_match_arms_agree():
    in_entry(
        "fan.speed = match sensor.temp { unavailable -> 0, > 28°C -> 3, else -> 1 }"
    )


def test_an_arm_that_disagrees_is_refused():
    assert "where the others are" in message(
        "fan.speed = match sensor.temp { > 28°C -> 3, else -> valve.open }"
    )


def test_a_match_needs_an_else():
    assert "no `else`" in message("fan.speed = match sensor.temp { > 28°C -> 3 }")


def test_a_bool_match_needs_no_else():
    in_entry("fan.speed = match valve.open { true -> 1, false -> 0 }")


def test_a_state_may_be_produced_where_the_type_is_known():
    in_entry("fan.speed = match sensor.temp { invalid -> invalid, else -> 1 }")


def test_a_state_alone_has_no_type():
    assert "which kind of value" in message("let x = invalid")


def test_a_pattern_shares_the_subjects_kind():
    assert "different kinds" in message(
        "fan.speed = match sensor.temp { > 28 -> 3, else -> 1 }"
    )


def test_if_arms_agree():
    assert "one arm is" in message(
        "fan.speed = if valve.open { 3 } else { valve.open }"
    )


def test_a_condition_is_a_yes_or_no():
    assert "yes-or-no" in message("if sensor.temp { fan.on() }")


# -- the world ----------------------------------------------------------


def test_an_unknown_name_suggests_the_nearest():
    assert "`sensor.temp`" in message("let x = sensor.tempp")


def test_a_read_only_entity_cannot_be_set():
    assert "read but not set" in message("sensor.temp = 3°C")


def test_a_write_only_entity_cannot_be_read():
    assert "set but not read" in message("let x = led.fault")


def test_a_host_function_is_called_not_read():
    assert "something to call" in message("let x = fan.on")


def test_an_argument_must_match_its_dimension():
    assert "different kinds" in message(
        "timer.after(5°C)"
    ) or "where duration" in message("timer.after(5°C)")


def test_a_call_checks_how_many():
    assert "takes 1" in message("timer.after()")


def test_a_local_may_not_shadow_an_entity():
    assert "already an entity" in message("let brightness = 1")


# -- functions ----------------------------------------------------------


def test_a_functions_parameters_come_from_its_call_site():
    analyse_source("fn double(x) { x * 2 }\non e { fan.speed = double(3) }")


def test_a_function_used_at_two_types_names_both():
    # §6.5.2: this language has no generics, and naming the two lines is
    # more useful to its audience than allowing the program.
    with pytest.raises(CompileError) as caught:
        analyse_source(
            "fn f(x) { x }\non e { fan.speed = f(3)\n setpoint.target = f(20°C) }"
        )
    assert "two different kinds" in caught.value.first.message


def test_a_function_nothing_calls_is_refused():
    with pytest.raises(CompileError) as caught:
        analyse_source("fn unused(x) { x }\non e { fan.on() }")
    assert "nothing calls" in caught.value.first.message


def test_recursion_resolves_from_the_arm_that_does_not_recurse():
    analyse_source(
        "fn countdown(n) limit 5 {\n"
        "  if n <= 0 { 0 } else { countdown(n - 1) }\n"
        "}\n"
        "on e { fan.speed = countdown(3) }"
    )


# -- planned constructs say so -----------------------------------------


@pytest.mark.parametrize(
    ("body", "word"),
    [
        ('let s = "hi"', "planned"),
        ("let a = min(1, 2)", "planned"),
        ("let x = sensor.count[0]", "planned"),
    ],
)
def test_a_planned_construct_is_named_as_one(body, word):
    assert word in message(body)


def test_break_outside_a_loop():
    assert "inside a loop" in message("break")


def test_a_loop_counts_in_whole_numbers():
    assert "whole numbers" in message("for i in 0°C..9°C { fan.on() }")
