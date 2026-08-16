# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0
"""The verifier: every refusal it owes, produced by a real container.

These containers are built in Python rather than assembled, because the
assembler will not write most of them — an out-of-range index or a
forged stack depth is exactly what an assembler exists to prevent, and
exactly what a verifier exists to catch.
"""

from __future__ import annotations

import pytest

from mcuscript.asm import assemble
from mcuscript.container import (
    Access,
    Constant,
    Container,
    Function,
    Import,
    ImportKind,
)
from mcuscript.errors import Refusal, Refused
from mcuscript.opcodes import Group, ValType
from mcuscript.verify import verify

ALL_GROUPS = frozenset(Group)


def build(
    code: bytes,
    *,
    locals_: tuple[ValType, ...] = (),
    returns: ValType = ValType.VOID,
    imports: tuple[Import, ...] = (),
    constants: tuple[Constant, ...] = (),
    max_stack: int = 0,
    max_call_depth: int = 0,
    groups: int = Group.CORE.mask,
    functions: list[Function] | None = None,
) -> Container:
    container = Container(
        code=code,
        constants=list(constants),
        imports=list(imports),
        functions=functions
        if functions is not None
        else [
            Function(
                "go",
                0,
                return_type=returns,
                max_stack=max_stack,
                max_call_depth=max_call_depth,
                local_types=locals_,
            )
        ],
    )
    container.required_groups = groups
    return container


def expect(refusal: Refusal, container: Container) -> Refused:
    with pytest.raises(Refused) as caught:
        verify(container, implemented=ALL_GROUPS)
    assert caught.value.refusal is refusal, caught.value
    return caught.value


TEMP = Import("temp", ImportKind.ENTITY, Access.READ, ValType.I32, 1)
FAN = Import("fan", ImportKind.ENTITY, Access.WRITE, ValType.I32, 2)
LOG = Import("log", ImportKind.FUNCTION, Access.NONE, ValType.VOID, 0, (ValType.I32,))

RET = b"\x23"


# -- the happy path -------------------------------------------------------


def test_a_well_formed_container_passes_and_reports_its_numbers():
    facts = verify(
        assemble("""
        .profile 0 0.0
        .entity read i32 temp
        .entry go -> i32
          load.h temp
          load.h temp
          add.i32
          ret_v
    """)
    )
    assert facts["go"].max_stack == 2
    assert facts["go"].max_call_depth == 0


# -- decoding -------------------------------------------------------------


def test_undefined_opcode():
    error = expect(Refusal.UNDEFINED_OPCODE, build(b"\xff" + RET))
    assert "0xFF" in str(error)


def test_a_zeroed_byte_is_an_undefined_opcode():
    # A run of erased flash must not decode as something executable.
    expect(Refusal.UNDEFINED_OPCODE, build(b"\x00" + RET))


def test_an_opcode_from_a_group_the_header_does_not_require():
    # extend.i32_i64 is in `i64`; the header claims only `core`.
    expect(
        Refusal.UNDEFINED_OPCODE,
        build(b"\x01\x01\x50\x0b" + RET, groups=Group.CORE.mask),
    )


def test_truncated_instruction():
    expect(Refusal.TRUNCATED_INSTRUCTION, build(b"\x02\x01"))  # const.i32.s16, 1 byte


# -- control flow ---------------------------------------------------------


def test_backward_branch():
    # jmp -3, back onto itself
    expect(Refusal.BACKWARD_BRANCH, build(b"\x20\xfd\xff" + RET))


def test_a_branch_past_the_end_of_the_function():
    expect(Refusal.BAD_BRANCH_TARGET, build(b"\x20\x64\x00" + RET))


def test_a_branch_into_the_middle_of_an_instruction():
    """The classic verifier bypass: the same bytes read two ways.

    Both readings are individually well-typed here — the immediate of
    ``const.i32.s16 1281`` is itself a valid ``const.i32.s8 5``, both
    push one ``i32`` and both fall into the same ``drop``. Nothing but
    the coverage count distinguishes this from honest code.
    """
    code = (
        b"\x04"  # 0  const.true                  [bool]
        b"\x21\x01\x00"  # 1  jmp_if_false +1 → 5     []
        b"\x02\x01\x05"  # 4  const.i32.s16 1281      [i32]
        b"\x0b" + RET  # 7  drop                        []  # 8
    )
    error = expect(Refusal.BAD_BRANCH_TARGET, build(code, max_stack=1))
    assert "overlap" in str(error)


def test_unreachable_code():
    # ret, then a byte no path can reach.
    expect(Refusal.UNREACHABLE_CODE, build(RET + b"\x04"))


def test_execution_may_not_run_off_the_end():
    expect(Refusal.BAD_BRANCH_TARGET, build(b"\x04\x0b"))  # const.true, drop, …


# -- the type stack -------------------------------------------------------


def test_type_mismatch():
    # const.true; const.true; add.i32
    error = expect(Refusal.TYPE_MISMATCH, build(b"\x04\x04\x10" + RET))
    assert "add.i32" in str(error)


def test_stack_underflow():
    expect(Refusal.STACK_UNDERFLOW, build(b"\x10" + RET))  # add.i32 on nothing


def test_inconsistent_join():
    # One path leaves an i32 on the stack, the other a bool, and they meet.
    code = (
        b"\x04"  # const.true                     [bool]
        b"\x21\x05\x00"  # jmp_if_false +5 → other  []
        b"\x01\x01"  # const.i32.s8 1              [i32]
        b"\x20\x01\x00"  # jmp +1 → join
        b"\x04"  # other: const.false              [bool]
        b"\x0b" + RET  # join: drop
    )
    error = expect(Refusal.INCONSISTENT_JOIN, build(code, max_stack=1))
    assert "i32" in str(error) and "bool" in str(error)


def test_a_void_function_may_not_return_a_value():
    expect(Refusal.UNBALANCED_RETURN, build(b"\x04\x24"))  # const.true; ret_v


def test_a_value_function_may_not_return_nothing():
    expect(Refusal.UNBALANCED_RETURN, build(RET, returns=ValType.I32))


def test_a_return_may_not_leave_the_stack_dirty():
    expect(Refusal.UNBALANCED_RETURN, build(b"\x04" + RET, max_stack=1))


def test_dup_is_the_one_instruction_that_grows_the_stack():
    facts = verify(build(b"\x04\x0c\x0b\x0b" + RET, max_stack=2))
    assert facts["go"].max_stack == 2


def test_else_takes_two_values_of_one_type():
    # const.true; const.i32.s8 1; else
    expect(Refusal.TYPE_MISMATCH, build(b"\x04\x01\x01\x28\x0b" + RET, max_stack=2))


def test_a_predicate_accepts_any_type_and_yields_bool():
    facts = verify(build(b"\x01\x07\x29\x0b" + RET, max_stack=1))
    assert facts["go"].max_stack == 1


# -- indices --------------------------------------------------------------


def test_a_constant_index_past_the_pool():
    expect(Refusal.INDEX_OUT_OF_RANGE, build(b"\x03\x00\x0b" + RET))


def test_a_constant_of_the_wrong_type():
    expect(
        Refusal.TYPE_MISMATCH,
        build(b"\x03\x00\x0b" + RET, constants=(Constant(ValType.F32, 1.0),)),
    )


def test_an_import_index_past_the_table():
    expect(Refusal.INDEX_OUT_OF_RANGE, build(b"\x08\x00\x0b" + RET))


def test_a_local_index_past_the_declaration():
    expect(Refusal.INDEX_OUT_OF_RANGE, build(b"\x06\x00\x0b" + RET))


# -- host access ----------------------------------------------------------


def test_writing_a_read_only_entity():
    error = expect(
        Refusal.ACCESS_DENIED,
        build(b"\x01\x01\x09\x00" + RET, imports=(TEMP,), max_stack=1),
    )
    assert "temp" in str(error)


def test_reading_a_write_only_entity():
    expect(Refusal.ACCESS_DENIED, build(b"\x08\x00\x0b" + RET, imports=(FAN,)))


def test_calling_an_entity():
    expect(Refusal.KIND_MISMATCH, build(b"\x0a\x00" + RET, imports=(TEMP,)))


def test_reading_a_host_function():
    expect(Refusal.KIND_MISMATCH, build(b"\x08\x00\x0b" + RET, imports=(LOG,)))


def test_a_host_call_consumes_its_parameters():
    facts = verify(build(b"\x01\x2a\x0a\x00" + RET, imports=(LOG,), max_stack=1))
    assert facts["go"].max_stack == 1


def test_a_host_call_with_the_wrong_parameter_type():
    expect(
        Refusal.TYPE_MISMATCH, build(b"\x04\x0a\x00" + RET, imports=(LOG,), max_stack=1)
    )


# -- the declared numbers -------------------------------------------------


def test_a_forged_stack_depth_is_refused():
    # The whole reason verification is mandatory: the VM allocates from
    # this number, and it came from the file.
    error = expect(
        Refusal.STACK_DEPTH_MISMATCH,
        build(b"\x04\x0b" + RET, max_stack=200),
    )
    assert "200" in str(error) and "1" in str(error)


def test_a_forged_call_depth_is_refused():
    expect(Refusal.CALL_DEPTH_MISMATCH, build(RET, max_call_depth=7))


# -- the call graph -------------------------------------------------------


def _two_functions(code_a: bytes, code_b: bytes, *, cap_a=0, cap_b=0) -> Container:
    return build(
        code_a + code_b,
        groups=Group.CORE.mask | Group.CALL.mask,
        functions=[
            Function("a", 0, recursion_cap=cap_a),
            Function("b", len(code_a), recursion_cap=cap_b),
        ],
    )


def test_call_depth_is_computed_across_the_graph():
    container = _two_functions(b"\x80\x01" + RET, RET)
    container.functions[0] = Function("a", 0, max_call_depth=1)
    facts = verify(container, implemented=ALL_GROUPS)
    assert facts["a"].max_call_depth == 1
    assert facts["b"].max_call_depth == 0


def test_an_uncapped_self_call_is_refused():
    container = build(
        b"\x80\x00" + RET,
        groups=Group.CORE.mask | Group.CALL.mask,
        functions=[Function("a", 0)],
    )
    error = expect(Refusal.UNCAPPED_RECURSION, container)
    assert "a" in str(error)


def test_an_uncapped_mutual_call_is_refused():
    # a → b → a consumes the stack exactly as a → a does.
    error = expect(
        Refusal.UNCAPPED_RECURSION, _two_functions(b"\x80\x01" + RET, b"\x80\x00" + RET)
    )
    assert "a" in str(error) and "b" in str(error)


def test_one_cycle_may_not_declare_two_different_caps():
    error = expect(
        Refusal.UNCAPPED_RECURSION,
        _two_functions(b"\x80\x01" + RET, b"\x80\x00" + RET, cap_a=5, cap_b=3),
    )
    assert "different caps" in str(error)


def test_a_capped_cycle_is_accepted_and_bounds_the_depth():
    container = _two_functions(b"\x80\x01" + RET, b"\x80\x00" + RET, cap_a=5, cap_b=5)
    container.functions = [
        Function("a", 0, max_call_depth=9, recursion_cap=5),
        Function("b", 3, max_call_depth=9, recursion_cap=5),
    ]
    facts = verify(container, implemented=ALL_GROUPS)
    # cap 5 over a two-function cycle: at most ten frames, nine below.
    assert facts["a"].max_call_depth == 9
    assert facts["a"].recursion_cap == 5


# -- code regions ---------------------------------------------------------


def test_code_regions_must_tile_the_section():
    container = build(
        RET + RET,
        functions=[Function("a", 0), Function("b", 2)],  # b starts past the end
    )
    with pytest.raises(Refused) as caught:
        verify(container, implemented=ALL_GROUPS)
    assert caught.value.refusal is Refusal.MALFORMED_SECTION


def test_code_without_a_function_is_refused():
    container = build(RET, functions=[])
    with pytest.raises(Refused) as caught:
        verify(container, implemented=ALL_GROUPS)
    assert caught.value.refusal is Refusal.MALFORMED_SECTION
