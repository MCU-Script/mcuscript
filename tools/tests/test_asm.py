# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0
"""The assembler, and the worked example the specification prints."""

from __future__ import annotations

import pytest

from mcuscript.asm import AsmError, assemble, disassemble
from mcuscript.container import Container
from mcuscript.opcodes import ValType

# spec §3.9: fan.speed = match temp { > 28°C -> 3, > 25°C -> 2, else -> 0 },
# with the profile normalizing temperature to tenths of a degree.
WORKED_EXAMPLE = """
.profile 1 0.1
.entity read i32 temp dim 1
.entity write i32 fan.speed dim 2

.entry on_temp
        load.h temp
        const.i32.s16 280
        gt.i32
        jmp_if_false L1
        const.i32.s8 3
        jmp end
L1:     load.h temp
        const.i32.s16 250
        gt.i32
        jmp_if_false L2
        const.i32.s8 2
        jmp end
L2:     const.i32.s8 0
end:    store.h fan.speed
        ret
"""


def test_the_worked_example_is_the_size_the_specification_claims():
    container = assemble(WORKED_EXAMPLE)
    assert len(container.code) == 33
    assert container.functions[0].max_stack == 2
    assert container.functions[0].max_call_depth == 0


def test_the_worked_examples_jump_offsets():
    """The offsets are printed in the specification, so they are pinned
    here — a document that shows numbers nobody recomputes is a document
    that drifts."""
    code = assemble(WORKED_EXAMPLE).code

    def off16(at: int) -> int:
        return int.from_bytes(code[at + 1 : at + 3], "little", signed=True)

    assert off16(6) == 5  # jmp_if_false → L1 at 14
    assert off16(11) == 16  # jmp → end at 30
    assert off16(20) == 5  # jmp_if_false → L2 at 28
    assert off16(25) == 2  # jmp → end at 30
    assert code[32] == 0x23  # ret


def test_the_last_jump_before_the_final_arm_is_not_removable():
    """§3.9 makes a point of it: without the jump, execution falls into
    the last arm and pushes a second value."""
    code = assemble(WORKED_EXAMPLE).code
    assert code[25] == 0x20, "the instruction before the else arm is a jmp"


def test_round_trip_through_the_disassembler():
    original = assemble(WORKED_EXAMPLE)
    again = assemble(disassemble(original))
    assert again.encode() == original.encode()


def test_round_trip_of_a_decoded_container():
    blob = assemble(WORKED_EXAMPLE).encode()
    again = assemble(disassemble(Container.decode(blob)))
    assert again.encode() == blob


CALLS = """.profile 1 0.0
.entry go -> i32
        const.i32.s8 4
        call countdown
        ret_v
.fn countdown -> i32
        .param n i32
        .local scratch i32
        .cap 5
        load.l n
        const.i32.s8 0
        gt.i32
        jmp_if_false bottom
        load.l n
        const.i32.s8 1
        sub.i32
        call countdown
        ret_v
bottom: const.i32.s8 0
        ret_v
"""


def test_round_trip_of_calls_parameters_and_a_cap():
    """Everything the `call` group added to a record at once.

    Round-tripping is the cheapest check that the encoder and the
    decoder agree about a new field: `param_count` is a prefix length
    into the local table, so getting it wrong turns a parameter into
    scratch and the bytes come back different."""
    original = assemble(CALLS)
    text = disassemble(original)
    assert "  .param v0 i32" in text
    assert "  .local v1 i32" in text
    assert "  .cap 5" in text
    assert assemble(text).encode() == original.encode()


STATES = """.profile 1 0.0
.entry go -> bool
        const.true
        const.false
        and
        const.unavailable bool
        or
        const.invalid bool
        else
        ret_v
"""


def test_round_trip_of_a_type_operand():
    """The one operand kind that is neither an index nor a number.

    A `type8` that round-tripped as a number would still assemble and
    still disassemble; it would just say `const.invalid 1`, and the next
    reader would look for constant 1.
    """
    original = assemble(STATES)
    text = disassemble(original)
    assert "  const.unavailable bool" in text
    assert "  const.invalid bool" in text
    assert assemble(text).encode() == original.encode()


def test_a_function_that_is_not_invocable():
    container = assemble(
        ".profile 0 0.0\n"
        ".entry go\n  call helper\n  drop\n  ret\n"
        ".fn helper -> i32\n  const.i32.s8 1\n  ret_v\n"
    )
    assert [f.invocable for f in container.functions] == [True, False]
    assert container.functions[1].return_type is ValType.I32


def test_locals_and_constants_are_addressed_by_name():
    container = assemble(
        ".profile 0 0.0\n"
        ".const big i32 100000\n"
        ".entry go\n"
        "  .local acc i32\n"
        "  const.i32 big\n"
        "  store.l acc\n"
        "  ret\n"
    )
    assert container.code == bytes([0x03, 0x00, 0x07, 0x00, 0x23])
    assert container.constants[0].value == 100000


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (".entry go\n  wiggle\n", "unknown instruction"),
        (".entry go\n  jmp nowhere\n", "unknown label"),
        (".entry go\n  load.h absent\n  ret\n", "unknown import"),
        (".entry go\n  const.i32 absent\n  ret\n", "unknown constant"),
        (".entry go\n  load.l absent\n  ret\n", "unknown local"),
        ("  ret\n", "outside a function"),
        (".entry go\n  const.i32.s8 500\n  ret\n", "does not fit"),
        (".entry go\n  add.i32 3\n", "takes no operand"),
        (".entry go\n  const.i32.s8\n", "takes one operand"),
        (".entry go\n  const.invalid 1\n  ret\n", "is not a type"),
        (".entry go\n  const.invalid void\n  ret\n", "is not a type"),
        (".wobble 1\n", "unknown directive"),
        (".entry go\n.entry go\n  ret\n", "already defined"),
        (".entity read i32 a\n.entity read i32 a\n", "already imported"),
        (".entry go\nL:\nL:\n  ret\n", "already defined"),
        (".entry go\n", "no instructions"),
    ],
)
def test_assembler_diagnostics(source, message):
    with pytest.raises(AsmError) as caught:
        assemble(source)
    assert message in str(caught.value)


def test_comments_and_blank_lines_are_ignored():
    container = assemble(
        "; a leading comment\n"
        "\n"
        ".profile 0 0.0   ; trailing\n"
        ".entry go\n"
        "  ret            ; and here\n"
    )
    assert container.code == bytes([0x23])
