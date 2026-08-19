# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0
"""The shape of a parsed script, per specification §6.14.

These nodes carry what was **written** and nothing that was worked out
afterwards. A `Number` holds the numeral and the suffix as they appeared,
not a value in base units; a `Name` holds the dotted parts, not an import
index; an `Annotation` holds a word, not a type. Everything a profile or
an inference pass decides belongs to a later stage, and keeping it out of
here is what lets the parser be checked against the grammar alone.

Every node carries a `span`, because §6.7 makes a diagnostic that can
point at the source a requirement rather than a nicety.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .diagnostics import Span


@dataclass(frozen=True)
class Node:
    span: Span


# -- expressions -------------------------------------------------------


@dataclass(frozen=True)
class Expr(Node):
    pass


@dataclass(frozen=True)
class Number(Expr):
    """A numeral and, if one was glued to it, a unit suffix (§6.1.5).

    `text` is what was written, with any `_` removed; whether it names a
    unit the profile has is not this stage's business.
    """

    text: str
    suffix: str = ""

    @property
    def is_decimal(self) -> bool:
        return "." in self.text or "e" in self.text.lower()


@dataclass(frozen=True)
class Duration(Expr):
    """Suffixed numbers written next to each other are one value (§6.1.6)."""

    parts: tuple[Number, ...]


@dataclass(frozen=True)
class DateTime(Expr):
    """`@"2026-08-18 13:25"` — the fields, with the meaning left open."""

    date: str
    time: str


@dataclass(frozen=True)
class StringLit(Expr):
    value: str


@dataclass(frozen=True)
class BoolLit(Expr):
    value: bool


@dataclass(frozen=True)
class StateLit(Expr):
    """`unavailable` or `invalid` written as a value (§6.3.5).

    A `match` arm may *produce* a state — `invalid -> invalid` — and this
    is the only place in the language where one is written rather than
    arising from an operand. It is also why the container owes two
    instructions that push a chosen state (§6.13).
    """

    state: str


@dataclass(frozen=True)
class Name(Expr):
    """A local, or a dotted import name looked up whole (§6.3.7)."""

    parts: tuple[str, ...]

    @property
    def text(self) -> str:
        return ".".join(self.parts)

    @property
    def is_dotted(self) -> bool:
        return len(self.parts) > 1


@dataclass(frozen=True)
class Unit(Node):
    """A unit standing in an argument position, for §6.3.10's conversions."""

    text: str


@dataclass(frozen=True)
class Unary(Expr):
    op: str
    operand: Expr


@dataclass(frozen=True)
class Binary(Expr):
    op: str
    left: Expr
    right: Expr


@dataclass(frozen=True)
class IsCheck(Expr):
    """`x is valid`, `x is not unavailable` (§6.6.2)."""

    operand: Expr
    state: str
    negated: bool = False


@dataclass(frozen=True)
class Call(Expr):
    callee: Name
    args: tuple[Expr | Unit, ...]


@dataclass(frozen=True)
class Index(Expr):
    target: Expr
    index: Expr | Range


@dataclass(frozen=True)
class Range(Node):
    """`a..b`, inclusive at both ends (§6.3.8). Not a value on its own."""

    low: Expr
    high: Expr


@dataclass(frozen=True)
class If(Expr):
    condition: Expr
    then: Block
    otherwise: Block | If | None = None


@dataclass(frozen=True)
class Match(Expr):
    subject: Expr
    arms: tuple[Arm, ...]


@dataclass(frozen=True)
class Arm(Node):
    pattern: Pattern
    body: Expr


@dataclass(frozen=True)
class Pattern(Node):
    pass


@dataclass(frozen=True)
class ElsePattern(Pattern):
    pass


@dataclass(frozen=True)
class StatePattern(Pattern):
    """`unavailable ->` or `invalid ->` (§6.3.5)."""

    state: str


@dataclass(frozen=True)
class ComparePattern(Pattern):
    op: str
    value: Expr


@dataclass(frozen=True)
class RangePattern(Pattern):
    range: Range


@dataclass(frozen=True)
class ValuePattern(Pattern):
    value: Expr


# -- statements --------------------------------------------------------


@dataclass(frozen=True)
class Stmt(Node):
    pass


@dataclass(frozen=True)
class Block(Node):
    statements: tuple[Stmt, ...]


@dataclass(frozen=True)
class Annotation(Node):
    """One of the four dimensionless types, or a dimension name (§6.5.3)."""

    name: str


@dataclass(frozen=True)
class Let(Stmt):
    name: str
    value: Expr
    annotation: Annotation | None = None


@dataclass(frozen=True)
class Assign(Stmt):
    target: Expr
    op: str
    value: Expr


@dataclass(frozen=True)
class ExprStmt(Stmt):
    value: Expr


@dataclass(frozen=True)
class Return(Stmt):
    value: Expr | None = None


@dataclass(frozen=True)
class Break(Stmt):
    pass


@dataclass(frozen=True)
class Continue(Stmt):
    pass


@dataclass(frozen=True)
class For(Stmt):
    variable: str
    iterable: Range | Expr
    body: Block


# -- declarations ------------------------------------------------------


@dataclass(frozen=True)
class Param(Node):
    name: str
    annotation: Annotation | None = None


@dataclass(frozen=True)
class Function(Node):
    name: str
    params: tuple[Param, ...]
    body: Block
    limit: int | None = None


@dataclass(frozen=True)
class Entry(Node):
    """`on <name> { … }` — what a host calls (§6.2.3)."""

    name: str
    body: Block


@dataclass(frozen=True)
class Program(Node):
    """A file: declarations, or one expression (§6.2.1, §6.2.2)."""

    entries: tuple[Entry, ...] = ()
    functions: tuple[Function, ...] = ()
    #: Set instead of the above when the file is a single expression.
    expression: Expr | None = None
    declaration_order: tuple[Entry | Function, ...] = field(default=())
