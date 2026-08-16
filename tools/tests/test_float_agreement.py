# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0
"""Floating point, bit for bit, through both backends.

The question this file answers is whether "the two backends produce
identical results" can hold for `f32` or has to be softened to a
tolerance. It holds, and the reason is not that anyone was careful: it
is that IEEE-754 defines ``+``, ``-``, ``*`` and ``/`` as the *correctly
rounded* result of the exact mathematical operation. For a given pair of
operands and rounding mode there is exactly one right answer, and both
backends compute it on the same hardware.

What can break it is never the arithmetic. It is the compiler:
contraction into a fused multiply-add, excess precision kept in a wider
register, and ``-ffast-math``. Two of those are defended against here by
construction — the slot holds a 32-bit pattern, so every operation ends
in a store that narrows, at the same points in both backends — and the
third is a build flag the specification forbids.

A tolerance would be the wrong answer for a reason that has nothing to
do with precision: a comparison feeds a branch. One ULP of disagreement
in `temp > 25.0` is not one ULP of disagreement in the output, it is a
different arm of the ladder and a fan at a different speed. There is no
tolerance on a `bool`.

The comparison here is on the **bit pattern**, printed as hex, so
nothing hides behind a decimal rendering.
"""

from __future__ import annotations

import struct

import pytest
from harness import CONFORMING_FLAGS, PROFILE, agree, compile_once

# Values chosen to break things: the two zeroes, both infinities, a
# quiet NaN, the largest and smallest normals, the smallest subnormal,
# a value one ULP away from another, and a few ordinary numbers.
NOTABLE = [
    ("+0", "0x00000000"),
    ("-0", "0x80000000"),
    ("+inf", "0x7F800000"),
    ("-inf", "0xFF800000"),
    ("qNaN", "0x7FC00000"),
    ("max normal", "0x7F7FFFFF"),
    ("min normal", "0x00800000"),
    ("min subnormal", "0x00000001"),
    ("1.0", "0x3F800000"),
    ("1.0 + 1 ULP", "0x3F800001"),
    ("0.1", "0x3DCCCCCD"),
    ("-2.5", "0xC0200000"),
    ("16777217 unrepresentable", "0x4B800000"),
]

IDS = [name for name, _ in NOTABLE]
BITS = [bits for _, bits in NOTABLE]


def _program(operation: str) -> str:
    return (
        PROFILE
        + ".entity read f32 a dim 1\n"
        + ".entity read f32 b dim 1\n"
        + ".entry go -> f32\n"
        + f"  load.h a\n  load.h b\n  {operation}\n  ret_v\n"
    )


def _host(a: str, b: str) -> str:
    return f"entity read f32 a dim 1 = {a}\nentity read f32 b dim 1 = {b}\n"


@pytest.mark.parametrize("operation", ["add.f32", "sub.f32", "mul.f32", "div.f32"])
def test_every_pair_of_notable_values_agrees_bit_for_bit(vm, cc, tmp_path, operation):
    """13 × 13 = 169 pairs per operation, compared as bit patterns.

    Nothing here is asserted to be a particular number. The assertion is
    that the interpreter and the compiled C produce the same bits, which
    is the property the project promised. The program is compiled once
    and fed 169 different worlds, because compiling per pair cost seven
    minutes.
    """
    program = compile_once(vm, cc, tmp_path, _program(operation))
    for a in BITS:
        for b in BITS:
            interpreted, compiled = program(_host(a, b))
            assert interpreted.output == compiled.output, (
                f"{operation} disagrees on {a} and {b}: "
                f"{interpreted.output!r} vs {compiled.output!r}"
            )


@pytest.mark.parametrize("comparison", ["eq.f32", "ne.f32", "lt.f32", "gt.f32"])
@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("0x7FC00000", "0x3F800000"),  # NaN against a number
        ("0x7FC00000", "0x7FC00000"),  # NaN against itself
        ("0x00000000", "0x80000000"),  # +0 == -0
        ("0x7F800000", "0x7F800000"),  # inf == inf
        ("0x3F800000", "0x3F800001"),  # one ULP apart
    ],
)
def test_ieee_comparison_agrees(vm, cc, tmp_path, comparison, a, b):
    """NaN makes every comparison false except `ne`, and `+0 == -0` is
    true although the bits differ. Both are IEEE-754 rules a naive
    backend gets wrong in opposite directions."""
    source = (
        PROFILE
        + ".entity read f32 a dim 1\n"
        + ".entity read f32 b dim 1\n"
        + ".entry go -> bool\n"
        + f"  load.h a\n  load.h b\n  {comparison}\n  ret_v\n"
    )
    agree(vm, cc, tmp_path, source, _host(a, b))


def test_nan_is_a_valid_value_and_not_the_invalid_state(vm, cc, tmp_path):
    """§1.5: conflating them would lose the distinction the state model
    exists for. A NaN is a number the script produced; `invalid` is the
    world saying the reading must not be used."""
    result = agree(
        vm,
        cc,
        tmp_path,
        _program("div.f32"),
        _host("0x00000000", "0x00000000"),  # 0.0 / 0.0
    )
    assert "nan" in result.output.lower()
    assert "valid" in result.output and "invalid" not in result.output


def test_float_division_by_zero_is_an_infinity_not_the_invalid_state(vm, cc, tmp_path):
    # Unlike integer division (§3.5): IEEE-754 has a defined answer and
    # integers do not.
    result = agree(vm, cc, tmp_path, _program("div.f32"), _host("1.0", "0x00000000"))
    assert "inf" in result.output
    assert "invalid" not in result.output


def test_conversion_to_integer_agrees(vm, cc, tmp_path):
    """The one C leaves undefined. A bare cast of an out-of-range float
    is undefined behaviour, so the two backends would diverge on exactly
    the input a faulty sensor produces; both go through the same range
    test instead, and the result is `invalid`."""
    source = (
        PROFILE
        + ".entity read f32 a dim 1\n"
        + ".entry go -> i32\n  load.h a\n  trunc.f32_i32\n  ret_v\n"
    )
    program = compile_once(vm, cc, tmp_path, source)
    for bits in BITS:
        program.agree(f"entity read f32 a dim 1 = {bits}\n")


@pytest.mark.parametrize(
    "value", [0, 1, -1, 16777216, 16777217, 2147483647, -2147483648]
)
def test_conversion_from_integer_agrees(vm, cc, tmp_path, value):
    """16777217 has no `f32`, so the conversion rounds; 2147483647
    rounds *up* to 2147483648, which is outside the integer range it
    came from."""
    source = (
        PROFILE
        + f".const n i32 {value}\n"
        + ".entry go -> f32\n  const.i32 n\n  convert.i32_f32\n  ret_v\n"
    )
    agree(vm, cc, tmp_path, source)


def test_a_float_constant_survives_as_bits(vm, cc, tmp_path):
    """The generated C emits the pool entry as a hex bit pattern rather
    than a decimal literal, so the C compiler is never asked to re-round
    a number the container already rounded."""
    from mcuscript.asm import assemble
    from mcuscript.cbackend import generate

    source = PROFILE + ".const x f32 0.1\n.entry go -> f32\n  const.f32 x\n  ret_v\n"
    text = generate(assemble(source))
    bits = struct.unpack("<I", struct.pack("<f", 0.1))[0]
    assert f"0x{bits:08X}u" in text
    agree(vm, cc, tmp_path, source)


def test_a_chain_of_operations_agrees(vm, cc, tmp_path):
    """`a*b + c` is the expression that contracts into a fused
    multiply-add when a compiler is allowed to, which changes the result
    by one rounding. Both backends store the product to a slot before
    adding, so there is nothing left to contract."""
    source = (
        PROFILE
        + ".entity read f32 a dim 1\n"
        + ".entity read f32 b dim 1\n"
        + ".entity read f32 c dim 1\n"
        + ".entry go -> f32\n"
        + "  load.h a\n  load.h b\n  mul.f32\n  load.h c\n  add.f32\n  ret_v\n"
    )
    host = (
        "entity read f32 a dim 1 = 0.1\n"
        "entity read f32 b dim 1 = 0.2\n"
        "entity read f32 c dim 1 = 0.3\n"
    )
    agree(vm, cc, tmp_path, source, host)


def test_a_float_comparison_that_feeds_a_branch_agrees(vm, cc, tmp_path):
    """Why a tolerance would be the wrong rule: this is where one ULP
    stops being one ULP. The two operands differ in the last bit, the
    comparison decides which arm runs, and the outputs are 1 and 0 —
    not 1 and 1.0000001."""
    source = (
        PROFILE
        + ".entity read f32 a dim 1\n"
        + ".entity read f32 b dim 1\n"
        + ".entry go -> i32\n"
        + "  load.h a\n  load.h b\n  gt.f32\n  jmp_if_false low\n"
        + "  const.i32.s8 1\n  ret_v\nlow:\n  const.i32.s8 0\n  ret_v\n"
    )
    agree(vm, cc, tmp_path, source, _host("0x3F800001", "0x3F800000"))


# -- i64, while we are here ------------------------------------------------


I64_EDGES = [
    "0",
    "1",
    "-1",
    "9223372036854775807",
    "-9223372036854775808",
    "4294967296",
    "-4294967296",
]


@pytest.mark.parametrize(
    "operation", ["add.i64", "sub.i64", "mul.i64", "div.i64", "rem.i64"]
)
def test_i64_arithmetic_agrees(vm, cc, tmp_path, operation):
    source = (
        PROFILE
        + ".entity read i64 a dim 1\n"
        + ".entity read i64 b dim 1\n"
        + f".entry go -> i64\n  load.h a\n  load.h b\n  {operation}\n  ret_v\n"
    )
    program = compile_once(vm, cc, tmp_path, source)
    for a in I64_EDGES:
        for b in I64_EDGES:
            host = f"entity read i64 a dim 1 = {a}\nentity read i64 b dim 1 = {b}\n"
            interpreted, compiled = program(host)
            assert interpreted.output == compiled.output, f"{operation}: {a}, {b}"


@pytest.mark.parametrize("value", [0, 1, -1, 2147483647, -2147483648])
def test_widening_and_narrowing_agree(vm, cc, tmp_path, value):
    """`wrap` truncates silently rather than producing `invalid`: it is
    the explicit "I want the low half" operation (§3.4)."""
    source = (
        PROFILE
        + f".const n i32 {value}\n"
        + ".entry go -> i32\n"
        + "  const.i32 n\n  extend.i32_i64\n  wrap.i64_i32\n  ret_v\n"
    )
    result = agree(vm, cc, tmp_path, source)
    assert str(value) in result.output


# -- the flags are load-bearing -------------------------------------------


FMA_TRAP = (
    PROFILE
    + ".entity read f32 a dim 1\n"
    + ".entity read f32 b dim 1\n"
    + ".entity read f32 c dim 1\n"
    + ".entry go -> f32\n"
    + "  load.h a\n  load.h b\n  mul.f32\n  load.h c\n  add.f32\n  ret_v\n"
)

FMA_HOST = (
    "entity read f32 a dim 1 = 1e20\n"
    "entity read f32 b dim 1 = 1e20\n"
    "entity read f32 c dim 1 = 0xFF800000\n"  # -inf
)


def _has_fma(cc, tmp_path) -> bool:
    import subprocess

    probe = tmp_path / "probe.c"
    probe.write_text("int main(void) { return 0; }\n")
    return (
        subprocess.run(
            [cc, "-mfma", str(probe), "-o", str(tmp_path / "probe")],
            capture_output=True,
        ).returncode
        == 0
    )


def test_the_required_build_flags_are_not_decoration(vm, cc, tmp_path):
    """The one test in this repository that asserts a **disagreement**.

    `-ffp-contract=off` is a requirement the specification states and
    that nothing would notice the absence of, because the default build
    happens to be safe. So this compiles the same program the way a
    careless build would — GCC's default under `-std=gnu*`, on hardware
    that has an FMA — and asserts the backends come apart.

    `1e20 * 1e20` overflows to infinity, and `inf + -inf` is NaN. Fused,
    there is no intermediate to overflow and the answer is -inf. Not a
    last-digit difference: a different kind of number. If this ever
    starts agreeing, either the guard became unnecessary or the hardware
    changed, and either way the requirement needs re-reading.
    """
    if not _has_fma(cc, tmp_path):
        pytest.skip("this target has no -mfma")

    safe_dir = tmp_path / "safe"
    safe_dir.mkdir()
    compile_once(vm, cc, safe_dir, FMA_TRAP, flags=[*CONFORMING_FLAGS, "-mfma"]).agree(
        FMA_HOST
    )

    careless_dir = tmp_path / "careless"
    careless_dir.mkdir()
    careless = compile_once(
        vm, cc, careless_dir, FMA_TRAP, flags=["-std=gnu99", "-O2", "-mfma"]
    )
    interpreted, compiled = careless(FMA_HOST)
    assert interpreted.output != compiled.output, (
        "the careless build agreed; -ffp-contract=off may no longer be "
        "the thing that matters"
    )
    assert "0xffc00000" in interpreted.output  # NaN
    assert "0xff800000" in compiled.output  # -inf
