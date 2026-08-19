# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0
"""Types, dimensions and units over a parsed script — §6.5 and §6.5.5.

The parser says what was written; this says what it means. It answers
three questions at once, because in this language they are one question:
what type is an expression, what dimension does it carry, and what
number does a literal stand for once its unit is gone.

Two rules do most of the work and both come straight from the chapter.

**A dimension is a type** (§6.5.3). A temperature is not an `i32` even
where a profile holds it in one, so `Quantity` pairs the two and nothing
compares the halves separately.

**The data type follows the dimension** (§6.5.5). A dimensioned result
carries its profile's declared data type; a result with none carries its
operands' type, except that a division produces `f32`. That single rule
is why `(a + b) / 2` on two temperatures is a temperature and
`current / baseline` on two temperatures is a decimal.

What this stage does **not** do, and says so rather than pretending:
strings and arrays are planned (§6.10, §6.9) and refused here by name;
a date literal is type-checked against the profile's calendar dimension
but not turned into a number, because that needs an epoch and the
profile format is M4's.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from . import ast
from .diagnostics import Span, error
from .opcodes import ValType
from .profile import Dimension, Profile, Unit
from .registry import Entity, HostFunction, Quantity, Registry, nearest


def _decimal(value: Fraction) -> str:
    """A fraction as a person would write it, for a diagnostic."""
    if value.denominator == 1:
        return str(value.numerator)
    text = f"{float(value):.10f}".rstrip("0")
    return text.rstrip(".") if text != "0." else "0"


BOOL = Quantity(ValType.BOOL)
I32 = Quantity(ValType.I32)
I64 = Quantity(ValType.I64)
F32 = Quantity(ValType.F32)

_INTEGERS = (ValType.I32, ValType.I64)
_CONVERSIONS = {"to_i32": ValType.I32, "to_i64": ValType.I64, "to_f32": ValType.F32}
_ONE_OPERAND = ("round", "trunc", "abs")
_PLANNED_BUILTINS = ("min", "max")


class _Pending:
    """The return type of a function that is still being inferred.

    A directly recursive function has one, and it is resolved by the arm
    of the `if` or `match` that does not recurse. One that survives to
    the top is an error rather than a guess.
    """

    def __repr__(self) -> str:  # pragma: no cover - debugging only
        return "<pending>"


PENDING = _Pending()

Inferred = Quantity | _Pending


@dataclass
class Signature:
    name: str
    params: tuple[Quantity, ...]
    returns: Quantity | None
    span: Span
    #: The call that fixed the parameter types, for the second opinion.
    fixed_by: Span | None = None


@dataclass
class Analysis:
    """What the pass learned, keyed by node identity."""

    types: dict[int, Quantity] = field(default_factory=dict)
    #: A literal's value in its dimension's base unit, exactly.
    values: dict[int, Fraction] = field(default_factory=dict)
    #: Which import a dotted name turned out to be.
    imports: dict[int, Entity | HostFunction] = field(default_factory=dict)
    signatures: dict[str, Signature] = field(default_factory=dict)

    def type_of(self, node: ast.Node) -> Quantity:
        return self.types[id(node)]


class _Scope:
    def __init__(self, parent: _Scope | None = None) -> None:
        self.parent = parent
        self.names: dict[str, Quantity] = {}

    def lookup(self, name: str) -> Quantity | None:
        scope: _Scope | None = self
        while scope is not None:
            if name in scope.names:
                return scope.names[name]
            scope = scope.parent
        return None

    def declare(self, name: str, quantity: Quantity) -> None:
        self.names[name] = quantity

    def visible(self) -> list[str]:
        out: list[str] = []
        scope: _Scope | None = self
        while scope is not None:
            out.extend(scope.names)
            scope = scope.parent
        return out


class _Analyser:
    def __init__(self, program: ast.Program, profile: Profile, registry: Registry):
        self.program = program
        self.profile = profile
        self.registry = registry
        self.out = Analysis()
        self.functions = {f.name: f for f in program.functions}
        self.in_progress: dict[str, Signature] = {}
        self.loop_depth = 0

    # -- entry point ----------------------------------------------------

    def run(self) -> Analysis:
        if self.program.expression is not None:
            self.expr(self.program.expression, _Scope())
            return self.out
        seen: dict[str, Span] = {}
        for entry in self.program.entries:
            if entry.name in seen:
                raise error(
                    f"there are two entry points called `{entry.name}`", entry.span
                )
            seen[entry.name] = entry.span
        for entry in self.program.entries:
            self.block(entry.body, _Scope())
        for function in self.program.functions:
            if function.name not in self.out.signatures:
                raise error(
                    f"nothing calls `{function.name}`",
                    function.span,
                    "A function only an entry point can reach is what a "
                    "container may hold; one nothing reaches is not.",
                )
        return self.out

    # -- statements -------------------------------------------------------

    def block(self, node: ast.Block, outer: _Scope) -> Inferred | None:
        """A block's value is its last expression, or nothing (§6.4.5)."""
        scope = _Scope(outer)
        last: Inferred | None = None
        for statement in node.statements:
            last = self.statement(statement, scope)
        if node.statements and isinstance(node.statements[-1], ast.ExprStmt):
            return last
        return None

    def statement(self, node: ast.Stmt, scope: _Scope) -> Inferred | None:
        match node:
            case ast.Let():
                expected = self.annotation(node.annotation) if node.annotation else None
                value = self.demand(node.value, scope, expected)
                if expected is not None and value != expected:
                    raise self.mismatch(node.value.span, expected, value)
                if scope.lookup(node.name) is not None:
                    raise error(f"`{node.name}` is already a name here", node.span)
                if self.registry.find(node.name) is not None:
                    raise error(
                        f"`{node.name}` is already an entity",
                        node.span,
                        "A `let` may not take a name the host already uses.",
                    )
                scope.declare(node.name, value)
                return None
            case ast.Assign():
                self.assignment(node, scope)
                return None
            case ast.ExprStmt():
                # Not `demand`: a recursive call in tail position is
                # still pending here, and the caller resolves it.
                return self.expr(node.value, scope, None)
            case ast.Return():
                if node.value is not None:
                    self.demand(node.value, scope, None)
                return None
            case ast.Break() | ast.Continue():
                if self.loop_depth == 0:
                    word = "break" if isinstance(node, ast.Break) else "continue"
                    raise error(f"`{word}` is only meaningful inside a loop", node.span)
                return None
            case ast.For():
                self.for_loop(node, scope)
                return None
        raise error("this statement is not understood yet", node.span)

    def assignment(self, node: ast.Assign, scope: _Scope) -> None:
        if not isinstance(node.target, ast.Name):
            raise error("only a name can be assigned to", node.target.span)
        name = node.target.text
        local = None if node.target.is_dotted else scope.lookup(name)
        if local is not None:
            target = local
        else:
            found = self.resolve(node.target, scope)
            if isinstance(found, HostFunction):
                raise error(f"`{name}` is something to call, not to set", node.span)
            if not found.writable:
                raise error(
                    f"`{name}` can be read but not set",
                    node.span,
                    "The host declares which entities a script may write.",
                )
            target = found.quantity
        self.out.types[id(node.target)] = target
        value = self.demand(node.value, scope, target)
        if node.op != "=":
            value = self.binary_result(
                node.op[0], target, value, node.span, node.value.span
            )
        if value != target:
            raise self.mismatch(node.value.span, target, value)

    def for_loop(self, node: ast.For, scope: _Scope) -> None:
        if not isinstance(node.iterable, ast.Range):
            raise error(
                "a loop runs over a range",
                node.iterable.span,
                "Write `for i in 0..9 { … }`. Looping over an array is "
                "planned and not built.",
            )
        low = self.demand(node.iterable.low, scope, None)
        high = self.demand(node.iterable.high, scope, low)
        for quantity, span in (
            (low, node.iterable.low.span),
            (high, node.iterable.high.span),
        ):
            if quantity.dimension is not None or quantity.type not in _INTEGERS:
                raise error(
                    f"a range counts in whole numbers, and this is {quantity}", span
                )
        if low.type != high.type:
            raise self.mismatch(node.iterable.high.span, low, high)
        inner = _Scope(scope)
        inner.declare(node.variable, low)
        self.loop_depth += 1
        self.block(node.body, inner)
        self.loop_depth -= 1

    # -- expressions -------------------------------------------------------

    def demand(
        self, node: ast.Expr, scope: _Scope, expected: Quantity | None
    ) -> Quantity:
        """Infer, and refuse a type that is still pending."""
        result = self.expr(node, scope, expected)
        if isinstance(result, _Pending):
            raise error(
                "this value's type cannot be worked out",
                node.span,
                "A recursive function needs a path that does not recurse "
                "for its type to come from.",
            )
        return result

    def expr(
        self, node: ast.Expr, scope: _Scope, expected: Quantity | None = None
    ) -> Inferred:
        result = self._expr(node, scope, expected)
        if isinstance(result, Quantity):
            self.out.types[id(node)] = result
        return result

    def _expr(
        self, node: ast.Expr, scope: _Scope, expected: Quantity | None
    ) -> Inferred:
        match node:
            case ast.Number():
                return self.number(node, expected)
            case ast.Duration():
                return self.duration(node)
            case ast.DateTime():
                return self.datetime(node)
            case ast.BoolLit():
                return BOOL
            case ast.StateLit():
                if expected is None:
                    raise error(
                        f"`{node.state}` needs to know which kind of value it is",
                        node.span,
                        "Write it where the type is already fixed — a `match` "
                        "arm beside a value, or an entity being set.",
                    )
                return expected
            case ast.StringLit():
                raise error(
                    "text is not a value this language holds yet",
                    node.span,
                    "Strings are planned. A literal will be usable as an "
                    "argument to a host function first.",
                )
            case ast.Name():
                return self.name(node, scope)
            case ast.Unary():
                return self.unary(node, scope, expected)
            case ast.Binary():
                return self.binary(node, scope, expected)
            case ast.IsCheck():
                self.demand(node.operand, scope, None)
                return BOOL
            case ast.Call():
                return self.call(node, scope)
            case ast.Index():
                raise error(
                    "arrays are planned and not built",
                    node.span,
                    "Until they are, one entity per value is the way.",
                )
            case ast.If():
                return self.if_expr(node, scope, expected)
            case ast.Match():
                return self.match_expr(node, scope, expected)
        raise error("this expression is not understood yet", node.span)

    # -- literals ----------------------------------------------------------

    def number(self, node: ast.Number, expected: Quantity | None) -> Quantity:
        if not node.suffix:
            value = (
                Fraction(node.text) if node.is_decimal else Fraction(int(node.text, 0))
            )
            self.out.values[id(node)] = value
            if node.is_decimal:
                return F32
            # A whole numeral takes the type the place around it needs,
            # which is how `let total: i64 = 0` works without a suffix
            # for literals (§6.5.3).
            adaptable = expected is not None and expected.dimension is None
            if adaptable and expected.type in (*_INTEGERS, ValType.F32):
                return expected
            return I32
        dimension, unit = self.unit_of(node.suffix, node.span)
        value = Fraction(node.text) if node.is_decimal else Fraction(int(node.text, 0))
        self.out.values[id(node)] = self.normalize(
            value, dimension, unit, node.span, node.text
        )
        return Quantity(dimension.type, dimension)

    def normalize(
        self,
        written: Fraction,
        dimension: Dimension,
        unit: Unit,
        span: Span,
        text: str,
    ) -> Fraction:
        base = written * unit.factor + unit.offset
        if dimension.is_integer and base.denominator != 1:
            step = _decimal(Fraction(1) / unit.factor)
            raise error(
                f"{text}{unit.spelling} is finer than {dimension.name} is held",
                span,
                f"This profile counts {dimension.name} in whole "
                f"{dimension.base_unit}, so its smallest step is "
                f"{step}{unit.spelling}.",
            )
        return base

    def duration(self, node: ast.Duration) -> Quantity:
        dimension, unit = self.unit_of(node.parts[0].suffix, node.parts[0].span)
        total = Fraction(0)
        previous = unit.factor
        seen = {unit.spelling}
        for index, part in enumerate(node.parts):
            part_dimension, part_unit = self.unit_of(part.suffix, part.span)
            if part_dimension is not dimension:
                raise error(
                    f"`{part.suffix}` is {part_dimension.name} and "
                    f"`{node.parts[0].suffix}` is {dimension.name}",
                    part.span,
                    "The parts written next to each other must be one kind "
                    "of quantity.",
                )
            if part_unit.is_affine:
                raise error(
                    f"`{part.suffix}` cannot be one part of a larger value",
                    part.span,
                    "A unit with an offset only means something on its own.",
                )
            if index and part.suffix in seen:
                raise error(f"`{part.suffix}` is written twice", part.span)
            if index and part_unit.factor >= previous:
                raise error(
                    f"`{part.suffix}` is not smaller than the part before it",
                    part.span,
                    "Parts are written from the largest to the smallest.",
                )
            seen.add(part.suffix)
            previous = part_unit.factor
            value = Fraction(part.text) if part.is_decimal else Fraction(int(part.text))
            total += self.normalize(value, dimension, part_unit, part.span, part.text)
        self.out.values[id(node)] = total
        return Quantity(dimension.type, dimension)

    def datetime(self, node: ast.DateTime) -> Quantity:
        calendar = self.profile.calendar
        if calendar is None:
            raise error(
                "this profile has no calendar, so a date means nothing here",
                node.span,
                f"The profile `{self.profile.name}` declares no dimension "
                "for points in time.",
            )
        return Quantity(calendar.type, calendar)

    def unit_of(self, spelling: str, span: Span) -> tuple[Dimension, Unit]:
        found = self.profile.find_unit(spelling)
        if found is None:
            known = self.profile.unit_spellings
            suggestions = nearest(spelling, known)
            note = (
                f"Did you mean {' or '.join('`' + s + '`' for s in suggestions)}?"
                if suggestions
                else f"The profile `{self.profile.name}` declares no such unit."
            )
            raise error(f"`{spelling}` is not a unit here", span, note)
        return found

    # -- names --------------------------------------------------------------

    def name(self, node: ast.Name, scope: _Scope) -> Quantity:
        if not node.is_dotted:
            local = scope.lookup(node.text)
            if local is not None:
                return local
        found = self.resolve(node, scope)
        if isinstance(found, HostFunction):
            raise error(
                f"`{node.text}` is something to call",
                node.span,
                f"Write `{node.text}()`.",
            )
        if not found.readable:
            raise error(f"`{node.text}` can be set but not read", node.span)
        return found.quantity

    def resolve(self, node: ast.Name, scope: _Scope) -> Entity | HostFunction:
        found = self.registry.find(node.text)
        if found is not None:
            self.out.imports[id(node)] = found
            return found
        candidates = tuple(self.registry.names) + tuple(scope.visible())
        suggestions = nearest(node.text, candidates)
        note = (
            f"Did you mean {' or '.join('`' + s + '`' for s in suggestions)}?"
            if suggestions
            else "The host declares what a script may reach."
        )
        raise error(f"there is no `{node.text}`", node.span, note)

    # -- operators ------------------------------------------------------------

    def unary(
        self, node: ast.Unary, scope: _Scope, expected: Quantity | None
    ) -> Quantity:
        if node.op == "not":
            operand = self.demand(node.operand, scope, BOOL)
            if operand != BOOL:
                raise error(
                    f"`not` needs a yes-or-no, and this is {operand}",
                    node.operand.span,
                )
            return BOOL
        operand = self.demand(node.operand, scope, expected)
        if node.op == "-":
            if operand.type is ValType.BOOL:
                raise error("a yes-or-no has no negative", node.operand.span)
            return operand
        if operand.dimension is not None or operand.type not in _INTEGERS:
            raise error(
                f"`~` flips the bits of a whole number, and this is {operand}",
                node.operand.span,
            )
        return operand

    def binary(
        self, node: ast.Binary, scope: _Scope, expected: Quantity | None
    ) -> Inferred:
        if node.op in ("and", "or"):
            for side in (node.left, node.right):
                quantity = self.demand(side, scope, BOOL)
                if quantity != BOOL:
                    raise error(
                        f"`{node.op}` needs a yes-or-no, and this is {quantity}",
                        side.span,
                    )
            return BOOL
        if node.op == "else":
            left = self.expr(node.left, scope, expected)
            right = self.expr(
                node.right, scope, left if isinstance(left, Quantity) else expected
            )
            if isinstance(left, _Pending):
                return right
            if isinstance(right, _Pending):
                return left
            if left != right:
                raise error(
                    f"the fallback is {right} where the value is {left}",
                    node.right.span,
                    "Both sides of `else` have to be the same kind of thing.",
                )
            return left
        left = self.demand(node.left, scope, None)
        right = self.demand(
            node.right, scope, left if node.op not in ("*", "/") else None
        )
        return self.binary_result(node.op, left, right, node.span, node.right.span)

    def binary_result(
        self, op: str, left: Quantity, right: Quantity, span: Span, right_span: Span
    ) -> Quantity:
        if op in ("<", "<=", ">", ">=", "==", "!="):
            if left.dimension is not right.dimension or left.type != right.type:
                raise self.incomparable(right_span, left, right)
            return BOOL
        if op in ("&", "|", "^", "<<", ">>"):
            for quantity, where in ((left, span), (right, right_span)):
                if quantity.dimension is not None or quantity.type not in _INTEGERS:
                    raise error(
                        f"`{op}` works on plain whole numbers, and this is {quantity}",
                        where,
                    )
            if op in ("&", "|", "^") and left.type != right.type:
                raise self.mismatch(right_span, left, right)
            return left
        return self.arithmetic(op, left, right, span, right_span)

    def arithmetic(
        self, op: str, left: Quantity, right: Quantity, span: Span, right_span: Span
    ) -> Quantity:
        if left.type is ValType.BOOL or right.type is ValType.BOOL:
            raise error(f"`{op}` does not work on a yes-or-no", span)

        # §6.5.5.1: a scale factor on the right of `+` or `-` is a
        # relative change, and on either side of `*` or `/` it scales.
        if op in ("+", "-") and right.is_scale and not left.is_scale:
            return left
        if op in ("+", "-") and left.is_scale and not right.is_scale:
            raise error(
                f"a ratio cannot have {right} added to it",
                right_span,
                f"`x {op} 5%` changes `x` by five percent; the other way "
                "round has no meaning.",
            )
        if op in ("*", "/") and right.is_scale and not left.is_scale:
            return left
        if op == "*" and left.is_scale and not right.is_scale:
            return right

        if op in ("+", "-", "mod"):
            crossed = left.dimension is not right.dimension
            if crossed and (op != "mod" or right.dimension is not None):
                raise self.incomparable(right_span, left, right)
            if left.dimension is None and left.type != right.type:
                raise self.mismatch(right_span, left, right)
            return left
        if op == "*":
            if left.dimension is not None and right.dimension is not None:
                raise error(
                    f"{left} times {right} is not a quantity this language has",
                    span,
                    "At most one side of a multiplication carries a unit.",
                )
            if left.dimension is None and right.dimension is None:
                if left.type != right.type:
                    raise self.mismatch(right_span, left, right)
                return left
            return left if left.dimension is not None else right
        if op == "/":
            if left.dimension is not None and left.dimension is right.dimension:
                return F32
            if right.dimension is not None:
                raise error(
                    f"{left} divided by {right} is not a quantity this language has",
                    span,
                    "A division either shares its dimension with the other "
                    "side or has none.",
                )
            if left.dimension is not None:
                return left
            return F32
        raise error(f"`{op}` is not an operator here", span)

    # -- calls ----------------------------------------------------------------

    def call(self, node: ast.Call, scope: _Scope) -> Inferred:
        name = node.callee.text
        if name in _CONVERSIONS:
            return self.conversion(node, scope, _CONVERSIONS[name])
        if name == "to_unit":
            return self.to_unit(node, scope)
        if name in _ONE_OPERAND:
            return self.one_operand(node, scope)
        if name in _PLANNED_BUILTINS:
            raise error(
                f"`{name}` is planned and not built yet",
                node.span,
                f"Until it is, `if a < b {{ a }} else {{ b }}` says what "
                f"`{name}` would.",
            )
        if not node.callee.is_dotted and self.functions.get(name) is not None:
            return self.own_function(node, scope)
        found = self.resolve(node.callee, scope)
        if isinstance(found, Entity):
            raise error(f"`{name}` is a value, not something to call", node.span)
        if len(node.args) != len(found.params):
            raise error(
                f"`{name}` takes {len(found.params)} and was given {len(node.args)}",
                node.span,
            )
        for argument, want in zip(node.args, found.params, strict=True):
            if isinstance(argument, ast.Unit):
                raise error("a unit is not an argument here", argument.span)
            got = self.demand(argument, scope, want)
            if got != want:
                raise self.mismatch(argument.span, want, got)
        if found.returns is None:
            return Quantity(ValType.VOID)
        return found.returns

    def own_function(self, node: ast.Call, scope: _Scope) -> Inferred:
        declaration = self.functions[node.callee.text]
        arguments = [
            self.demand(a, scope, None)
            for a in node.args
            if not isinstance(a, ast.Unit)
        ]
        if len(arguments) != len(declaration.params):
            raise error(
                f"`{declaration.name}` takes {len(declaration.params)} and "
                f"was given {len(arguments)}",
                node.span,
            )
        known = self.out.signatures.get(declaration.name)
        if known is not None:
            if tuple(arguments) != known.params:
                raise error(
                    f"`{declaration.name}` is used with two different kinds of value",
                    node.span,
                    f"It was first used at line {known.fixed_by.line} with "
                    f"{', '.join(str(p) for p in known.params)}.",
                )
            return (
                known.returns if known.returns is not None else Quantity(ValType.VOID)
            )
        if declaration.name in self.in_progress:
            return PENDING
        return self.infer_function(declaration, tuple(arguments), node.span)

    def infer_function(
        self, declaration: ast.Function, arguments: tuple[Quantity, ...], call: Span
    ) -> Quantity:
        signature = Signature(declaration.name, arguments, None, declaration.span, call)
        self.in_progress[declaration.name] = signature
        scope = _Scope()
        for param, quantity in zip(declaration.params, arguments, strict=True):
            if param.annotation is not None:
                declared = self.annotation(param.annotation)
                if declared != quantity:
                    raise self.mismatch(param.span, declared, quantity)
            scope.declare(param.name, quantity)
        result = self.block(declaration.body, scope)
        del self.in_progress[declaration.name]
        signature.returns = result
        self.out.signatures[declaration.name] = signature
        return result if result is not None else Quantity(ValType.VOID)

    def one_operand(self, node: ast.Call, scope: _Scope) -> Quantity:
        name = node.callee.text
        if len(node.args) != 1 or isinstance(node.args[0], ast.Unit):
            raise error(f"`{name}` takes one value", node.span)
        operand = self.demand(node.args[0], scope, None)
        if operand.type is ValType.BOOL:
            raise error(f"`{name}` needs a number, and this is a yes-or-no", node.span)
        if name == "abs":
            return operand
        if operand.type is not ValType.F32:
            raise error(
                f"`{name}` turns a decimal into a whole number, and this is "
                f"already whole",
                node.span,
            )
        if operand.dimension is not None:
            return Quantity(operand.dimension.type, operand.dimension)
        return I32

    # -- §6.3.10 conversions -----------------------------------------------

    def conversion(self, node: ast.Call, scope: _Scope, target: ValType) -> Quantity:
        """`to_i32(x, °C, 100)` — a quantity becomes a plain number.

        The result never carries a dimension: that is what crossing out
        of the dimension system means. Whether the arithmetic rounds is
        §6.3.10's business, and the conversion does it without being
        asked, so nothing is refused here for being inexact.
        """
        name = node.callee.text
        value, dimension, unit, _factor = self.crossing(node, scope, name)
        if dimension is None and unit is not None:
            raise error(
                f"this is {value} and has no unit to count in",
                node.args[1].span,
            )
        return Quantity(target)

    def to_unit(self, node: ast.Call, scope: _Scope) -> Quantity:
        if len(node.args) not in (2, 3):
            raise error("`to_unit` takes a number and a unit", node.span)
        value = self.demand(node.args[0], scope, None)
        if value.dimension is not None:
            raise error(
                f"`to_unit` builds a quantity out of a plain number, and "
                f"this is already {value}",
                node.args[0].span,
            )
        dimension, _unit = self.written_unit(node.args[1])
        self.factor_of(node, 2)
        return Quantity(dimension.type, dimension)

    def crossing(
        self, node: ast.Call, scope: _Scope, name: str
    ) -> tuple[Quantity, Dimension | None, Unit | None, Fraction]:
        if not node.args:
            raise error(f"`{name}` takes a value", node.span)
        value = self.demand(node.args[0], scope, None)
        if value.type is ValType.BOOL:
            raise error(f"`{name}` needs a number", node.args[0].span)
        factor = self.factor_of(node, 2)
        if value.dimension is None:
            if len(node.args) > 1:
                return value, None, self.written_unit(node.args[1])[1], factor
            return value, None, None, factor
        if len(node.args) < 2:
            raise error(
                f"`{name}` needs to know which unit to count {value} in",
                node.span,
                f"Write `{name}(…, {value.dimension.base_unit or 'unit'})`.",
            )
        dimension, unit = self.written_unit(node.args[1])
        if dimension is not value.dimension:
            raise error(
                f"this is {value} and `{unit.spelling}` is {dimension.name}",
                node.args[1].span,
            )
        return value, dimension, unit, factor

    def written_unit(self, node: ast.Expr | ast.Unit) -> tuple[Dimension, Unit]:
        if isinstance(node, ast.Unit):
            return self.unit_of(node.text, node.span)
        if isinstance(node, ast.Name) and not node.is_dotted:
            return self.unit_of(node.text, node.span)
        raise error("this is not a unit", node.span)

    def factor_of(self, node: ast.Call, index: int) -> Fraction:
        if len(node.args) <= index:
            return Fraction(1)
        written = node.args[index]
        if not isinstance(written, ast.Number) or written.suffix:
            raise error(
                "a resolution is written as a plain number",
                written.span,
                "For example `100` for hundredths.",
            )
        return Fraction(written.text)

    # -- if and match ---------------------------------------------------------

    def if_expr(
        self, node: ast.If, scope: _Scope, expected: Quantity | None
    ) -> Inferred:
        condition = self.demand(node.condition, scope, BOOL)
        if condition != BOOL:
            raise error(
                f"`if` needs a yes-or-no, and this is {condition}",
                node.condition.span,
                "A comparison makes one: `temp > 25°C`.",
            )
        then = self.block(node.then, scope)
        if node.otherwise is None:
            return Quantity(ValType.VOID)
        if isinstance(node.otherwise, ast.If):
            other = self.expr(node.otherwise, scope, expected or then)
        else:
            other = self.block(node.otherwise, scope)
        if then is None or other is None:
            return Quantity(ValType.VOID)
        if isinstance(then, _Pending):
            return other
        if isinstance(other, _Pending):
            return then
        if then != other:
            raise error(
                f"one arm is {then} and the other is {other}",
                node.span,
                "Both arms of an `if` used for its value give the same kind of thing.",
            )
        return then

    def match_expr(
        self, node: ast.Match, scope: _Scope, expected: Quantity | None
    ) -> Inferred:
        subject = self.demand(node.subject, scope, None)
        result: Inferred | None = expected
        has_else = False
        for arm in node.arms:
            self.pattern(arm.pattern, subject, scope)
            if isinstance(arm.pattern, ast.ElsePattern):
                has_else = True
            value = self.expr(
                arm.body, scope, result if isinstance(result, Quantity) else None
            )
            if isinstance(value, _Pending):
                continue
            if result is None or isinstance(result, _Pending):
                result = value
            elif value != result:
                raise error(
                    f"this arm is {value} where the others are {result}",
                    arm.body.span,
                    "Every arm of a `match` gives the same kind of thing.",
                )
        if not has_else and subject.type is not ValType.BOOL:
            raise error(
                "this `match` has no `else`",
                node.span,
                "Add `else -> …` for the values the arms do not name.",
            )
        return result if result is not None else Quantity(ValType.VOID)

    def pattern(self, node: ast.Pattern, subject: Quantity, scope: _Scope) -> None:
        match node:
            case ast.ElsePattern() | ast.StatePattern():
                return
            case ast.ComparePattern():
                value = self.demand(node.value, scope, subject)
                if value != subject:
                    raise self.incomparable(node.value.span, subject, value)
            case ast.ValuePattern():
                value = self.demand(node.value, scope, subject)
                if value != subject:
                    raise self.incomparable(node.value.span, subject, value)
            case ast.RangePattern():
                for end in (node.range.low, node.range.high):
                    value = self.demand(end, scope, subject)
                    if value != subject:
                        raise self.incomparable(end.span, subject, value)

    # -- annotations and diagnostics -------------------------------------------

    def annotation(self, node: ast.Annotation) -> Quantity:
        plain = {
            "i32": ValType.I32,
            "i64": ValType.I64,
            "f32": ValType.F32,
            "bool": ValType.BOOL,
        }
        if node.name in plain:
            return Quantity(plain[node.name])
        dimension = self.profile.find_dimension(node.name)
        if dimension is None:
            known = tuple(plain) + tuple(d.name for d in self.profile.dimensions)
            suggestions = nearest(node.name, known)
            note = (
                f"Did you mean {' or '.join('`' + s + '`' for s in suggestions)}?"
                if suggestions
                else "A type is `i32`, `i64`, `f32`, `bool`, or a dimension "
                "the profile declares."
            )
            raise error(f"`{node.name}` is not a type here", node.span, note)
        return Quantity(dimension.type, dimension)

    def mismatch(self, span: Span, want: Quantity, got: Quantity):
        if want.dimension is None and got.dimension is None:
            return error(
                f"this is {got} where {want} is needed",
                span,
                f"Numbers do not change kind on their own; write `to_{want.type}(…)`.",
            )
        return error(f"this is {got} where {want} is needed", span)

    def incomparable(self, span: Span, left: Quantity, right: Quantity):
        if left.dimension is not right.dimension:
            return error(
                f"{left} and {right} are different kinds of quantity",
                span,
                "Only two of the same kind can be compared or added.",
            )
        return self.mismatch(span, left, right)


def analyse(
    program: ast.Program,
    profile: Profile,
    registry: Registry,
) -> Analysis:
    """Type and dimension a parsed script, or refuse it."""
    return _Analyser(program, profile, registry).run()
