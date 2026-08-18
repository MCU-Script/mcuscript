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


@pytest.mark.parametrize(
    "body",
    [
        "  const.i32.s8 12\n  const.i32.s8 10\n  and.i32\n  ret_v\n",
        "  const.i32.s8 12\n  const.i32.s8 10\n  or.i32\n  ret_v\n",
        "  const.i32.s8 12\n  const.i32.s8 10\n  xor.i32\n  ret_v\n",
        "  const.i32.s8 12\n  bitnot.i32\n  ret_v\n",
        "  const.i32.s8 -1\n  bitnot.i32\n  ret_v\n",
        # A negative operand is where a backend that used signed `&`
        # would be relying on the representation rather than the bits.
        "  const.i32.s8 -8\n  const.i32.s8 12\n  and.i32\n  ret_v\n",
        "  const.i32.s8 1\n  const.i32.s8 31\n  shl.i32\n  ret_v\n",
        "  const.i32.s8 -16\n  const.i32.s8 2\n  shr.i32\n  ret_v\n",
        "  const.i32.s8 -1\n  const.i32.s8 31\n  shr.i32\n  ret_v\n",
        "  const.i32.s8 16\n  const.i32.s8 0\n  shr.i32\n  ret_v\n",
        # Out of range in both directions: `invalid`, not whatever the
        # machine's shifter happens to do (§1.5).
        "  const.i32.s8 1\n  const.i32.s8 32\n  shl.i32\n  ret_v\n",
        "  const.i32.s8 1\n  const.i32.s8 -1\n  shl.i32\n  ret_v\n",
        "  const.i32.s8 -16\n  const.i32.s8 32\n  shr.i32\n  ret_v\n",
    ],
)
def test_bitwise_agrees(vm, cc, tmp_path, body):
    agree(vm, cc, tmp_path, PROFILE + ".entry go -> i32\n" + body)


def test_a_shift_out_of_range_is_invalid_rather_than_a_machine_quirk(vm, cc, tmp_path):
    """The one case where "the backends agree" is not enough on its own.

    x86 masks the shift count to five bits and ARM produces zero, so two
    conforming builds of the *same* backend would already disagree if
    the count reached the hardware. §1.5 says `invalid`, and that is a
    claim about the value and not only about the agreement."""
    run = agree(
        vm,
        cc,
        tmp_path,
        PROFILE + ".entry go -> i32\n"
        "  const.i32.s8 1\n  const.i32.s8 33\n  shl.i32\n  ret_v\n",
    )
    assert "result i32 0 invalid" in run.output


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


# -- loops -----------------------------------------------------------------
#
# The backward branch is where the two lowerings stop resembling each
# other most: the VM assigns `pc` and the C jumps to a label whose
# operand-stack variables were laid out on an earlier pass. Agreement
# here is the claim that reading the depth out of the verifier's map,
# rather than walking it forward, was the right call.


def _countdown(limit: int, stop: int, *, body: str = "") -> str:
    """`acc = sum(range(stop))`, under a guard that allows `limit` turns."""
    return (
        PROFILE
        + ".entry go -> i32\n"
        + "  .local acc i32\n  .local i i32\n  .local n i32\n"
        + "  const.i32.s8 0\n  store.l acc\n"
        + "  const.i32.s8 0\n  store.l i\n"
        + f"  const.i32.s8 {limit}\n  store.l n\n"
        + "top:\n"
        + "  loop.guard n\n"
        + f"  load.l i\n  const.i32.s8 {stop}\n  ge.i32\n  jmp_if_true out\n"
        + body
        + "  load.l acc\n  load.l i\n  add.i32\n  store.l acc\n"
        + "  load.l i\n  const.i32.s8 1\n  add.i32\n  store.l i\n"
        + "  jmp top\n"
        + "out:\n  load.l acc\n  ret_v\n"
    )


@pytest.mark.parametrize("stop", [0, 1, 5])
def test_a_bounded_loop_agrees(vm, cc, tmp_path, stop):
    agree(vm, cc, tmp_path, _countdown(20, stop))


def test_a_loop_that_runs_out_of_turns_agrees(vm, cc, tmp_path):
    """Including the fault and the exit code.

    The counter is one short of what the loop needs, so both backends
    have to stop in the same place — and the C one has to unwind
    through its `done:` label rather than fall out of the function.
    """
    agree(vm, cc, tmp_path, _countdown(4, 5))


def test_a_loop_whose_counter_is_never_set_agrees(vm, cc, tmp_path):
    """Zero turns allowed, so the guard faults on the first one.

    This is the default a producer gets by forgetting the bound, and
    the two backends reach it by different routes: the VM's locals are
    zeroed slots, the generated C's are initialised declarations.
    """
    source = (
        PROFILE
        + ".entry go -> i32\n"
        + "  .local n i32\n"
        + "top:\n  loop.guard n\n  jmp top\n"
    )
    agree(vm, cc, tmp_path, source)


def test_nested_loops_agree(vm, cc, tmp_path):
    """Two counters, the inner one reset by the outer body.

    Resetting a counter is forbidden *inside* its own loop and required
    just outside it, which is the one place the rule could be read the
    wrong way round.
    """
    source = (
        PROFILE
        + ".entry go -> i32\n"
        + "  .local acc i32\n  .local i i32\n  .local j i32\n"
        + "  .local outer i32\n  .local inner i32\n"
        + "  const.i32.s8 0\n  store.l acc\n"
        + "  const.i32.s8 0\n  store.l i\n"
        + "  const.i32.s8 10\n  store.l outer\n"
        + "o_top:\n  loop.guard outer\n"
        + "  load.l i\n  const.i32.s8 3\n  ge.i32\n  jmp_if_true o_out\n"
        + "  const.i32.s8 0\n  store.l j\n"
        + "  const.i32.s8 10\n  store.l inner\n"
        + "i_top:\n  loop.guard inner\n"
        + "  load.l j\n  const.i32.s8 4\n  ge.i32\n  jmp_if_true i_out\n"
        + "  load.l acc\n  const.i32.s8 1\n  add.i32\n  store.l acc\n"
        + "  load.l j\n  const.i32.s8 1\n  add.i32\n  store.l j\n"
        + "  jmp i_top\n"
        + "i_out:\n"
        + "  load.l i\n  const.i32.s8 1\n  add.i32\n  store.l i\n"
        + "  jmp o_top\n"
        + "o_out:\n  load.l acc\n  ret_v\n"
    )
    assert agree(vm, cc, tmp_path, source).output.split()[2] == "12"


def test_a_loop_around_a_host_write_agrees_in_order(vm, cc, tmp_path):
    """The writes must land in the same order as well as the same count.

    A loop is the cheapest way to get many writes out of one program,
    and write *order* is the part of the host boundary a reordered
    lowering would break silently.
    """
    source = (
        PROFILE
        + ".entity write i32 out dim 1\n"
        + ".entry go\n"
        + "  .local i i32\n  .local n i32\n"
        + "  const.i32.s8 0\n  store.l i\n"
        + "  const.i32.s8 10\n  store.l n\n"
        + "top:\n  loop.guard n\n"
        + "  load.l i\n  const.i32.s8 4\n  ge.i32\n  jmp_if_true out\n"
        + "  load.l i\n  store.h out\n"
        + "  load.l i\n  const.i32.s8 1\n  add.i32\n  store.l i\n"
        + "  jmp top\n"
        + "out:\n  ret\n"
    )
    run = agree(vm, cc, tmp_path, source, "entity write i32 out dim 1\n")
    assert run.output.count("write ") == 4


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
