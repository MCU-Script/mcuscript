# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0
"""The instruction table against the specification's own claims."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from mcuscript import opcodes
from mcuscript.opcodes import (
    BY_CODE,
    BY_NAME,
    GROUP_RANGES,
    Group,
    Operand,
    groups_used,
)

SPEC = Path(__file__).resolve().parents[2] / "spec"


def test_ranges_are_disjoint():
    seen: dict[int, Group] = {}
    for group, (lo, hi) in GROUP_RANGES.items():
        for code in range(lo, hi + 1):
            assert code not in seen, f"{group} overlaps {seen[code]} at 0x{code:02X}"
            seen[code] = group


def test_zero_is_unassigned():
    # A run of erased flash decodes as an undefined opcode rather than as
    # something executable (§3.1).
    assert 0x00 not in BY_CODE


def test_instruction_size_follows_from_the_opcode():
    for op in BY_CODE.values():
        assert op.size == 1 + opcodes.OPERAND_SIZE[op.operand]
        assert 1 <= op.size <= 3


def test_every_branch_is_off16():
    for op in BY_CODE.values():
        if op.name.startswith("jmp"):
            assert op.operand is Operand.OFF16


def test_groups_used_reports_exactly_the_bits_the_code_needs():
    code = bytes([0x04, 0x0B, 0x23])  # const.true, drop, ret — all core
    assert groups_used(code) == Group.CORE.mask

    code = bytes([0x04, 0x0B, 0x50, 0x23])  # ... plus extend.i32_i64
    assert groups_used(code) == Group.CORE.mask | Group.I64.mask


def test_groups_used_refuses_an_undefined_opcode():
    with pytest.raises(ValueError):
        groups_used(bytes([0xFF]))


def test_the_loop_group_holds_the_bound_and_not_the_branch():
    """The group's whole content is `loop.guard`.

    Worth pinning because the obvious expectation is the opposite one:
    a group called `loop` ought to contain the jump. It does not — the
    backward branch is `jmp`, which `core` already has — and an
    instruction added here later should have to argue with that.
    """
    lo, hi = GROUP_RANGES[Group.LOOP]
    assert [op.name for code, op in sorted(BY_CODE.items()) if lo <= code <= hi] == [
        "loop.guard"
    ]
    assert BY_NAME["jmp"].group is Group.CORE


@pytest.mark.parametrize("chapter", ["03-instructions.md"])
def test_every_opcode_in_the_specification_is_in_the_table(chapter):
    """The specification tabulates opcodes as `| \\`0xNN\\` | \\`NAME\\` |`.

    Ranges written as `0x41`–`0x46` are collapsed rows for a family and
    are checked by their endpoints only.
    """
    text = (SPEC / chapter).read_text(encoding="utf-8")
    singles = re.findall(r"^\|\s*`0x([0-9A-F]{2})`\s*\|", text, re.MULTILINE)
    ranges = re.findall(
        r"^\|\s*`0x([0-9A-F]{2})`–`0x([0-9A-F]{2})`\s*\|", text, re.MULTILINE
    )
    assert singles, "no opcode rows found — has the table's shape changed?"
    for code in singles:
        assert int(code, 16) in BY_CODE, f"0x{code} is specified but not implemented"
    for lo, hi in ranges:
        assert int(lo, 16) in BY_CODE and int(hi, 16) in BY_CODE
