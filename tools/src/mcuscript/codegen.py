# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0
"""A typed script becomes a container — the last stage of the front end.

The parser said what was written and `sema` said what it means; this
says what it *is*, as the bytes of specification chapters 2 to 4. It
reads the analysis rather than re-deriving anything: a literal's value
in base units, which import a name turned out to be, what every node's
type and dimension are. Where it needs something the analysis did not
record, the fix belongs there and not here — two stages that both decide
what an expression means is the drift this project cannot afford.

Three things are worth knowing before reading it.

**The lowering is a stack machine and nothing cleverer.** An expression
emits its operands and then its operator, which is why there is no
register allocation, no scheduling and no peephole pass. The container
is verified afterwards by the same verifier a loader would use, so a
mistake here is a refusal and not a wrong program.

**A dimension is gone by the time anything is emitted.** Units were
normalized to base units by `sema`, so what arrives here is integers and
floats; the only trace a dimension leaves is the data type it declared,
plus two lowerings that need to know it existed — a cyclic comparison
(§6.5.6) and a scale factor (§6.5.5.1).

**What it refuses, it refuses by name and with a span.** A construct the
chapter marks *planned*, or one whose lowering the instruction set
cannot express, produces the same kind of diagnostic as a type error —
never a traceback, and never a container that the verifier then has to
catch.
"""

from __future__ import annotations

import struct
from collections.abc import Callable
from dataclasses import dataclass, replace
from fractions import Fraction
from math import gcd

from . import ast
from .container import Access, Constant, Container, Function, Import, ImportKind
from .diagnostics import Span, error
from .opcodes import BY_NAME, Operand, ValType, groups_used
from .profile import Dimension, Profile, Unit
from .registry import Entity, HostFunction, Quantity, Registry
from .sema import Analysis, falls_through
from .verify import analyze

_INT_TYPES = (ValType.I32, ValType.I64)

#: Arithmetic mnemonics by operator and working type.
_ARITH = {
    "+": {ValType.I32: "add.i32", ValType.I64: "add.i64", ValType.F32: "add.f32"},
    "-": {ValType.I32: "sub.i32", ValType.I64: "sub.i64", ValType.F32: "sub.f32"},
    "*": {ValType.I32: "mul.i32", ValType.I64: "mul.i64", ValType.F32: "mul.f32"},
    "/": {ValType.I32: "div.i32", ValType.I64: "div.i64", ValType.F32: "div.f32"},
    "mod": {ValType.I32: "rem.i32", ValType.I64: "rem.i64"},
}

_COMPARE = {
    "==": "eq",
    "!=": "ne",
    "<": "lt",
    "<=": "le",
    ">": "gt",
    ">=": "ge",
}

_SUFFIX = {ValType.I32: "i32", ValType.I64: "i64", ValType.F32: "f32"}

#: Toward zero, at the width the result needs (§3.5).
_TRUNC = {ValType.I32: "trunc.f32_i32", ValType.I64: "trunc.f32_i64"}

_BITWISE = {
    "&": "and.i32",
    "|": "or.i32",
    "^": "xor.i32",
    "<<": "shl.i32",
    ">>": "shr.i32",
}

_CONVERSIONS = {"to_i32": ValType.I32, "to_i64": ValType.I64, "to_f32": ValType.F32}


class _Code:
    """A function's instruction stream, with branches patched in place."""

    def __init__(self) -> None:
        self.buf = bytearray()

    def __len__(self) -> int:
        return len(self.buf)

    def emit(self, mnemonic: str, operand: int | None = None) -> None:
        op = BY_NAME[mnemonic]
        self.buf.append(op.code)
        if op.operand is Operand.NONE:
            return
        assert operand is not None, mnemonic
        if op.operand is Operand.IMM8:
            self.buf += int(operand).to_bytes(1, "little", signed=True)
        elif op.operand is Operand.IMM16:
            self.buf += int(operand).to_bytes(2, "little", signed=True)
        else:  # IDX8 and TYPE8 are both one unsigned byte
            self.buf.append(int(operand))

    def branch(self, mnemonic: str) -> int:
        """Emit a branch to be patched later; returns a handle."""
        self.buf.append(BY_NAME[mnemonic].code)
        at = len(self.buf)
        self.buf += b"\x00\x00"
        return at

    def here(self) -> int:
        return len(self.buf)

    def patch(self, at: int, target: int | None = None) -> None:
        destination = self.here() if target is None else target
        delta = destination - (at + 2)
        if not -0x8000 <= delta <= 0x7FFF:
            raise ValueError("a branch is out of range")
        self.buf[at : at + 2] = delta.to_bytes(2, "little", signed=True)


@dataclass
class _Loop:
    """Where `break` and `continue` go, filled in as they are met."""

    continue_at: int
    breaks: list[int]
    continues: list[int]


class _Builder:
    """The container's shared tables: constants and imports."""

    def __init__(self, profile: Profile) -> None:
        self.profile = profile
        self.constants: list[Constant] = []
        self._constant_index: dict[tuple[ValType, object], int] = {}
        self.imports: list[Import] = []
        self._import_index: dict[str, int] = {}

    def constant(self, type_: ValType, value: int | float) -> int:
        key = (
            type_,
            struct.pack("<f", value) if type_ is ValType.F32 else value,
        )
        if key not in self._constant_index:
            self._constant_index[key] = len(self.constants)
            self.constants.append(Constant(type_, value))
        index = self._constant_index[key]
        if index > 255:
            raise error("this script uses more constants than a container holds", None)
        return index

    def import_of(self, thing: Entity | HostFunction, span: Span) -> int:
        if thing.name in self._import_index:
            return self._import_index[thing.name]
        if len(self.imports) > 255:
            raise error(
                "this script reaches more host names than a container holds", span
            )
        if isinstance(thing, Entity):
            access = (Access.READ if thing.readable else 0) | (
                Access.WRITE if thing.writable else 0
            )
            record = Import(
                name=thing.name,
                kind=ImportKind.ENTITY,
                access=access,
                type=thing.quantity.type,
                dimension=(
                    thing.quantity.dimension.id if thing.quantity.dimension else 0
                ),
            )
        else:
            record = Import(
                name=thing.name,
                kind=ImportKind.FUNCTION,
                access=Access.NONE,
                type=(
                    thing.returns.type if thing.returns is not None else ValType.VOID
                ),
                dimension=(
                    thing.returns.dimension.id
                    if thing.returns is not None and thing.returns.dimension
                    else 0
                ),
                param_types=tuple(p.type for p in thing.params),
            )
        self._import_index[thing.name] = len(self.imports)
        self.imports.append(record)
        return self._import_index[thing.name]


class _Emit:
    """One function's worth of code generation."""

    def __init__(
        self,
        outer: _Generator,
        name: str,
        params: tuple[tuple[str, Quantity], ...],
        returns: Quantity | None,
        body: ast.Block,
    ) -> None:
        self.outer = outer
        self.analysis = outer.analysis
        self.builder = outer.builder
        self.name = name
        self.body = body
        self.returns = returns
        self.code = _Code()
        self.locals: list[ValType] = []
        self.scopes: list[dict[str, int]] = [{}]
        self.loops: list[_Loop] = []
        self.param_count = len(params)
        for parameter, quantity in params:
            self.declare(parameter, quantity.type)

    # -- locals -----------------------------------------------------------

    def declare(self, name: str, type_: ValType) -> int:
        slot = self.slot(type_)
        self.scopes[-1][name] = slot
        return slot

    def slot(self, type_: ValType) -> int:
        """A fresh slot. Anonymous ones hold a `match` subject or a loop's
        bookkeeping, and cost a frame slot each — which is why the frame
        size the verifier computes is a real number and not a bound."""
        if len(self.locals) > 255:
            raise error("this script needs more locals than a container holds", None)
        self.locals.append(type_)
        return len(self.locals) - 1

    def lookup(self, name: str) -> int | None:
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        return None

    # -- the whole function ------------------------------------------------

    def run(self) -> tuple[bytes, tuple[ValType, ...], int]:
        wants_value = self.returns is not None
        reachable = falls_through(self.body)
        # A body that ends in `return` has already given its value; only
        # one that can fall off the end leaves one on the stack (§6.4.5).
        self.block(self.body, value=wants_value and reachable)
        if reachable:
            self.code.emit("ret_v" if wants_value else "ret")
        return bytes(self.code.buf), tuple(self.locals), self.param_count

    # -- statements ---------------------------------------------------------

    def block(self, node: ast.Block, *, value: bool) -> None:
        self.scopes.append({})
        for index, statement in enumerate(node.statements):
            last = index == len(node.statements) - 1
            self.statement(statement, keep=value and last)
        if value and (
            not node.statements or not isinstance(node.statements[-1], ast.ExprStmt)
        ):
            # A block that has to give a value and does not end in an
            # expression has none to give. `sema` refuses that shape, so
            # reaching here means the two stages disagree.
            raise error("this block gives no value", node.span)
        self.scopes.pop()

    def statement(self, node: ast.Stmt, *, keep: bool) -> None:
        match node:
            case ast.Let():
                quantity = self.analysis.type_of(node.value)
                self.expr(node.value)
                self.code.emit("store.l", self.declare(node.name, quantity.type))
            case ast.Assign():
                self.assign(node)
            case ast.ExprStmt():
                quantity = self.analysis.type_of(node.value)
                self.expr(node.value)
                if quantity.type is not ValType.VOID and not keep:
                    self.code.emit("drop")
            case ast.Return():
                if node.value is None:
                    self.code.emit("ret")
                else:
                    self.expr(node.value)
                    self.code.emit("ret_v")
            case ast.Break():
                self.loops[-1].breaks.append(self.code.branch("jmp"))
            case ast.Continue():
                self.loops[-1].continues.append(self.code.branch("jmp"))
            case ast.For():
                self.for_loop(node)
            case _:  # pragma: no cover - sema refuses everything else
                raise error("this statement cannot be compiled yet", node.span)

    def assign(self, node: ast.Assign) -> None:
        target = node.target
        assert isinstance(target, ast.Name)
        slot = None if target.is_dotted else self.lookup(target.text)
        if node.op != "=":
            # `x += e` is `x = x + e`, and the operator's result type is
            # the target's — `sema` checked that, so nothing widens here.
            place = self.analysis.type_of(target)
            self.arith(
                node.op[0],
                (lambda: self.load(target), place),
                (lambda: self.expr(node.value), self.analysis.type_of(node.value)),
                place,
                node.span,
            )
        else:
            self.expr(node.value)
        if slot is not None:
            self.code.emit("store.l", slot)
            return
        entity = self.analysis.imports[id(target)]
        self.code.emit("store.h", self.builder.import_of(entity, target.span))

    def for_loop(self, node: ast.For) -> None:
        """`for i in a..b`, with the bound of §6.4.4.

        The counter is `b - a + 1` and the body does not touch it, which
        is what §3.8.1 requires of a conforming cycle. It is not a limit
        the writer meets: a range says how many turns there are, and the
        guard is how the container proves it terminates.
        """
        assert isinstance(node.iterable, ast.Range)
        counted = self.analysis.type_of(node.iterable.low).type
        if counted is not ValType.I32:
            raise error(
                "a loop counts in `i32` in this version",
                node.iterable.span,
                "A 64-bit range would need a 64-bit guard, and the guard "
                "counts in `i32`.",
            )
        self.scopes.append({})
        self.expr(node.iterable.low)
        variable = self.declare(node.variable, ValType.I32)
        self.code.emit("store.l", variable)
        self.expr(node.iterable.high)
        limit = self.slot(ValType.I32)
        self.code.emit("store.l", limit)

        guard = self.slot(ValType.I32)
        self.code.emit("load.l", limit)
        self.code.emit("load.l", variable)
        self.code.emit("sub.i32")
        self.code.emit("const.i32.s8", 1)
        self.code.emit("add.i32")
        self.code.emit("store.l", guard)

        self.code.emit("load.l", variable)
        self.code.emit("load.l", limit)
        self.code.emit("le.i32")
        skip = self.code.branch("jmp_if_false")

        top = self.code.here()
        self.code.emit("loop.guard", guard)
        self.loops.append(_Loop(continue_at=0, breaks=[], continues=[]))
        self.block(node.body, value=False)
        loop = self.loops.pop()

        step = self.code.here()
        for at in loop.continues:
            self.code.patch(at, step)
        self.code.emit("load.l", variable)
        self.code.emit("const.i32.s8", 1)
        self.code.emit("add.i32")
        self.code.emit("store.l", variable)
        self.code.emit("load.l", variable)
        self.code.emit("load.l", limit)
        self.code.emit("le.i32")
        self.code.patch(self.code.branch("jmp_if_true"), top)

        self.code.patch(skip)
        for at in loop.breaks:
            self.code.patch(at)
        self.scopes.pop()

    # -- expressions ---------------------------------------------------------

    def expr(self, node: ast.Expr) -> None:
        match node:
            case ast.Number() | ast.Duration() | ast.DateTime():
                self.literal(node)
            case ast.BoolLit():
                self.code.emit("const.true" if node.value else "const.false")
            case ast.StateLit():
                quantity = self.analysis.type_of(node)
                self.code.emit(f"const.{node.state}", quantity.type.value)
            case ast.Name():
                self.load(node)
            case ast.Unary():
                self.unary(node)
            case ast.Binary():
                self.binary(node)
            case ast.IsCheck():
                self.expr(node.operand)
                self.code.emit(f"is_{node.state}")
                if node.negated:
                    self.code.emit("not")
            case ast.Call():
                self.call(node)
            case ast.If():
                self.if_expr(node, value=self.wants_value(node))
            case ast.Match():
                self.match_expr(node)
            case _:  # pragma: no cover - sema refuses everything else
                raise error("this expression cannot be compiled yet", node.span)

    def wants_value(self, node: ast.Expr) -> bool:
        return self.analysis.type_of(node).type is not ValType.VOID

    def literal(self, node: ast.Number | ast.Duration | ast.DateTime) -> None:
        quantity = self.analysis.type_of(node)
        value = self.analysis.values[id(node)]
        self.push_number(value, quantity.type, node.span)

    def push_number(self, value: Fraction, type_: ValType, span: Span) -> None:
        if type_ is ValType.F32:
            self.code.emit("const.f32", self.builder.constant(type_, float(value)))
            return
        if value.denominator != 1:
            raise error(
                f"{_decimal(value)} is not a whole number", span
            )  # pragma: no cover - sema normalizes first
        whole = value.numerator
        if type_ is ValType.I64:
            if -0x8000 <= whole <= 0x7FFF:
                # §3.4: a small 64-bit literal is an `i32` and an extend,
                # which costs a byte less than a pool entry and no pool
                # slot at all.
                self.push_i32(whole)
                self.code.emit("extend.i32_i64")
            else:
                self.code.emit("const.i64", self.builder.constant(type_, whole))
            return
        if not -0x8000_0000 <= whole <= 0x7FFF_FFFF:
            raise error(f"{whole} does not fit a 32-bit whole number", span)
        self.push_i32(whole)

    def push_i32(self, value: int) -> None:
        if -128 <= value <= 127:
            self.code.emit("const.i32.s8", value)
        elif -0x8000 <= value <= 0x7FFF:
            self.code.emit("const.i32.s16", value)
        else:
            self.code.emit("const.i32", self.builder.constant(ValType.I32, value))

    def load(self, node: ast.Name) -> None:
        if not node.is_dotted:
            slot = self.lookup(node.text)
            if slot is not None:
                self.code.emit("load.l", slot)
                return
        entity = self.analysis.imports[id(node)]
        self.code.emit("load.h", self.builder.import_of(entity, node.span))

    def unary(self, node: ast.Unary) -> None:
        quantity = self.analysis.type_of(node)
        self.expr(node.operand)
        if node.op == "not":
            self.code.emit("not")
        elif node.op == "-":
            self.code.emit(f"neg.{_SUFFIX[quantity.type]}")
        else:
            self.require_i32(quantity, node.span, "~")
            self.code.emit("bitnot.i32")

    def require_i32(self, quantity: Quantity, span: Span, operator: str) -> None:
        if quantity.type is not ValType.I32:
            raise error(
                f"`{operator}` works on 32-bit whole numbers in this version",
                span,
                "The instruction set has no 64-bit bitwise operations.",
            )

    def binary(self, node: ast.Binary) -> None:
        left = self.analysis.type_of(node.left)
        right = self.analysis.type_of(node.right)
        result = self.analysis.type_of(node)

        if node.op == "else":
            self.expr(node.left)
            self.expr(node.right)
            self.code.emit("else")
            return
        if node.op in ("and", "or"):
            self.expr(node.left)
            self.expr(node.right)
            self.code.emit(node.op)
            return
        if node.op in _COMPARE:
            if left.type is ValType.BOOL:
                self.bool_equality(node)
                return
            self.comparison(node, left)
            return
        if node.op in _BITWISE:
            self.require_i32(result, node.span, node.op)
            self.expr(node.left)
            self.expr(node.right)
            self.code.emit(_BITWISE[node.op])
            return
        if node.op in ("+", "-") and right.is_scale and not left.is_scale:
            self.relative_change(node, left, right, result)
            return
        self.arith(
            node.op,
            (lambda: self.expr(node.left), left),
            (lambda: self.expr(node.right), right),
            result,
            node.span,
        )

    def relative_change(
        self, node: ast.Binary, left: Quantity, right: Quantity, result: Quantity
    ) -> None:
        """`x + 5%` is `x * 105%` (§6.5.5.1), and this is where it becomes it.

        The right operand is not a constant in general — `x + rate` with
        a ratio entity is the same construct — so the one is pushed and
        the arithmetic done at run time.
        """
        working = right.type
        self.expr(node.left)
        self.convert(left.type, working, node.left.span)
        self.push_number(Fraction(1), working, node.span)
        self.expr(node.right)
        self.code.emit(_ARITH["+" if node.op == "+" else "-"][working])
        self.code.emit(_ARITH["*"][working])
        self.convert(working, result.type, node.span)

    def bool_equality(self, node: ast.Binary) -> None:
        """`a == b` on two yes-or-nos, as boolean algebra.

        The instruction set compares numbers and not `bool`s, and this is
        the reason it does not have to: equality on two of them is
        `(a and b) or (not a and not b)`, which the operators of §3.3
        already spell. Each operand is read twice, which is why they go
        into slots first — and the state still comes out right, because
        propagation is a maximum and a maximum does not care how often
        it sees the same operand.
        """
        left = self.slot(ValType.BOOL)
        right = self.slot(ValType.BOOL)
        self.expr(node.left)
        self.code.emit("store.l", left)
        self.expr(node.right)
        self.code.emit("store.l", right)
        self.code.emit("load.l", left)
        self.code.emit("load.l", right)
        self.code.emit("and")
        self.code.emit("load.l", left)
        self.code.emit("not")
        self.code.emit("load.l", right)
        self.code.emit("not")
        self.code.emit("and")
        self.code.emit("or")
        if node.op == "!=":
            self.code.emit("not")

    def comparison(self, node: ast.Binary, operand: Quantity) -> None:
        cyclic = operand.dimension is not None and operand.dimension.cyclic
        if cyclic and node.op in ("<", "<=", ">", ">="):
            # §6.5.6: the difference against zero, so the answer stays
            # right across the wrap.
            self.expr(node.left)
            self.expr(node.right)
            self.code.emit(_ARITH["-"][operand.type])
            self.push_number(Fraction(0), operand.type, node.span)
            self.code.emit(f"{_COMPARE[node.op]}.{_SUFFIX[operand.type]}")
            return
        self.expr(node.left)
        self.expr(node.right)
        self.code.emit(f"{_COMPARE[node.op]}.{_SUFFIX[operand.type]}")

    def arith(
        self,
        op: str,
        left: tuple[Callable[[], None], Quantity],
        right: tuple[Callable[[], None], Quantity],
        result: Quantity,
        span: Span,
    ) -> None:
        """Emit one arithmetic operator, converting as each operand lands.

        The working type is the widest of the two operands and the
        result, because §6.5.5's rule is about the *result*: two
        temperatures divided are a decimal, so the division that
        produces it happens in decimals. Each side is converted right
        after it is pushed, since a conversion afterwards would have to
        reach under the other one.
        """
        working = _widest(left[1].type, right[1].type, result.type)
        mnemonics = _ARITH.get(op)
        if mnemonics is None or working not in mnemonics:
            raise error(f"`{op}` cannot be compiled for {result}", span)
        push_left, left_type = left
        push_right, right_type = right
        push_left()
        self.convert(left_type.type, working, span)
        push_right()
        self.convert(right_type.type, working, span)
        self.code.emit(mnemonics[working])
        self.convert(working, result.type, span)

    def convert(self, have: ValType, want: ValType, span: Span) -> None:
        if have is want:
            return
        if have is ValType.I32 and want is ValType.F32:
            self.code.emit("convert.i32_f32")
            return
        if have is ValType.F32 and want is ValType.I32:
            self.code.emit("trunc.f32_i32")
            return
        if have is ValType.I32 and want is ValType.I64:
            self.code.emit("extend.i32_i64")
            return
        if have is ValType.I64 and want is ValType.I32:
            self.code.emit("wrap.i64_i32")
            return
        if have is ValType.I64 and want is ValType.F32:
            self.code.emit("convert.i64_f32")
            return
        if have is ValType.F32 and want is ValType.I64:
            self.code.emit("trunc.f32_i64")
            return
        raise error(  # pragma: no cover - every pair above is covered
            f"turning {have} into {want} is not something this version can do",
            span,
        )

    # -- calls ----------------------------------------------------------------

    def call(self, node: ast.Call) -> None:
        name = node.callee.text
        if name in _CONVERSIONS:
            self.conversion(node, _CONVERSIONS[name])
            return
        if name == "to_unit":
            self.to_unit(node)
            return
        if name == "abs":
            self.absolute(node)
            return
        if name in ("round", "trunc"):
            self.rounding(node, name)
            return
        if not node.callee.is_dotted and name in self.outer.functions:
            for argument in node.args:
                assert isinstance(argument, ast.Expr)
                self.expr(argument)
            self.outer.called.setdefault(self.name, set()).add(name)
            self.code.emit("call", self.outer.function_index[name])
            return
        function = self.analysis.imports[id(node.callee)]
        for argument in node.args:
            assert isinstance(argument, ast.Expr)
            self.expr(argument)
        self.code.emit("call.h", self.builder.import_of(function, node.span))

    def absolute(self, node: ast.Call) -> None:
        """`abs(x)`, as a comparison and a negation, inside a guard.

        There is no `ABS` instruction and there should not be: it is two
        instructions and a branch in every backend. The branch is why
        the guard is here — §6.3.9 says a built-in propagates validity
        like an operator, so `abs(temp)` with an unread sensor is
        `unavailable` and not a fault, and a branch on the operand would
        make it one (§1.3.1).
        """
        argument = node.args[0]
        assert isinstance(argument, ast.Expr)
        quantity = self.analysis.type_of(node)
        slot = self.slot(quantity.type)
        self.expr(argument)
        self.code.emit("store.l", slot)

        def body() -> None:
            self.code.emit("load.l", slot)
            self.push_number(Fraction(0), quantity.type, node.span)
            self.code.emit(f"ge.{_SUFFIX[quantity.type]}")
            negative = self.code.branch("jmp_if_false")
            self.code.emit("load.l", slot)
            done = self.code.branch("jmp")
            self.code.patch(negative)
            self.code.emit("load.l", slot)
            self.code.emit(f"neg.{_SUFFIX[quantity.type]}")
            self.code.patch(done)

        self.guarded(slot, body, lambda: self.code.emit("load.l", slot))

    def guarded(
        self,
        slot: int,
        body: Callable[[], None],
        fallback: Callable[[], None],
    ) -> None:
        """Run a branchy lowering only where its operand is valid.

        §6.3.9's own words: *"a lowering that branches on the operand is
        wrong even where it is obvious. The available pattern is to
        branch on a predicate instead."* `is_valid` yields a `valid`
        `bool` whatever it is given, so the branch here is always safe —
        and the fallback yields the operand carried through, which has
        exactly the right state and a defined payload.

        The fallback's *value* is never used, because its state is not
        valid; what matters is that both backends compute the same one.
        """
        self.code.emit("load.l", slot)
        self.code.emit("is_valid")
        absent = self.code.branch("jmp_if_false")
        body()
        done = self.code.branch("jmp")
        self.code.patch(absent)
        fallback()
        self.code.patch(done)

    def rounding(self, node: ast.Call, name: str) -> None:
        argument = node.args[0]
        assert isinstance(argument, ast.Expr)
        target = self.analysis.type_of(node).type
        self.expr(argument)
        if name == "trunc":
            self.code.emit(_TRUNC[target])
        else:
            self.round_f32(node.span, target)

    def round_f32(self, span: Span, target: ValType = ValType.I32) -> None:
        """Nearest, away from zero on a tie — §6.3.10's rule.

        `TRUNC` goes toward zero, so the half is added in the operand's
        own direction first, which needs the sign and therefore a
        branch — hence the guard of §6.3.9. Where the operand is not
        valid the fallback truncates instead: the same type, the same
        state, and a value nothing may look at.
        """
        slot = self.slot(ValType.F32)
        self.code.emit("store.l", slot)

        def body() -> None:
            self.code.emit("load.l", slot)
            self.code.emit("load.l", slot)
            self.push_number(Fraction(0), ValType.F32, span)
            self.code.emit("ge.f32")
            negative = self.code.branch("jmp_if_false")
            self.push_number(Fraction(1, 2), ValType.F32, span)
            done = self.code.branch("jmp")
            self.code.patch(negative)
            self.push_number(Fraction(-1, 2), ValType.F32, span)
            self.code.patch(done)
            self.code.emit("add.f32")
            self.code.emit(_TRUNC[target])

        def fallback() -> None:
            self.code.emit("load.l", slot)
            self.code.emit(_TRUNC[target])

        self.guarded(slot, body, fallback)

    # -- §6.3.10 conversions ---------------------------------------------------

    def conversion(self, node: ast.Call, target: ValType) -> None:
        """`to_i32(temp, °C, 100)` — out of the dimension system.

        The value on the stack is in base units and what the script asked
        for is *its own* unit at *its own* resolution, so the whole
        conversion is one exact rational: `(v - offset) × scale`. It is
        emitted as `(v × N - M) / D` with three integer constants, which
        is what keeps a unit with an offset — `°F` — from needing
        anything the instruction set does not have.
        """
        argument = node.args[0]
        assert isinstance(argument, ast.Expr)
        source = self.analysis.type_of(argument)
        scale, offset = self.scaling(node, source)
        self.expr(argument)
        self.rational(_terms(scale, -offset * scale), source.type, target, node.span)

    def to_unit(self, node: ast.Call) -> None:
        """The other direction: a plain number becomes a quantity.

        A number counted in `unit / resolution` becomes base units, which
        is the same arithmetic read backwards — `v × factor / resolution
        + offset`.
        """
        argument = node.args[0]
        assert isinstance(argument, ast.Expr)
        source = self.analysis.type_of(argument)
        result = self.analysis.type_of(node)
        _dimension, unit = self.written_unit(node.args[1])
        scale = unit.factor / self.factor(node, 2)
        self.expr(argument)
        self.rational(_terms(scale, unit.offset), source.type, result.type, node.span)

    def scaling(self, node: ast.Call, source: Quantity) -> tuple[Fraction, Fraction]:
        """What the operand has to be multiplied by, and shifted by first."""
        if source.dimension is None or len(node.args) < 2:
            return self.factor(node, 2), Fraction(0)
        _dimension, unit = self.written_unit(node.args[1])
        resolution = self.factor(node, 2)
        return resolution / unit.factor, unit.offset

    def written_unit(self, node: ast.Expr | ast.Unit) -> tuple[Dimension, Unit]:
        spelling = node.text if isinstance(node, ast.Unit | ast.Name) else ""
        found = self.builder.profile.find_unit(spelling)
        assert found is not None, spelling  # sema resolved it already
        return found

    def factor(self, node: ast.Call, index: int) -> Fraction:
        if len(node.args) <= index:
            return Fraction(1)
        written = node.args[index]
        assert isinstance(written, ast.Number)
        return Fraction(written.text)

    def rational(
        self,
        terms: tuple[int, int, int],
        source: ValType,
        target: ValType,
        span: Span,
    ) -> None:
        """Turn the value on the stack into `(v × N + M) / D`.

        Where the arithmetic happens is the whole of the correctness
        here. A conversion to `f32` converts **first** and scales in
        decimals, because scaling in whole numbers would divide 2650 by
        100 and hand back 26 where §6.3.10 promises 26.5. A conversion to
        a whole number scales in whole numbers and rounds once, at the
        divide.

        Each of the three steps is skipped where it would do nothing,
        which is the ordinary case: a script counting in the unit its
        profile already uses pays for no arithmetic at all.
        """
        multiplier, addend, divisor = terms
        working = (
            ValType.F32 if target is ValType.F32 or source is ValType.F32 else source
        )
        self.convert(source, working, span)
        if multiplier != 1:
            self.push_number(Fraction(multiplier), working, span)
            self.code.emit(_ARITH["*"][working])
        if addend != 0:
            self.push_number(Fraction(addend), working, span)
            self.code.emit(_ARITH["+"][working])
        if divisor != 1:
            if working is ValType.F32:
                self.push_number(Fraction(divisor), working, span)
                self.code.emit(_ARITH["/"][working])
            else:
                self.round_integer(divisor, working, span)
        if working is ValType.F32 and target is not ValType.F32:
            self.round_f32(span, target)
        else:
            self.convert(working, target, span)

    def round_integer(self, divisor: int, type_: ValType, span: Span) -> None:
        """Divide, rounding to nearest and away from zero on a tie.

        `DIV` truncates toward zero, so half the divisor is added in the
        dividend's own direction first — the whole-number form of the
        rule §6.3.10 states for the decimal one, and the same guard for
        the same reason: the sign test is a branch, and a conversion of
        an absent reading answers rather than faults.
        """
        slot = self.slot(type_)
        self.code.emit("store.l", slot)

        def body() -> None:
            self.code.emit("load.l", slot)
            self.push_number(Fraction(0), type_, span)
            self.code.emit(f"ge.{_SUFFIX[type_]}")
            negative = self.code.branch("jmp_if_false")
            self.code.emit("load.l", slot)
            self.push_number(Fraction(divisor, 2), type_, span)
            positive = self.code.branch("jmp")
            self.code.patch(negative)
            self.code.emit("load.l", slot)
            self.push_number(Fraction(-divisor, 2), type_, span)
            self.code.patch(positive)
            self.code.emit(_ARITH["+"][type_])
            self.push_number(Fraction(divisor), type_, span)
            self.code.emit(_ARITH["/"][type_])

        def fallback() -> None:
            self.code.emit("load.l", slot)
            self.push_number(Fraction(divisor), type_, span)
            self.code.emit(_ARITH["/"][type_])

        self.guarded(slot, body, fallback)

    # -- if and match ------------------------------------------------------------

    def if_expr(self, node: ast.If, *, value: bool) -> None:
        self.expr(node.condition)
        otherwise = self.code.branch("jmp_if_false")
        self.block(node.then, value=value)
        if node.otherwise is None:
            self.code.patch(otherwise)
            return
        done = self.code.branch("jmp")
        self.code.patch(otherwise)
        if isinstance(node.otherwise, ast.If):
            self.if_expr(node.otherwise, value=value)
        else:
            self.block(node.otherwise, value=value)
        self.code.patch(done)

    def match_expr(self, node: ast.Match) -> None:
        """The ladder of §6.3.5, validity first.

        The subject is evaluated once into a slot, because every arm
        tests it and a `match` on a host read must not read twice. The
        two state arms come first and are the reason for the two chosen
        state instructions: where a script names no arm for a state, the
        match yields that state itself, and something has to push it.
        """
        subject = self.analysis.type_of(node.subject)
        result = self.analysis.type_of(node)
        slot = self.slot(subject.type)
        self.expr(node.subject)
        self.code.emit("store.l", slot)

        ends: list[int] = []
        for state in ("unavailable", "invalid"):
            self.code.emit("load.l", slot)
            self.code.emit(f"is_{state}")
            skip = self.code.branch("jmp_if_false")
            arm = next(
                (
                    a
                    for a in node.arms
                    if isinstance(a.pattern, ast.StatePattern)
                    and a.pattern.state == state
                ),
                None,
            )
            if arm is not None:
                self.expr(arm.body)
            else:
                self.code.emit(f"const.{state}", result.type.value)
            ends.append(self.code.branch("jmp"))
            self.code.patch(skip)

        value_arms = [
            arm for arm in node.arms if not isinstance(arm.pattern, ast.StatePattern)
        ]
        # The arm that runs when nothing above it matched: the `else` if
        # there is one, and otherwise the last arm — which §6.3.5 lets a
        # `match` omit only when the arms provably cover every value, so
        # testing it would be a branch whose answer is known.
        fallthrough = next(
            (arm for arm in value_arms if isinstance(arm.pattern, ast.ElsePattern)),
            value_arms[-1] if value_arms else None,
        )
        for arm in value_arms:
            if arm is fallthrough:
                continue
            self.pattern(arm.pattern, slot, subject)
            skip = self.code.branch("jmp_if_false")
            self.expr(arm.body)
            ends.append(self.code.branch("jmp"))
            self.code.patch(skip)
        if fallthrough is None:  # pragma: no cover - sema demands an arm
            raise error("this `match` has no arm to take", node.span)
        self.expr(fallthrough.body)
        for at in ends:
            self.code.patch(at)

    def pattern(self, node: ast.Pattern, slot: int, subject: Quantity) -> None:
        """Emit the test for one arm; leaves a `bool` on the stack."""
        if subject.type is ValType.BOOL:
            # The only patterns a yes-or-no can carry are `true` and
            # `false` (§6.3.5), and testing one against the subject is
            # the subject itself.
            assert isinstance(node, ast.ValuePattern)
            assert isinstance(node.value, ast.BoolLit)
            self.code.emit("load.l", slot)
            if not node.value.value:
                self.code.emit("not")
            return
        suffix = _SUFFIX[subject.type]
        match node:
            case ast.ValuePattern():
                self.code.emit("load.l", slot)
                self.expr(node.value)
                self.code.emit(f"eq.{suffix}")
            case ast.ComparePattern():
                self.code.emit("load.l", slot)
                self.expr(node.value)
                self.code.emit(f"{_COMPARE[node.op]}.{suffix}")
            case ast.RangePattern():
                self.code.emit("load.l", slot)
                self.expr(node.range.low)
                self.code.emit(f"ge.{suffix}")
                self.code.emit("load.l", slot)
                self.expr(node.range.high)
                self.code.emit(f"le.{suffix}")
                self.code.emit("and")
            case _:  # pragma: no cover - the two others are handled above
                raise error("this pattern cannot be compiled yet", node.span)


def _terms(scale: Fraction, addend: Fraction) -> tuple[int, int, int]:
    """`v × scale + addend` as `(v × N + M) / D`, in lowest terms.

    Both halves are exact rationals the profile and the script chose, so
    the three integers are exact too — which is the point of holding a
    unit factor as a fraction rather than as a float.
    """
    multiplier = scale.numerator * addend.denominator
    offset = addend.numerator * scale.denominator
    divisor = scale.denominator * addend.denominator
    common = gcd(gcd(abs(multiplier), abs(offset)), abs(divisor))
    if common > 1:
        multiplier //= common
        offset //= common
        divisor //= common
    return multiplier, offset, divisor


def _decimal(value: Fraction) -> str:
    return str(value.numerator) if value.denominator == 1 else str(float(value))


def _widest(*types: ValType) -> ValType:
    if ValType.F32 in types:
        return ValType.F32
    if ValType.I64 in types:
        return ValType.I64
    return ValType.I32


class _Generator:
    def __init__(
        self,
        program: ast.Program,
        analysis: Analysis,
        profile: Profile,
        registry: Registry,
        entry_name: str,
    ) -> None:
        self.program = program
        self.analysis = analysis
        self.builder = _Builder(profile)
        self.registry = registry
        self.entry_name = entry_name
        self.functions = {f.name: f for f in program.functions}
        self.called: dict[str, set[str]] = {}
        self.function_index: dict[str, int] = {}

    def run(self) -> Container:
        entries: list[tuple[str, ast.Block, Quantity | None]] = []
        if self.program.expression is not None:
            body = ast.Block(
                self.program.expression.span,
                (ast.ExprStmt(self.program.expression.span, self.program.expression),),
            )
            entries.append(
                (self.entry_name, body, self.analysis.type_of(self.program.expression))
            )
        else:
            for entry in self.program.entries:
                entries.append(
                    (entry.name, entry.body, self.analysis.entries.get(entry.name))
                )

        # Entry points come first, then the functions, so that a record's
        # index is stable and a reader of the disassembly meets the
        # invocable ones at the top.
        order = [name for name, _, _ in entries] + [
            f.name for f in self.program.functions
        ]
        self.function_index = {name: i for i, name in enumerate(order)}

        emitted: list[tuple[str, bool, bytes, tuple[ValType, ...], int, ValType]] = []
        for name, body, returns in entries:
            code, locals_, params = _Emit(self, name, (), returns, body).run()
            emitted.append(
                (
                    name,
                    True,
                    code,
                    locals_,
                    params,
                    returns.type if returns else ValType.VOID,
                )
            )
        for declaration in self.program.functions:
            signature = self.analysis.signatures[declaration.name]
            params = tuple(
                (parameter.name, quantity)
                for parameter, quantity in zip(
                    declaration.params, signature.params, strict=True
                )
            )
            code, locals_, count = _Emit(
                self, declaration.name, params, signature.returns, declaration.body
            ).run()
            emitted.append(
                (
                    declaration.name,
                    False,
                    code,
                    locals_,
                    count,
                    signature.returns.type if signature.returns else ValType.VOID,
                )
            )

        caps = self.caps()
        blob = bytearray()
        records: list[Function] = []
        for name, invocable, code, locals_, params, returns in emitted:
            records.append(
                Function(
                    name=name,
                    code_offset=len(blob),
                    return_type=returns,
                    local_types=locals_,
                    invocable=invocable,
                    param_count=params,
                    recursion_cap=caps.get(name, 0),
                )
            )
            blob += code

        container = Container(
            code=bytes(blob),
            constants=list(self.builder.constants),
            functions=records,
            imports=list(self.builder.imports),
            profile_id=self.builder.profile.id,
            profile_major=self.builder.profile.major,
            profile_minor=self.builder.profile.minor,
        )
        container.required_groups = groups_used(container.code)
        facts = analyze(container)
        container.functions = [
            replace(
                fn,
                max_stack=facts[fn.name].max_stack,
                max_call_depth=facts[fn.name].max_call_depth,
                component=facts[fn.name].component,
            )
            for fn in container.functions
        ]
        return container

    def caps(self) -> dict[str, int]:
        """The recursion cap of §6.2.4, one per cycle in the call graph.

        `limit` is required exactly where there is a cycle and refused
        where there is not, may stand on any one function of a cycle,
        and reaches the container on **every** function of it — the
        record is per function and a verifier compares them.
        """
        from .verify import _tarjan

        names = list(self.function_index)
        index_of = {name: i for i, name in enumerate(names)}
        edges: list[set[int]] = [set() for _ in names]
        for caller, callees in self.called.items():
            for callee in callees:
                edges[index_of[caller]].add(index_of[callee])

        declared = {
            f.name: f.limit for f in self.program.functions if f.limit is not None
        }
        spans = {f.name: f.span for f in self.program.functions}
        caps: dict[str, int] = {}
        for component in _tarjan(edges):
            members = [names[i] for i in component]
            cyclic = len(members) > 1 or any(
                index_of[m] in edges[index_of[m]] for m in members
            )
            stated = {m: declared[m] for m in members if m in declared}
            if not cyclic:
                for member, value in stated.items():
                    raise error(
                        f"`{member}` declares a limit and cannot repeat",
                        spans[member],
                        f"`limit {value}` bounds a cycle in the calls, and "
                        f"nothing calls `{member}` back.",
                    )
                continue
            if not stated:
                raise error(
                    f"the calls between {_and(members)} go in a circle with no limit",
                    spans[members[0]],
                    "Write `limit <n>` on one of them, for how deep it may go.",
                )
            if len({v for v in stated.values()}) > 1:
                first, second = sorted(stated)[:2]
                raise error(
                    f"`{first}` and `{second}` are in one circle and declare "
                    f"different limits",
                    spans[second],
                    "One cycle has one limit; put it on either function.",
                )
            value = next(iter(stated.values()))
            for member in members:
                caps[member] = value
        return caps


def _and(names: list[str]) -> str:
    ordered = sorted(names)
    if len(ordered) == 1:
        return f"`{ordered[0]}`"
    return ", ".join(f"`{n}`" for n in ordered[:-1]) + f" and `{ordered[-1]}`"


def compile_script(
    source: str,
    filename: str,
    profile: Profile,
    registry: Registry,
    *,
    entry_name: str = "main",
) -> Container:
    """Text to container, in one call: parse, analyse, generate.

    The three stages are separate modules and stay that way — each is
    testable on its own and each owns a different question — but nobody
    outside this package should have to know the order.
    """
    from .parser import parse
    from .sema import analyse

    program = parse(source, filename)
    analysis = analyse(program, profile, registry)
    return generate(program, analysis, profile, registry, entry_name=entry_name)


def generate(
    program: ast.Program,
    analysis: Analysis,
    profile: Profile,
    registry: Registry,
    *,
    entry_name: str = "main",
) -> Container:
    """A verified container for a script that `analyse` accepted.

    `entry_name` names the entry point of a file that is a single
    expression (§6.2.2), which has no name of its own — a producer takes
    it from the compilation unit, and this is where it is set.
    """
    return _Generator(program, analysis, profile, registry, entry_name).run()
