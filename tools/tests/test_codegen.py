# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0
"""A script becomes a container, and the container runs the same both ways.

Two kinds of test, and the second is the point. The structural ones say
what the compiler emitted, because a lowering that verifies is not
necessarily the lowering that was meant. The differential ones compile a
script, run the container on the VM and as generated C, and compare the
output byte for byte — which is the project's promise applied one level
higher than it used to reach: it used to say that two backends agree
about a container, and it now says they agree about a **script**.

Every container here goes through `mcuscript.verify` on the way out, so
"it compiled" already means "a loader would accept it".
"""

from __future__ import annotations

import pytest
from harness import agree, compile_once
from homeprofile import HOME, REGISTRY

from mcuscript.asm import disassemble
from mcuscript.codegen import generate
from mcuscript.container import Container, ImportKind
from mcuscript.diagnostics import CompileError
from mcuscript.opcodes import ValType, group_names
from mcuscript.parser import parse
from mcuscript.sema import analyse


def build(source: str, *, entry_name: str = "main") -> Container:
    program = parse(source, "test.mcs")
    analysis = analyse(program, HOME, REGISTRY)
    return generate(program, analysis, HOME, REGISTRY, entry_name=entry_name)


def refusal(source: str) -> str:
    with pytest.raises(CompileError) as caught:
        build(source)
    return caught.value.diagnostics[0].message


# -- what the compiler emits -----------------------------------------------


WORKED_EXAMPLE = """
on temperature_changed {
    fan.speed = match sensor.temp {
        unavailable -> 0
        > 28°C      -> 3
        > 25°C      -> 2
        else        -> 0
    }
}
"""


def test_the_worked_example_of_the_specification():
    """§3.9 written as a script rather than as assembler.

    The instruction sequence is the chapter's, with one thing the
    chapter's hand-written version left out: the `unavailable` arm, which
    is the reason a `match` reads its subject into a slot instead of
    twice from the host.
    """
    container = build(WORKED_EXAMPLE)
    text = disassemble(container)
    assert "const.i32.s16 2800" in text
    assert "const.i32.s16 2500" in text
    assert "is_unavailable" in text
    assert "store.h fan.speed" in text
    # The subject is read once, however many arms test it.
    assert text.count("load.h sensor.temp") == 1


def test_a_match_that_names_no_arm_for_a_state_yields_that_state():
    """The propagation of §6.3.5, and what the two constants are for."""
    text = disassemble(build(WORKED_EXAMPLE))
    # `unavailable` has an arm; `invalid` does not, so the match yields
    # it — as a value, of the arms' type.
    assert "const.invalid i32" in text
    assert "const.unavailable" not in text


def test_a_file_that_is_only_an_expression_is_a_program():
    """§6.2.2, including the name a producer supplies."""
    container = build("(to_f32(sensor.temp, °C) - 32) / 1.8\n", entry_name="fahrenheit")
    assert [f.name for f in container.functions] == ["fahrenheit"]
    assert container.functions[0].invocable
    assert container.functions[0].return_type is ValType.F32


def test_an_entry_point_that_writes_and_yields_nothing():
    container = build("on go { fan.on() }\n")
    assert container.functions[0].return_type is ValType.VOID
    assert disassemble(container).rstrip().endswith("ret")


def test_imports_appear_once_in_first_use_order():
    container = build(
        "on go {\n"
        "  fan.speed = sensor.count\n"
        "  setpoint.target = sensor.temp\n"
        "  fan.speed = sensor.count\n"
        "}\n"
    )
    assert [i.name for i in container.imports] == [
        "sensor.count",
        "fan.speed",
        "sensor.temp",
        "setpoint.target",
    ]


def test_an_import_carries_the_access_and_dimension_the_registry_declared():
    container = build("on go { setpoint.target = sensor.temp }\n")
    read = next(i for i in container.imports if i.name == "sensor.temp")
    write = next(i for i in container.imports if i.name == "setpoint.target")
    assert read.kind == ImportKind.ENTITY
    assert (read.access, write.access) == (0x01, 0x03)
    # Both are temperatures, and the container records the dimension so
    # that a host disagreeing about it is caught at load (§4.5).
    assert (read.dimension, write.dimension) == (1, 1)


def test_a_host_function_import_carries_its_signature():
    container = build("on go { timer.after(5s) }\n")
    imported = container.imports[0]
    assert imported.kind == ImportKind.FUNCTION
    assert imported.param_types == (ValType.I32,)
    assert imported.type is ValType.VOID


def test_a_literal_is_normalized_to_base_units_at_compile_time():
    """`24.5°C` is 2450 hundredths, and no unit survives (§1.4)."""
    assert "const.i32.s16 2450" in disassemble(
        build("on go { setpoint.target = 24.5°C }\n")
    )


def test_small_numbers_use_the_short_form_and_large_ones_the_pool():
    text = disassemble(build("on go { fan.speed = 7 }\n"))
    assert "const.i32.s8 7" in text
    container = build("on go { fan.speed = 100000 }\n")
    assert container.constants[0].value == 100000
    assert "const.i32 " in disassemble(container)


def test_one_constant_is_pooled_once():
    container = build("on go { fan.speed = 100000 + 100000 }\n")
    assert len(container.constants) == 1


def test_a_loop_carries_the_bound_of_its_range():
    """§6.4.4: the counter is `b - a + 1` and the body does not touch it."""
    text = disassemble(build("on go {\n  for i in 0..9 { fan.on() }\n}\n"))
    assert "loop.guard" in text
    guard = next(line for line in text.splitlines() if "loop.guard" in line)
    counter = guard.split()[-1]
    # Written before the loop and never again — which is what makes the
    # cycle conforming (§3.8.1).
    assert text.count(f"store.l {counter}") == 1


def test_a_recursion_limit_reaches_every_function_of_its_cycle():
    """§6.2.4 lets `limit` stand on any one of them; §4.3 wants it on all."""
    container = build(
        "fn down(n) limit 5 {\n"
        "  if n <= 0 { return 0 }\n"
        "  return up(n - 1)\n"
        "}\n"
        "fn up(n) { down(n) }\n"
        "on go { fan.speed = down(3) }\n"
    )
    caps = {f.name: f.recursion_cap for f in container.functions}
    assert caps == {"go": 0, "down": 5, "up": 5}


#: The shapes a recursive function's base case comes in. It is as often
#: an arm of an `if` or a `match` as it is a `return`, and the arm that
#: recurses may come first — in which case the pass unwinds before the
#: base case was ever read, and has to go back for it.
RECURSIVE = {
    "a return": "if n <= 0 { return 0 }\n  return f(n - 1) + 1",
    "if arms": "if n <= 0 { 0 } else { f(n - 1) + 1 }",
    "if arms, recursion first": "if n > 0 { f(n - 1) + 1 } else { 0 }",
    "match arms": "match n { <= 0 -> 0, else -> f(n - 1) + 1 }",
    "match arms, recursion first": "match n { > 0 -> f(n - 1) + 1, else -> 0 }",
}


@pytest.mark.parametrize("body", RECURSIVE.values(), ids=list(RECURSIVE))
def test_a_recursive_function_finds_its_base_case(body):
    container = build(f"fn f(n) limit 5 {{\n  {body}\n}}\non go {{ return f(3) }}\n")
    assert container.functions[1].return_type is ValType.I32


def test_a_recursion_with_no_way_out_is_refused():
    assert "no way out" in refusal(
        "fn f(n) limit 5 { f(n - 1) + 1 }\non go { return f(3) }\n"
    )


def test_a_limit_on_something_that_cannot_repeat_is_refused():
    assert "cannot repeat" in refusal(
        "fn twice(x) limit 5 { x * 2 }\non go { fan.speed = twice(2) }\n"
    )


MUTUAL = """
fn a(n){first} {{
  if n <= 0 {{ return 0 }}
  return b(n - 1)
}}
fn b(n){second} {{ a(n) }}
on go {{ fan.speed = a(3) }}
"""


def test_a_cycle_without_a_limit_is_refused_naming_the_functions():
    message = refusal(MUTUAL.format(first="", second=""))
    assert "`a`" in message and "`b`" in message and "circle" in message


def test_two_limits_in_one_cycle_are_refused_naming_both():
    message = refusal(MUTUAL.format(first=" limit 3", second=" limit 4"))
    assert "`a`" in message and "`b`" in message


def test_a_limit_on_either_function_of_a_cycle_covers_both():
    """§6.2.4: the declaration may stand on any one of them."""
    for shape in (
        {"first": " limit 4", "second": ""},
        {"first": "", "second": " limit 4"},
    ):
        container = build(MUTUAL.format(**shape))
        assert {f.recursion_cap for f in container.functions if f.name != "go"} == {4}


# -- what it refuses --------------------------------------------------------


def test_a_date_has_no_number_to_compile_to():
    """The one construct the front end types and cannot lower.

    What `@"…"` counts from is an epoch, and an epoch belongs to the
    profile format — so this refusal is a statement about what is built,
    not about the script.
    """
    assert "date" in refusal('on go {\n  let t: instant = @"2026-08-19 13:25"\n}\n')


@pytest.mark.parametrize(
    ("script", "groups"),
    [
        ("on go {\n  let big: i64 = 5\n  return to_f32(big)\n}\n", "i64"),
        ("on go { return to_i64(1.5) }\n", "i64"),
        # Two 64-bit numbers divided are a decimal (§6.5.5), which is the
        # case that has no way around the conversion.
        ("on go {\n  let a: i64 = 7\n  let b: i64 = 2\n  return a / b\n}\n", "i64"),
    ],
)
def test_a_64_bit_number_and_a_decimal_convert_both_ways(script, groups):
    """§3.5's pair, and why it is not optional.

    A profile chooses a dimension's data type, so a quantity may be held
    in an `i64`; a script that divides two of those has a decimal
    whatever anybody prefers. The container declares **both** groups for
    it, because the instruction sits in `float` and touches a type only
    `i64` produces (§3.2).
    """
    container = build(script)
    names = group_names(container.required_groups)
    assert "float" in names and groups in names


def test_bitwise_operations_stay_32_bit():
    message = refusal(
        "on go {\n  let big: i64 = 5\n  fan.speed = to_i32(big & big)\n}\n"
    )
    assert "32-bit" in message


# -- from a shell ------------------------------------------------------------


def test_the_command_compiles_a_file(tmp_path, capsys):
    """`mcuscript build`, which has no profile and no registry yet.

    A world that declares neither is legal (§6.5.4) and is what the
    command compiles against until a profile can be named, so what it
    takes is a script of plain numbers — and what it proves is that the
    pipeline reaches a file from a shell.
    """
    from mcuscript.cli import main

    script = tmp_path / "fahrenheit.mcs"
    script.write_text("(212 - 32) * 5 / 9\n", encoding="utf-8")
    out = tmp_path / "fahrenheit.mcsb"
    assert main(["build", str(script), "-o", str(out)]) == 0
    assert "1 function(s)" in capsys.readouterr().out

    container = Container.decode(out.read_bytes())
    # The entry point takes its name from the file, which is what §6.2.2
    # means by a producer supplying it.
    assert [f.name for f in container.functions] == ["fahrenheit"]
    assert container.functions[0].return_type is ValType.F32


def test_the_command_reports_a_bad_script_and_stops(tmp_path, capsys):
    from mcuscript.cli import main

    script = tmp_path / "bad.mcs"
    script.write_text("on go { 1 + true }\n", encoding="utf-8")
    assert main(["build", str(script), "-o", str(tmp_path / "out.mcsb")]) == 2
    error = capsys.readouterr().err
    assert "bad.mcs:1" in error and "yes-or-no" in error
    assert not (tmp_path / "out.mcsb").exists()


def test_a_unit_without_a_profile_says_so(tmp_path, capsys):
    from mcuscript.cli import main

    script = tmp_path / "warm.mcs"
    script.write_text("25°C\n", encoding="utf-8")
    assert main(["build", str(script), "-o", str(tmp_path / "out.mcsb")]) == 2
    assert "declares units" in capsys.readouterr().err


# -- the same script, both backends -----------------------------------------


HOST = (
    "entity read i32 sensor.temp dim 1 = {temp}\n"
    "entity read i32 sensor.outside dim 1 = 2000\n"
    "entity read i32 sensor.humidity dim 2 = 550\n"
    "entity read i32 sensor.count dim 0 = 7\n"
    "entity read i32 clock.hour dim 0 = 13\n"
    "entity rw i32 fan.speed dim 0\n"
    "entity rw bool valve.open dim 0\n"
    "entity rw bool state.latch dim 0\n"
    "entity rw i32 setpoint.target dim 1\n"
    "entity rw i32 brightness dim 0\n"
    # Two moments either side of the `i32` wrap: the second is a second
    # after the first, and a plain comparison would say the opposite.
    "entity read i32 timer.started dim 6 = 2147483000\n"
    "entity read i32 timer.expires dim 6 = -2147483296\n"
    "function void fan.on\n"
    "function void timer.after i32\n"
)

SCRIPTS = {
    "the worked example": WORKED_EXAMPLE,
    "a formula": "(to_f32(sensor.temp, °C) - 32) / 1.8\n",
    "an if used for its value": (
        "on go { fan.speed = if sensor.temp > 25°C { 3 } else { 0 } }\n"
    ),
    "a fallback for an absent reading": (
        "on go { fan.speed = if sensor.temp else 20°C > 25°C { 3 } else { 0 } }\n"
    ),
    "a validity test": "on go { valve.open = sensor.temp is valid }\n",
    "locals and assignment": (
        "on go {\n  let t = sensor.temp\n  t = t + 1°C\n  setpoint.target = t\n}\n"
    ),
    "compound assignment": "on go {\n  let n = 1\n  n += 3\n  fan.speed = n\n}\n",
    "a loop": (
        "on go {\n  let n = 0\n  for i in 0..9 { n = n + i }\n  fan.speed = n\n}\n"
    ),
    "break and continue": (
        "on go {\n"
        "  let n = 0\n"
        "  for i in 0..9 {\n"
        "    if i == 3 { continue }\n"
        "    if i == 7 { break }\n"
        "    n = n + i\n"
        "  }\n"
        "  fan.speed = n\n"
        "}\n"
    ),
    "a function": (
        "fn double(x) { x * 2 }\non go { fan.speed = double(sensor.count) }\n"
    ),
    "capped recursion": (
        "fn down(n) limit 5 {\n"
        "  if n <= 0 { return 0 }\n"
        "  return down(n - 1) + n\n"
        "}\n"
        "on go { fan.speed = down(3) }\n"
    ),
    "a host call": "on go { timer.after(5s) }\n",
    "a duration in parts": "on go { timer.after(1min 30s) }\n",
    "a relative change": "on go { setpoint.target = sensor.temp + 5pct }\n",
    "a scale factor": "on go { setpoint.target = sensor.temp * 50pct }\n",
    "two temperatures divided": (
        "on go { valve.open = sensor.temp / sensor.outside > 0.8 }\n"
    ),
    "a conversion with a resolution": (
        "on go { fan.speed = to_i32(sensor.temp, °C, 100) }\n"
    ),
    "a conversion that rounds": "on go { fan.speed = to_i32(sensor.temp, °C) }\n",
    "a number becoming a quantity": (
        "on go { setpoint.target = to_unit(3250, °C, 100) }\n"
    ),
    "bitwise": "on go { fan.speed = (sensor.count & 3) | 4 }\n",
    "a range pattern": (
        "on go { fan.speed = match sensor.temp { 24..28°C -> 2, else -> 0 } }\n"
    ),
    "a match on a yes-or-no": (
        "on go { fan.speed = match valve.open { true -> 1, false -> 0 } }\n"
    ),
    "remainder": "on go { fan.speed = sensor.count mod 4 }\n",
    "absolute value": "on go { fan.speed = abs(0 - sensor.count) }\n",
    "the boolean operators": (
        "on go { valve.open = not (sensor.temp > 25°C and sensor.humidity > 60%) }\n"
    ),
    "a state a script chose": (
        "on go { fan.speed = match sensor.temp { invalid -> invalid, else -> 1 } }\n"
    ),
    "equality on two yes-or-nos": (
        "on go { valve.open = state.latch == (sensor.temp > 25°C) }\n"
    ),
}


@pytest.mark.parametrize("script", SCRIPTS.values(), ids=list(SCRIPTS))
def test_a_compiled_script_runs_the_same_in_both_backends(vm, cc, tmp_path, script):
    """The promise, one level up: a script, not a container.

    Four worlds per script — a reading, a cold sensor, a faulted one and
    a value that is not a round number — because validity is where a
    lowering that looks right goes wrong, and because a compiler is free
    to be wrong in ways an assembler could not be.
    """
    program = compile_once(vm, cc, tmp_path, build(script))
    for reading in ("2650", "unavailable", "invalid", "2455"):
        program.agree(HOST.format(temp=reading))


#: Scripts with the answer they owe. The differential test above cannot
#: catch a compiler that is wrong, because both backends read the same
#: container and a wrong one is identically wrong in each — agreement is
#: a property of the backends, and these are the property of the
#: compiler.
ANSWERS = {
    "a loop sums its range": (
        "on go {\n  let n = 0\n  for i in 0..9 { n = n + i }\n  return n\n}\n",
        ("i32", "45", "valid"),
    ),
    "break and continue skip and stop": (
        "on go {\n"
        "  let n = 0\n"
        "  for i in 0..9 {\n"
        "    if i == 3 { continue }\n"
        "    if i == 7 { break }\n"
        "    n = n + i\n"
        "  }\n"
        "  return n\n"
        "}\n",
        ("i32", "18", "valid"),
    ),
    "recursion adds up": (
        "fn down(n) limit 5 {\n"
        "  if n <= 0 { return 0 }\n"
        "  return down(n - 1) + n\n"
        "}\n"
        "on go { return down(3) }\n",
        ("i32", "6", "valid"),
    ),
    "a conversion into the profile's own base unit": (
        # `c°C` starts with a letter and contains `°`, which is the
        # shape a fine base unit has and the one the lexer has to keep
        # in one piece (§6.1.5).
        "on go { return to_i32(sensor.temp, c°C) }\n",
        ("i32", "2650", "valid"),
    ),
    "a conversion to a decimal keeps the fraction": (
        # 2650 hundredths is 26.5 °C, and §6.3.10 says `to_f32` rounds
        # nothing at all — so the scaling happens in decimals and not in
        # whole numbers, where it would hand back 26.
        "on go { return to_f32(sensor.temp, °C) }\n",
        ("f32", "0x41d40000(26.5)", "valid"),
    ),
    "a unit with an offset": (
        # 26.5 °C is 79.7 °F, rounded away from zero. The offset is
        # -16000/9 base units, which is why the conversion is one exact
        # rational and not a subtraction the compiler could not write.
        "on go { return to_i32(sensor.temp, °F) }\n",
        ("i32", "80", "valid"),
    ),
    "a conversion counts in the resolution asked for": (
        "on go { return to_i32(sensor.temp, °C, 100) }\n",
        ("i32", "2650", "valid"),
    ),
    "a conversion rounds away from zero": (
        # 26.5 °C, and §6.3.10 rounds the tie away from zero.
        "on go { return to_i32(sensor.temp, °C) }\n",
        ("i32", "27", "valid"),
    ),
    "a relative change is a multiplication": (
        # 26.50 °C plus five percent is 27.825, truncated to the
        # profile's hundredths.
        "on go { return to_i32(sensor.temp + 5pct, c°C) }\n",
        ("i32", "2782", "valid"),
    ),
    "a scale factor scales": (
        "on go { return to_i32(sensor.temp * 50pct, c°C) }\n",
        ("i32", "1325", "valid"),
    ),
    "remainder": ("on go { return sensor.count mod 4 }\n", ("i32", "3", "valid")),
    "absolute value": (
        "on go { return abs(0 - sensor.count) }\n",
        ("i32", "7", "valid"),
    ),
    "a range pattern is inclusive at both ends": (
        "on go { return match sensor.temp { 24..28°C -> 2, else -> 0 } }\n",
        ("i32", "2", "valid"),
    ),
    "a match propagates a state no arm names": (
        "on go { return match sensor.humidity { > 90% -> 1, else -> 0 } }\n",
        ("i32", "0", "valid"),
    ),
    "equality on two yes-or-nos": (
        "on go { return (sensor.temp > 25°C) == (sensor.count > 3) }\n",
        ("bool", "true", "valid"),
    ),
    "the boolean operators do not short-circuit": (
        # The humidity reading is there; the point is that both operands
        # are evaluated and the answer is the honest one.
        "on go { return sensor.temp > 25°C and sensor.humidity > 60% }\n",
        ("bool", "false", "valid"),
    ),
    "a 64-bit number as a decimal": (
        "on go {\n  let a: i64 = 7\n  let b: i64 = 2\n  return a / b }\n",
        ("f32", "0x40600000(3.5)", "valid"),
    ),
    "a decimal as a 64-bit number": (
        "on go { return to_i64(2.5) }\n",
        ("i64", "3", "valid"),
    ),
    "a comparison across the wrap": (
        # §6.5.6: the difference against zero, so a moment a second
        # after another still compares as later even though the counter
        # wrapped in between.
        "on go { return timer.started < timer.expires }\n",
        ("bool", "true", "valid"),
    ),
}


#: What a built-in owes when its operand is not there. §6.3.9: "a
#: built-in propagates validity like an operator — `abs(temp)` with an
#: unread sensor is `unavailable`, not a fault — so a lowering that
#: branches on the operand is wrong even where it is obvious."
ABSENT = {
    "abs carries an absent reading": "on go { return abs(sensor.temp) }\n",
    "a rounding conversion carries one": ("on go { return to_i32(sensor.temp, °C) }\n"),
    "a conversion with an offset carries one": (
        "on go { return to_i32(sensor.temp, °F) }\n"
    ),
    "round carries one": ("on go { return round(to_f32(sensor.temp, °C)) }\n"),
}


@pytest.mark.parametrize("script", ABSENT.values(), ids=list(ABSENT))
@pytest.mark.parametrize("state", ["unavailable", "invalid"])
def test_a_builtin_propagates_a_state_rather_than_faulting(
    vm, cc, tmp_path, script, state
):
    run = agree(vm, cc, tmp_path, build(script), HOST.format(temp=state))
    assert "fault" not in run.output, run.output
    assert run.output.split()[3] == state


@pytest.mark.parametrize(("script", "expected"), ANSWERS.values(), ids=list(ANSWERS))
def test_a_compiled_script_computes_what_it_owes(vm, cc, tmp_path, script, expected):
    run = agree(vm, cc, tmp_path, build(script), HOST.format(temp="2650"))
    assert tuple(run.output.split()[1:4]) == expected


def test_a_compiled_script_computes_what_it_says(vm, cc, tmp_path):
    """One end-to-end number, because agreement alone would not catch
    two backends being identically wrong about the same script."""
    run = agree(
        vm,
        cc,
        tmp_path,
        build(WORKED_EXAMPLE),
        HOST.format(temp="2650"),
    )
    assert run.output.splitlines()[0] == "write fan.speed 2 valid"


def test_a_formula_answers_in_the_unit_it_was_written_in(vm, cc, tmp_path):
    run = agree(
        vm,
        cc,
        tmp_path,
        build("(to_f32(sensor.temp, °C) - 32) / 1.8\n"),
        HOST.format(temp="10000"),
    )
    # 100 °C is 212 °F, and the script asked in °C rather than in the
    # profile's hundredths — which is the point of §6.3.10. The runner
    # prints an `f32` as its bits and then as a number.
    assert "(37.7777786)" in run.output
