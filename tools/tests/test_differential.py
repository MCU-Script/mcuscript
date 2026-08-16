# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0
"""The differential test: the two backends, on the same program.

Every program has two lowerings and must have both, and they must
produce identical results. This is where that stops being a claim.

The same container goes to the VM and to the C backend; the C is
compiled against the same host description and prints through the same
code; and the test asserts that the two outputs are **byte-identical**
— not that each matches an expected string. Writing expectations down
would test the expectations. Comparing the backends tests the promise.

Floating point gets its own module, `test_float_agreement.py`, because
that is where the promise was most in doubt.
"""

from __future__ import annotations

import pytest
from harness import PROFILE, agree, both  # noqa: F401

from mcuscript.asm import assemble
from mcuscript.cbackend import UnsupportedProgram, generate

# -- arithmetic -----------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        "  const.i32.s8 2\n  const.i32.s8 3\n  add.i32\n  ret_v\n",
        "  const.i32.s8 2\n  const.i32.s8 3\n  sub.i32\n  ret_v\n",
        "  const.i32.s8 -7\n  const.i32.s8 2\n  div.i32\n  ret_v\n",
        "  const.i32.s8 -7\n  const.i32.s8 2\n  rem.i32\n  ret_v\n",
        "  const.i32.s8 7\n  const.i32.s8 0\n  div.i32\n  ret_v\n",
        "  const.i32.s8 7\n  const.i32.s8 0\n  rem.i32\n  ret_v\n",
        "  const.i32.s8 100\n  const.i32.s8 100\n  mul.i32\n  ret_v\n",
        "  const.i32.s8 5\n  neg.i32\n  ret_v\n",
        "  const.i32.s8 5\n  dup\n  mul.i32\n  ret_v\n",
    ],
)
def test_arithmetic_agrees(vm, cc, tmp_path, body):
    agree(vm, cc, tmp_path, PROFILE + ".entry go -> i32\n" + body)


@pytest.mark.parametrize("value", ["2147483647", "-2147483648"])
def test_the_extremes_agree(vm, cc, tmp_path, value):
    """`INT32_MIN` is the one that catches a lazy backend twice over: it
    has no negative literal in C, and dividing it by -1 is the case §1.5
    calls `invalid`."""
    source = (
        PROFILE
        + f".const edge i32 {value}\n"
        + ".entry go -> i32\n"
        + "  const.i32 edge\n  const.i32.s8 -1\n  div.i32\n  ret_v\n"
    )
    agree(vm, cc, tmp_path, source)


def test_wrapping_agrees(vm, cc, tmp_path):
    source = (
        PROFILE
        + ".const big i32 2147483647\n"
        + ".entry go -> i32\n"
        + "  const.i32 big\n  const.i32.s8 1\n  add.i32\n  ret_v\n"
    )
    result = agree(vm, cc, tmp_path, source)
    assert "-2147483648" in result.output


@pytest.mark.parametrize(
    "comparison", ["eq.i32", "ne.i32", "lt.i32", "le.i32", "gt.i32", "ge.i32"]
)
@pytest.mark.parametrize(("a", "b"), [(1, 2), (2, 2), (3, 2), (-1, 1)])
def test_every_comparison_agrees(vm, cc, tmp_path, comparison, a, b):
    source = (
        PROFILE
        + ".entry go -> bool\n"
        + f"  const.i32.s8 {a}\n  const.i32.s8 {b}\n  {comparison}\n  ret_v\n"
    )
    agree(vm, cc, tmp_path, source)


def test_not_agrees(vm, cc, tmp_path):
    agree(
        vm, cc, tmp_path, PROFILE + ".entry go -> bool\n  const.true\n  not\n  ret_v\n"
    )


# -- validity -------------------------------------------------------------


ABSENT_HOST = "entity read i32 a dim 1 {}\nentity read i32 b dim 1 {}\n"


@pytest.mark.parametrize("a", ["= 5", "= unavailable", "= invalid"])
@pytest.mark.parametrize("b", ["= 7", "= unavailable", "= invalid"])
def test_validity_propagation_agrees(vm, cc, tmp_path, a, b):
    source = (
        PROFILE
        + ".entity read i32 a dim 1\n.entity read i32 b dim 1\n"
        + ".entry go -> i32\n  load.h a\n  load.h b\n  add.i32\n  ret_v\n"
    )
    agree(vm, cc, tmp_path, source, ABSENT_HOST.format(a, b))


@pytest.mark.parametrize("a", ["= 5", "= unavailable", "= invalid"])
@pytest.mark.parametrize("b", ["= 7", "= unavailable", "= invalid"])
def test_else_agrees(vm, cc, tmp_path, a, b):
    source = (
        PROFILE
        + ".entity read i32 a dim 1\n.entity read i32 b dim 1\n"
        + ".entry go -> i32\n  load.h a\n  load.h b\n  else\n  ret_v\n"
    )
    agree(vm, cc, tmp_path, source, ABSENT_HOST.format(a, b))


@pytest.mark.parametrize("predicate", ["is_valid", "is_unavailable", "is_invalid"])
@pytest.mark.parametrize("state", ["= 5", "= unavailable", "= invalid"])
def test_the_predicates_agree(vm, cc, tmp_path, predicate, state):
    source = (
        PROFILE
        + ".entity read i32 a dim 1\n"
        + f".entry go -> bool\n  load.h a\n  {predicate}\n  ret_v\n"
    )
    agree(vm, cc, tmp_path, source, f"entity read i32 a dim 1 {state}\n")


def test_a_fault_agrees_including_the_exit_code(vm, cc, tmp_path):
    source = (
        PROFILE
        + ".entity read i32 a dim 1\n"
        + ".entry go -> i32\n"
        + "  load.h a\n  const.i32.s8 1\n  gt.i32\n  jmp_if_false L\n"
        + "  const.i32.s8 1\n  ret_v\nL:\n  const.i32.s8 0\n  ret_v\n"
    )
    result = agree(vm, cc, tmp_path, source, "entity read i32 a dim 1\n")
    assert result.output == "fault absent_condition\n"
    assert result.code == 3


def test_an_unwritten_local_agrees(vm, cc, tmp_path):
    agree(
        vm,
        cc,
        tmp_path,
        PROFILE + ".entry go -> i32\n  .local scratch i32\n  load.l scratch\n  ret_v\n",
    )


def test_locals_round_trip_the_same_way(vm, cc, tmp_path):
    source = (
        PROFILE
        + ".entity read i32 a dim 1\n"
        + ".entry go -> i32\n"
        + "  .local held i32\n"
        + "  load.h a\n  store.l held\n"
        + "  load.l held\n  load.l held\n  add.i32\n  ret_v\n"
    )
    for state in ("= 21", "= unavailable", "= invalid"):
        agree(vm, cc, tmp_path, source, f"entity read i32 a dim 1 {state}\n")


# -- the host boundary ----------------------------------------------------


def test_writes_agree_in_content_and_order(vm, cc, tmp_path):
    source = (
        PROFILE
        + ".entity read i32 a dim 1\n"
        + ".entity write i32 first dim 2\n"
        + ".entity write i32 second dim 2\n"
        + ".entry go\n"
        + "  load.h a\n  store.h first\n"
        + "  const.i32.s8 7\n  store.h second\n  ret\n"
    )
    result = agree(
        vm,
        cc,
        tmp_path,
        source,
        "entity read i32 a dim 1 = invalid\n"
        "entity write i32 first dim 2\nentity write i32 second dim 2\n",
    )
    assert result.output.splitlines()[0].startswith("write first")
    assert result.output.splitlines()[1].startswith("write second")


def test_reading_back_a_write_agrees(vm, cc, tmp_path):
    source = (
        PROFILE
        + ".entity rw i32 memory dim 1\n"
        + ".entry go -> i32\n"
        + "  const.i32.s8 42\n  store.h memory\n  load.h memory\n  ret_v\n"
    )
    agree(vm, cc, tmp_path, source, "entity rw i32 memory dim 1\n")


def test_a_host_call_agrees(vm, cc, tmp_path):
    source = (
        PROFILE
        + ".hostfn i32 reading i32\n"
        + ".entry go -> i32\n  const.i32.s8 3\n  call.h reading\n  ret_v\n"
    )
    agree(vm, cc, tmp_path, source, "function i32 reading i32 = 41\n")


def test_a_host_fault_agrees(vm, cc, tmp_path):
    source = (
        PROFILE + ".hostfn i32 reading\n.entry go -> i32\n  call.h reading\n  ret_v\n"
    )
    result = agree(vm, cc, tmp_path, source, "function i32 reading = fault\n")
    assert result.output == "fault host_fault\n"


# -- control flow ---------------------------------------------------------

WORKED_EXAMPLE = (
    PROFILE
    + ".entity read i32 temp dim 1\n"
    + ".entity write i32 fan.speed dim 2\n"
    + ".entry on_temp\n"
    + "  load.h temp\n  const.i32.s16 280\n  gt.i32\n  jmp_if_false L1\n"
    + "  const.i32.s8 3\n  jmp end\n"
    + "L1:\n  load.h temp\n  const.i32.s16 250\n  gt.i32\n  jmp_if_false L2\n"
    + "  const.i32.s8 2\n  jmp end\n"
    + "L2:\n  const.i32.s8 0\n"
    + "end:\n  store.h fan.speed\n  ret\n"
)


@pytest.mark.parametrize("temperature", ["= 291", "= 280", "= 250", "= 100", ""])
def test_the_worked_example_agrees_on_every_arm(vm, cc, tmp_path, temperature):
    agree(
        vm,
        cc,
        tmp_path,
        WORKED_EXAMPLE,
        f"entity read i32 temp dim 1 {temperature}\nentity write i32 fan.speed dim 2\n",
    )


def test_a_join_after_two_arms_agrees(vm, cc, tmp_path):
    source = (
        PROFILE
        + ".entity read i32 a dim 1\n"
        + ".entry go -> i32\n"
        + "  load.h a\n  const.i32.s8 0\n  gt.i32\n  jmp_if_true positive\n"
        + "  const.i32.s8 -1\n  jmp join\n"
        + "positive:\n  const.i32.s8 1\n"
        + "join:\n  const.i32.s8 10\n  mul.i32\n  ret_v\n"
    )
    for state in ("= 5", "= -5", "= 0"):
        agree(vm, cc, tmp_path, source, f"entity read i32 a dim 1 {state}\n")


# -- the generated source itself -------------------------------------------


def test_the_generated_c_states_its_own_floating_point_requirement():
    """§1.5: `a*b + c` contracts to a fused multiply-add under
    `-std=gnu11` and not under `-std=c11`, on the same compiler. The
    generated translation unit says so itself rather than trusting the
    build."""
    text = generate(assemble(PROFILE + ".entry go\n  ret\n"))
    assert "#pragma STDC FP_CONTRACT OFF" in text


def test_a_name_collision_is_refused_rather_than_emitted():
    container = assemble(
        PROFILE
        + ".entity read i32 fan.speed dim 1\n"
        + ".entity read i32 fan_speed dim 1\n"
        + ".entry go\n  ret\n"
    )
    with pytest.raises(UnsupportedProgram, match="mangle"):
        generate(container)
