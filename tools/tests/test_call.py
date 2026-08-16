# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0
"""The `call` group, in both backends and in both verifiers.

Calls are where the two lowerings are structurally furthest apart: the
VM keeps frames in one flat slot buffer it sized at load, and the
generated C uses the embedder's thread stack and ordinary C functions.
Nothing forces them to agree except this file — so most of it runs the
same container both ways and compares the bytes, and the parts that
cannot be a comparison say why.
"""

from __future__ import annotations

import pytest
from harness import PROFILE, agree, compile_once

from mcuscript.asm import AsmError, assemble
from mcuscript.container import Container, Function
from mcuscript.errors import Refusal, Refused
from mcuscript.opcodes import Group, ValType
from mcuscript.verify import analyze, verify

RET = b"\x23"
ALL_GROUPS = frozenset(Group)


def expect(refusal: Refusal, container: Container) -> Refused:
    with pytest.raises(Refused) as caught:
        verify(container, implemented=ALL_GROUPS)
    assert caught.value.refusal is refusal, (
        f"expected {refusal}, got {caught.value.refusal}"
    )
    return caught.value


# -- the verifier ---------------------------------------------------------


def test_a_call_takes_the_callees_declared_parameters():
    facts = analyze(
        assemble(
            PROFILE + ".entry go -> i32\n"
            "  const.i32.s8 2\n"
            "  const.i32.s8 3\n"
            "  call add\n"
            "  ret_v\n"
            ".fn add -> i32\n"
            "  .param a i32\n"
            "  .param b i32\n"
            "  load.l a\n"
            "  load.l b\n"
            "  add.i32\n"
            "  ret_v\n"
        )
    )
    # Two pushed, one left: from the caller's side a call is one
    # instruction with a stack effect like any other.
    assert facts["go"].max_stack == 2
    assert facts["go"].max_call_depth == 1
    # go's frame is 0 locals + 2 stack, add's is 2 locals + 2 stack.
    assert facts["go"].max_slots == 6


def test_a_call_with_the_wrong_argument_type_is_refused():
    with pytest.raises(Refused) as caught:
        assemble(
            PROFILE + ".entry go\n  const.true\n  call take\n  ret\n"
            ".fn take\n  .param n i32\n  ret\n"
        )
    assert caught.value.refusal is Refusal.TYPE_MISMATCH


def test_a_call_with_too_few_arguments_is_refused():
    with pytest.raises(Refused) as caught:
        assemble(
            PROFILE + ".entry go\n  const.i32.s8 1\n  call take\n  ret\n"
            ".fn take\n  .param a i32\n  .param b i32\n  ret\n"
        )
    assert caught.value.refusal is Refusal.STACK_UNDERFLOW


def test_a_call_to_a_function_that_is_not_there_is_refused():
    container = Container(
        code=b"\x80\x07" + RET,
        functions=[Function("go", 0, max_stack=0)],
        required_groups=Group.CORE.mask | Group.CALL.mask,
    )
    expect(Refusal.INDEX_OUT_OF_RANGE, container)


def test_scratch_locals_are_not_parameters():
    """A callee may have locals beyond its signature, and the caller must
    not be asked to push them. Before `param_count` existed there was no
    way to say so, and every local was an argument."""
    facts = analyze(
        assemble(
            PROFILE + ".entry go -> i32\n"
            "  const.i32.s8 4\n"
            "  call twice\n"
            "  ret_v\n"
            ".fn twice -> i32\n"
            "  .param n i32\n"
            "  .local scratch i32\n"
            "  load.l n\n"
            "  store.l scratch\n"
            "  load.l scratch\n"
            "  load.l scratch\n"
            "  add.i32\n"
            "  ret_v\n"
        )
    )
    assert facts["twice"].max_stack == 2


def test_an_invocable_entry_point_cannot_take_parameters():
    with pytest.raises(AsmError) as caught:
        assemble(PROFILE + ".entry go\n  .param n i32\n  ret\n")
    assert "host-invocable" in str(caught.value)


def test_a_container_claiming_an_entry_point_with_parameters_is_refused():
    # The assembler will not write one, so the record is built by hand —
    # which is the case a loader has to survive.
    container = Container(
        code=RET,
        functions=[
            Function("go", 0, local_types=(ValType.I32,), param_count=1, invocable=True)
        ],
    )
    with pytest.raises(Refused) as caught:
        Container.decode(container.encode())
    assert caught.value.refusal is Refusal.ENTRY_TAKES_PARAMETERS


def test_a_parameter_may_not_follow_a_local():
    with pytest.raises(AsmError) as caught:
        assemble(
            PROFILE + ".entry go\n  call f\n  ret\n"
            ".fn f\n  .local t i32\n  .param n i32\n  ret\n"
        )
    assert "before every .local" in str(caught.value)


# -- both backends --------------------------------------------------------


def test_a_call_returns_a_value(vm, cc, tmp_path):
    run = agree(
        vm,
        cc,
        tmp_path,
        PROFILE + ".entry go -> i32\n"
        "  const.i32.s8 20\n"
        "  const.i32.s8 3\n"
        "  call sub\n"
        "  ret_v\n"
        ".fn sub -> i32\n"
        "  .param a i32\n"
        "  .param b i32\n"
        "  load.l a\n"
        "  load.l b\n"
        "  sub.i32\n"
        "  ret_v\n",
    )
    # Leftmost pushed first, so this is 20 - 3 and not 3 - 20. Argument
    # order is exactly the sort of thing two backends can disagree about.
    assert "result i32 17" in run.output


def test_a_call_carries_validity_through(vm, cc, tmp_path):
    run = agree(
        vm,
        cc,
        tmp_path,
        PROFILE + ".entity read i32 temp\n"
        ".entry go -> i32\n"
        "  load.h temp\n"
        "  call double\n"
        "  ret_v\n"
        ".fn double -> i32\n"
        "  .param n i32\n"
        "  load.l n\n"
        "  load.l n\n"
        "  add.i32\n"
        "  ret_v\n",
        "entity read i32 temp = unavailable\n",
    )
    assert "unavailable" in run.output


def test_a_void_call_pushes_nothing(vm, cc, tmp_path):
    run = agree(
        vm,
        cc,
        tmp_path,
        PROFILE + ".entity write i32 out\n"
        ".entry go\n"
        "  const.i32.s8 7\n"
        "  call emit\n"
        "  ret\n"
        ".fn emit\n"
        "  .param n i32\n"
        "  load.l n\n"
        "  store.h out\n"
        "  ret\n",
        "entity write i32 out\n",
    )
    assert "write out 7" in run.output


def test_a_callees_scratch_locals_start_unavailable(vm, cc, tmp_path):
    run = agree(
        vm,
        cc,
        tmp_path,
        PROFILE + ".entry go -> bool\n"
        "  const.i32.s8 1\n"
        "  call peek\n"
        "  ret_v\n"
        ".fn peek -> bool\n"
        "  .param n i32\n"
        "  .local never_written i32\n"
        "  load.l never_written\n"
        "  is_unavailable\n"
        "  ret_v\n",
    )
    assert "result bool true" in run.output


def test_a_chain_of_calls(vm, cc, tmp_path):
    run = agree(
        vm,
        cc,
        tmp_path,
        PROFILE + ".entry go -> i32\n"
        "  const.i32.s8 1\n"
        "  call a\n"
        "  ret_v\n"
        ".fn a -> i32\n"
        "  .param n i32\n"
        "  load.l n\n"
        "  const.i32.s8 10\n"
        "  mul.i32\n"
        "  call b\n"
        "  ret_v\n"
        ".fn b -> i32\n"
        "  .param n i32\n"
        "  load.l n\n"
        "  const.i32.s8 5\n"
        "  add.i32\n"
        "  ret_v\n",
    )
    assert "result i32 15" in run.output


def test_a_host_call_inside_a_callee(vm, cc, tmp_path):
    run = agree(
        vm,
        cc,
        tmp_path,
        PROFILE + ".hostfn i32 clamp i32\n"
        ".entry go -> i32\n"
        "  const.i32.s8 9\n"
        "  call through\n"
        "  ret_v\n"
        ".fn through -> i32\n"
        "  .param n i32\n"
        "  load.l n\n"
        "  call.h clamp\n"
        "  ret_v\n",
        "function i32 clamp i32 = 4\n",
    )
    assert "result i32 4" in run.output


def test_a_fault_inside_a_callee_ends_the_invocation(vm, cc, tmp_path):
    run = agree(
        vm,
        cc,
        tmp_path,
        PROFILE + ".entity read i32 temp\n"
        ".entity write i32 out\n"
        ".entry go\n"
        "  load.h temp\n"
        "  call decide\n"
        "  ret\n"
        ".fn decide\n"
        "  .param n i32\n"
        "  load.l n\n"
        "  const.i32.s8 0\n"
        "  gt.i32\n"
        "  jmp_if_false low\n"
        "  const.i32.s8 1\n"
        "  store.h out\n"
        "  ret\n"
        "low:\n"
        "  const.i32.s8 0\n"
        "  store.h out\n"
        "  ret\n",
        "entity read i32 temp = unavailable\nentity write i32 out\n",
    )
    # The comparison is against an absent reading reaching a branch two
    # frames down: the fault has to leave both frames, in both backends.
    assert "fault absent_condition" in run.output
    assert "write" not in run.output


# -- recursion ------------------------------------------------------------

#: `n` is counted down to zero and the result is the number of calls
#: that ran. With a cap of 5 the fifth frame is the last allowed one.
COUNTDOWN = (
    PROFILE + ".entity read i32 start\n"
    ".entry go -> i32\n"
    "  load.h start\n"
    "  call down\n"
    "  ret_v\n"
    ".fn down -> i32\n"
    "  .param n i32\n"
    "  .cap 5\n"
    "  load.l n\n"
    "  const.i32.s8 0\n"
    "  gt.i32\n"
    "  jmp_if_false bottom\n"
    "  load.l n\n"
    "  const.i32.s8 1\n"
    "  sub.i32\n"
    "  call down\n"
    "  const.i32.s8 1\n"
    "  add.i32\n"
    "  ret_v\n"
    "bottom:\n"
    "  const.i32.s8 0\n"
    "  ret_v\n"
)


def test_recursion_within_the_cap(vm, cc, tmp_path):
    program = compile_once(vm, cc, tmp_path, COUNTDOWN)
    for depth in range(5):
        run = program.agree(f"entity read i32 start = {depth}\n")
        assert f"result i32 {depth}" in run.output, run.output


def test_recursion_past_the_cap_faults(vm, cc, tmp_path):
    program = compile_once(vm, cc, tmp_path, COUNTDOWN)
    run = program.agree("entity read i32 start = 5\n")
    # Five frames of `down` are allowed; the sixth is the fault, and
    # both backends have to reach it at the same input.
    assert "fault recursion_limit" in run.output


def test_the_cap_counts_frames_and_not_round_trips(vm, cc, tmp_path):
    """`a → b → a → b → a` is five, exactly as `a → a → a → a → a` is.

    One counter per component is what makes this true without either
    backend knowing the shape of the cycle."""
    source = (
        PROFILE + ".entity read i32 start\n"
        ".entry go -> i32\n"
        "  load.h start\n"
        "  call ping\n"
        "  ret_v\n"
        ".fn ping -> i32\n"
        "  .param n i32\n"
        "  .cap 5\n"
        "  load.l n\n"
        "  const.i32.s8 0\n"
        "  gt.i32\n"
        "  jmp_if_false bottom\n"
        "  load.l n\n"
        "  const.i32.s8 1\n"
        "  sub.i32\n"
        "  call pong\n"
        "  const.i32.s8 1\n"
        "  add.i32\n"
        "  ret_v\n"
        "bottom:\n"
        "  const.i32.s8 0\n"
        "  ret_v\n"
        ".fn pong -> i32\n"
        "  .param n i32\n"
        "  .cap 5\n"
        "  load.l n\n"
        "  call ping\n"
        "  ret_v\n"
    )
    program = compile_once(vm, cc, tmp_path, source)
    # start=2: ping, pong, ping, pong, ping — five frames, the last of
    # which sees n == 0 and stops. One more and it is the fault.
    assert "result i32 2" in program.agree("entity read i32 start = 2\n").output
    assert (
        "fault recursion_limit" in program.agree("entity read i32 start = 3\n").output
    )


def test_an_entry_point_may_recurse_into_itself(vm, cc, tmp_path):
    """The entry point's own frame counts against the cap.

    Two things meet here that meet nowhere else: the VM has to seed the
    counter at invocation rather than at a call, and the generated C has
    only one function — so it is calling itself before its prototype
    would have been emitted."""
    source = (
        PROFILE + ".entity read i32 start\n"
        ".entry go -> i32\n"
        "  .cap 3\n"
        "  load.h start\n"
        "  const.i32.s8 0\n"
        "  gt.i32\n"
        "  jmp_if_false bottom\n"
        "  call go\n"
        "  ret_v\n"
        "bottom:\n"
        "  const.i32.s8 0\n"
        "  ret_v\n"
    )
    program = compile_once(vm, cc, tmp_path, source)
    # `start` is read afresh in every frame, so a positive one recurses
    # until the cap: the entry occupies the first of three.
    assert "result i32 0" in program.agree("entity read i32 start = 0\n").output
    assert "fault recursion_limit" in program.agree(
        "entity read i32 start = 1\n"
    ).output


def test_the_generated_counter_is_balanced_after_a_fault(vm, cc, tmp_path):
    """Invoke twice; the second must behave exactly like the first.

    This is the one thing the comparison cannot see. The VM's counters
    are locals of `mcuscript_invoke`, so a fault unwinding past them
    costs nothing; the generated C keeps a static counter, and a
    decrement missing from the fault path would leave it raised and
    refuse the *next* invocation for what this one did.
    """
    program = compile_once(vm, cc, tmp_path, COUNTDOWN, repeat=2)
    faulted = program.compiled_only("entity read i32 start = 5\n")
    assert faulted.output.count("fault recursion_limit") == 2, faulted.output

    fine = program.compiled_only("entity read i32 start = 4\n")
    assert fine.output.count("result i32 4") == 2, fine.output
