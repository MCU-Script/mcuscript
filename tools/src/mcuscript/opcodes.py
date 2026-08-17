# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0
"""The instruction table.

This module is the single source of truth for the instruction set of
specification chapter 3. The assembler, the disassembler, the verifier
and the C backend all read it, and a test compares the C runtime's
opcode header against it so the two cannot drift.

Every group that has instructions is now implemented by both backends,
which moves the refusal of §2.5 out of reach of a real program: the
only way a container can require something this build lacks is to say
so in its header, and that is what the check reads anyway. The
reserved `loop` group is what a test uses to say it.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class Group(enum.IntEnum):
    """Instruction groups; the value is the bit in ``required_groups``."""

    CORE = 0
    I64 = 1
    FLOAT = 2
    CALL = 3
    BITS = 4
    LOOP = 5
    I64DIV = 6

    @property
    def mask(self) -> int:
        return 1 << self.value


#: The groups this version's runtime implements: every one that has
#: instructions. `loop` is reserved with none at all (spec §3.8), so the
#: refusal of §2.5 is exercised through a container whose *header*
#: claims a group — which is what the specification actually says the
#: check is about.
IMPLEMENTED_GROUPS = frozenset(
    {Group.CORE, Group.I64, Group.FLOAT, Group.CALL, Group.BITS, Group.I64DIV}
)

#: Opcode range per group (inclusive), spec §3.2. Ranges are disjoint so
#: an implementation that omits a group omits a contiguous span of its
#: dispatch table.
GROUP_RANGES: dict[Group, tuple[int, int]] = {
    Group.CORE: (0x01, 0x3F),
    Group.I64: (0x40, 0x5F),
    Group.FLOAT: (0x60, 0x7F),
    Group.CALL: (0x80, 0x8F),
    Group.BITS: (0x90, 0x9F),
    Group.LOOP: (0xA0, 0xAF),
    Group.I64DIV: (0xB0, 0xBF),
}


class ValType(enum.IntEnum):
    """Type codes, spec §4.1."""

    VOID = 0x00
    I32 = 0x01
    I64 = 0x02
    F32 = 0x03
    BOOL = 0x04

    def __str__(self) -> str:
        return _TYPE_NAMES[self]


_TYPE_NAMES = {
    ValType.VOID: "void",
    ValType.I32: "i32",
    ValType.I64: "i64",
    ValType.F32: "f32",
    ValType.BOOL: "bool",
}

TYPE_BY_NAME = {name: t for t, name in _TYPE_NAMES.items()}


class Operand(enum.Enum):
    """The operand an opcode carries. Its size follows from the kind."""

    NONE = "none"
    IMM8 = "imm8"  # signed
    IMM16 = "imm16"  # signed
    IDX8 = "idx8"  # unsigned index into a table
    OFF16 = "off16"  # signed, relative to the byte after the instruction


OPERAND_SIZE = {
    Operand.NONE: 0,
    Operand.IMM8: 1,
    Operand.IMM16: 2,
    Operand.IDX8: 1,
    Operand.OFF16: 2,
}


class Poly(enum.Enum):
    """How the verifier types an instruction whose signature is not fixed.

    Everything here needs a table lookup (the local's declared type, the
    import's signature) or is genuinely type-agnostic. Instructions with
    a fixed signature carry ``None`` and are handled by ``pops``/
    ``pushes`` alone.
    """

    LOCAL_GET = "local_get"  # type from the entry point's local table
    LOCAL_SET = "local_set"
    HOST_GET = "host_get"  # type from the import table
    HOST_SET = "host_set"
    HOST_CALL = "host_call"  # signature from the import table
    CALL = "call"  # signature from the callee's record
    DROP = "drop"  # any one value
    DUP = "dup"  # any one value, twice
    SELECT = "select"  # `else`: T T -> T
    PREDICATE = "predicate"  # any -> bool
    RET = "ret"  # against the function's return type
    RET_V = "ret_v"


@dataclass(frozen=True, slots=True)
class Op:
    code: int
    name: str
    group: Group
    operand: Operand = Operand.NONE
    pops: tuple[ValType, ...] = ()  # bottom of the popped run first
    pushes: tuple[ValType, ...] = ()
    poly: Poly | None = None
    doc: str = ""

    @property
    def size(self) -> int:
        return 1 + OPERAND_SIZE[self.operand]

    @property
    def is_branch(self) -> bool:
        return self.operand is Operand.OFF16

    def __str__(self) -> str:
        return self.name


_I32 = ValType.I32
_I64 = ValType.I64
_F32 = ValType.F32
_BOOL = ValType.BOOL


def _binary(t: ValType) -> dict:
    return {"pops": (t, t), "pushes": (t,)}


def _unary(t: ValType) -> dict:
    return {"pops": (t,), "pushes": (t,)}


def _compare(t: ValType) -> dict:
    return {"pops": (t, t), "pushes": (_BOOL,)}


_OPS: list[Op] = [
    # -- core: constants ---------------------------------------------
    Op(0x01, "const.i32.s8", Group.CORE, Operand.IMM8, pushes=(_I32,)),
    Op(0x02, "const.i32.s16", Group.CORE, Operand.IMM16, pushes=(_I32,)),
    Op(0x03, "const.i32", Group.CORE, Operand.IDX8, pushes=(_I32,)),
    Op(0x04, "const.true", Group.CORE, pushes=(_BOOL,)),
    Op(0x05, "const.false", Group.CORE, pushes=(_BOOL,)),
    # -- core: locals ------------------------------------------------
    Op(0x06, "load.l", Group.CORE, Operand.IDX8, poly=Poly.LOCAL_GET),
    Op(0x07, "store.l", Group.CORE, Operand.IDX8, poly=Poly.LOCAL_SET),
    # -- core: host access -------------------------------------------
    Op(0x08, "load.h", Group.CORE, Operand.IDX8, poly=Poly.HOST_GET),
    Op(0x09, "store.h", Group.CORE, Operand.IDX8, poly=Poly.HOST_SET),
    Op(0x0A, "call.h", Group.CORE, Operand.IDX8, poly=Poly.HOST_CALL),
    # -- core: stack -------------------------------------------------
    Op(0x0B, "drop", Group.CORE, poly=Poly.DROP),
    Op(0x0C, "dup", Group.CORE, poly=Poly.DUP),
    # -- core: i32 arithmetic ----------------------------------------
    Op(0x10, "add.i32", Group.CORE, **_binary(_I32)),
    Op(0x11, "sub.i32", Group.CORE, **_binary(_I32)),
    Op(0x12, "mul.i32", Group.CORE, **_binary(_I32)),
    Op(0x13, "div.i32", Group.CORE, **_binary(_I32)),
    Op(0x14, "rem.i32", Group.CORE, **_binary(_I32)),
    Op(0x15, "neg.i32", Group.CORE, **_unary(_I32)),
    # -- core: i32 comparison ----------------------------------------
    Op(0x18, "eq.i32", Group.CORE, **_compare(_I32)),
    Op(0x19, "ne.i32", Group.CORE, **_compare(_I32)),
    Op(0x1A, "lt.i32", Group.CORE, **_compare(_I32)),
    Op(0x1B, "le.i32", Group.CORE, **_compare(_I32)),
    Op(0x1C, "gt.i32", Group.CORE, **_compare(_I32)),
    Op(0x1D, "ge.i32", Group.CORE, **_compare(_I32)),
    # -- core: bool --------------------------------------------------
    Op(0x1E, "not", Group.CORE, **_unary(_BOOL)),
    # -- core: branches and return -----------------------------------
    Op(0x20, "jmp", Group.CORE, Operand.OFF16),
    Op(0x21, "jmp_if_false", Group.CORE, Operand.OFF16, pops=(_BOOL,)),
    Op(0x22, "jmp_if_true", Group.CORE, Operand.OFF16, pops=(_BOOL,)),
    Op(0x23, "ret", Group.CORE, poly=Poly.RET),
    Op(0x24, "ret_v", Group.CORE, poly=Poly.RET_V),
    # -- core: validity ----------------------------------------------
    Op(0x28, "else", Group.CORE, poly=Poly.SELECT),
    Op(0x29, "is_valid", Group.CORE, poly=Poly.PREDICATE),
    Op(0x2A, "is_unavailable", Group.CORE, poly=Poly.PREDICATE),
    Op(0x2B, "is_invalid", Group.CORE, poly=Poly.PREDICATE),
    # -- i64 -----------------------------------------------------------
    Op(0x40, "const.i64", Group.I64, Operand.IDX8, pushes=(_I64,)),
    Op(0x41, "add.i64", Group.I64, **_binary(_I64)),
    Op(0x42, "sub.i64", Group.I64, **_binary(_I64)),
    Op(0x43, "mul.i64", Group.I64, **_binary(_I64)),
    Op(0x46, "neg.i64", Group.I64, **_unary(_I64)),
    Op(0x48, "eq.i64", Group.I64, **_compare(_I64)),
    Op(0x49, "ne.i64", Group.I64, **_compare(_I64)),
    Op(0x4A, "lt.i64", Group.I64, **_compare(_I64)),
    Op(0x4B, "le.i64", Group.I64, **_compare(_I64)),
    Op(0x4C, "gt.i64", Group.I64, **_compare(_I64)),
    Op(0x4D, "ge.i64", Group.I64, **_compare(_I64)),
    Op(0x50, "extend.i32_i64", Group.I64, pops=(_I32,), pushes=(_I64,)),
    Op(0x51, "wrap.i64_i32", Group.I64, pops=(_I64,), pushes=(_I32,)),
    # -- float ---------------------------------------------------------
    Op(0x60, "const.f32", Group.FLOAT, Operand.IDX8, pushes=(_F32,)),
    Op(0x61, "add.f32", Group.FLOAT, **_binary(_F32)),
    Op(0x62, "sub.f32", Group.FLOAT, **_binary(_F32)),
    Op(0x63, "mul.f32", Group.FLOAT, **_binary(_F32)),
    Op(0x64, "div.f32", Group.FLOAT, **_binary(_F32)),
    Op(0x65, "neg.f32", Group.FLOAT, **_unary(_F32)),
    Op(0x68, "eq.f32", Group.FLOAT, **_compare(_F32)),
    Op(0x69, "ne.f32", Group.FLOAT, **_compare(_F32)),
    Op(0x6A, "lt.f32", Group.FLOAT, **_compare(_F32)),
    Op(0x6B, "le.f32", Group.FLOAT, **_compare(_F32)),
    Op(0x6C, "gt.f32", Group.FLOAT, **_compare(_F32)),
    Op(0x6D, "ge.f32", Group.FLOAT, **_compare(_F32)),
    Op(0x70, "convert.i32_f32", Group.FLOAT, pops=(_I32,), pushes=(_F32,)),
    Op(0x71, "trunc.f32_i32", Group.FLOAT, pops=(_F32,), pushes=(_I32,)),
    # -- call ----------------------------------------------------------
    Op(0x80, "call", Group.CALL, Operand.IDX8, poly=Poly.CALL),
    # -- bits ----------------------------------------------------------
    Op(0x90, "and.i32", Group.BITS, **_binary(_I32)),
    Op(0x91, "or.i32", Group.BITS, **_binary(_I32)),
    Op(0x92, "xor.i32", Group.BITS, **_binary(_I32)),
    Op(0x93, "bitnot.i32", Group.BITS, **_unary(_I32)),
    Op(0x94, "shl.i32", Group.BITS, **_binary(_I32)),
    Op(0x95, "shr.i32", Group.BITS, **_binary(_I32)),
    # -- i64div ----------------------------------------------------------
    # Split out of `i64` because 64-bit division is the only arithmetic in
    # the instruction set that a 32-bit target cannot do in registers: the
    # C compiler calls a library routine for it, and that routine is three
    # times the size of the rest of the group put together (§3.4).
    Op(0xB0, "div.i64", Group.I64DIV, **_binary(_I64)),
    Op(0xB1, "rem.i64", Group.I64DIV, **_binary(_I64)),
]


BY_CODE: dict[int, Op] = {op.code: op for op in _OPS}
BY_NAME: dict[str, Op] = {op.name: op for op in _OPS}

assert len(BY_CODE) == len(_OPS), "duplicate opcode byte"
assert len(BY_NAME) == len(_OPS), "duplicate mnemonic"
assert 0x00 not in BY_CODE, "0x00 must stay unassigned (spec §3.1)"
for _op in _OPS:
    _lo, _hi = GROUP_RANGES[_op.group]
    assert _lo <= _op.code <= _hi, f"{_op.name} outside its group's range"


def group_of(code: int) -> Group | None:
    """The group an opcode byte falls into, assigned or not."""
    for group, (lo, hi) in GROUP_RANGES.items():
        if lo <= code <= hi:
            return group
    return None


def groups_used(code: bytes) -> int:
    """The ``required_groups`` mask for an instruction stream.

    Exactly the bits the code needs — not the bits the language has
    (spec §2.5). Decoding is by instruction length, so this assumes a
    stream that starts at an instruction boundary; callers that have not
    verified that use :mod:`mcuscript.verify` instead.
    """
    mask = 0
    pc = 0
    while pc < len(code):
        op = BY_CODE.get(code[pc])
        if op is None:
            raise ValueError(f"undefined opcode 0x{code[pc]:02X} at {pc}")
        mask |= op.group.mask
        pc += op.size
    return mask


def group_names(mask: int) -> list[str]:
    """Human-readable group names in a mask, unknown bits included."""
    names = []
    for group in Group:
        if mask & group.mask:
            names.append(group.name.lower())
    unknown = mask & ~sum(g.mask for g in Group)
    if unknown:
        names.append(f"reserved(0x{unknown:X})")
    return names
