# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0
"""Tokens to a syntax tree, per specification §6.14.

Recursive descent, one function per precedence level, in the order
§6.3.1 gives. Nothing here resolves a name, judges a unit or works out a
type: the parser's whole job is to say what was written, and everything
that needs a profile happens later.

Two shapes in the grammar are worth pointing at before reading the code.

**A statement is an expression until an `=` says otherwise.** Assignment
is not an expression (§6.4.2), so the parser reads an expression and
then looks for an assignment operator. That is also what lets `if x = 5`
produce the diagnostic the chapter promises rather than a shrug: a
condition is parsed with assignment explicitly forbidden, and the
refusal names `==`.

**A construct that is planned is parsed and then refused.** `while`,
`try` and `catch` are reserved words with no implementation (§6.0), and
a parser that did not know them would report an unexpected identifier.
Reading them and saying *not yet* is a better answer, and it is what the
reservation was for.
"""

from __future__ import annotations

from . import ast
from .diagnostics import Span, error
from .lexer import Token, TokenKind, split_datetime, tokenize

_COMPARISONS = frozenset({"<", "<=", ">", ">=", "==", "!="})
_ASSIGNMENTS = frozenset({"=", "+=", "-=", "*=", "/="})
#: `unavailable` and `invalid` are keywords; `valid` is contextual
#: and an ordinary identifier everywhere else (§6.14).
_STATE_KEYWORDS = frozenset({"unavailable", "invalid"})


class _Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.pos = 0

    # -- token handling ------------------------------------------------

    @property
    def current(self) -> Token:
        return self.tokens[self.pos]

    def advance(self) -> Token:
        token = self.tokens[self.pos]
        if token.kind is not TokenKind.EOF:
            self.pos += 1
        return token

    def at_op(self, *texts: str) -> bool:
        return self.current.is_op(*texts)

    def at_kw(self, *texts: str) -> bool:
        return self.current.is_kw(*texts)

    def eat_op(self, *texts: str) -> Token | None:
        return self.advance() if self.current.is_op(*texts) else None

    def eat_kw(self, *texts: str) -> Token | None:
        return self.advance() if self.current.is_kw(*texts) else None

    def expect_op(self, text: str, what: str) -> Token:
        if not self.current.is_op(text):
            raise error(
                f"expected `{text}` {what}, found {self.current}",
                self.current.span,
            )
        return self.advance()

    def skip_separators(self) -> None:
        while self.current.kind is TokenKind.NEWLINE:
            self.advance()

    def at_end(self) -> bool:
        return self.current.kind is TokenKind.EOF

    # -- a file ---------------------------------------------------------

    def program(self, span: Span) -> ast.Program:
        self.skip_separators()
        if self.at_end():
            raise error("this script is empty", span)

        # §6.2.2: a file that is a single expression is a program.
        if not (self.at_kw("on", "fn")):
            expression = self.expression()
            self.skip_separators()
            if not self.at_end():
                raise error(
                    f"expected the end of the script, found {self.current}",
                    self.current.span,
                    "A file is either one expression, or a list of `on` and "
                    "`fn` declarations.",
                )
            return ast.Program(span, expression=expression)

        entries: list[ast.Entry] = []
        functions: list[ast.Function] = []
        order: list[ast.Entry | ast.Function] = []
        while not self.at_end():
            declaration = self.declaration()
            order.append(declaration)
            if isinstance(declaration, ast.Entry):
                entries.append(declaration)
            else:
                functions.append(declaration)
            self.skip_separators()
        return ast.Program(
            span,
            entries=tuple(entries),
            functions=tuple(functions),
            declaration_order=tuple(order),
        )

    def declaration(self) -> ast.Entry | ast.Function:
        if keyword := self.eat_kw("on"):
            name = self.identifier("after `on`")
            body = self.block()
            return ast.Entry(keyword.span.to(body.span), name, body)
        if keyword := self.eat_kw("fn"):
            return self.function(keyword)
        raise error(
            f"expected `on` or `fn`, found {self.current}",
            self.current.span,
            "A script is a list of `on` blocks and `fn` definitions.",
        )

    def function(self, keyword: Token) -> ast.Function:
        name = self.identifier("after `fn`")
        self.expect_op("(", "after a function's name")
        params: list[ast.Param] = []
        if not self.at_op(")"):
            while True:
                token = self.current
                param_name = self.identifier("as a parameter")
                annotation = self.annotation()
                params.append(ast.Param(token.span, param_name, annotation))
                if not self.eat_op(","):
                    break
        self.expect_op(")", "after a function's parameters")
        limit = None
        if self.eat_kw("limit"):
            limit = self.whole_number("after `limit`")
        body = self.block()
        return ast.Function(
            keyword.span.to(body.span), name, tuple(params), body, limit
        )

    def identifier(self, where: str) -> str:
        if self.current.kind is not TokenKind.IDENT:
            raise error(
                f"expected a name {where}, found {self.current}", self.current.span
            )
        return self.advance().text

    def whole_number(self, where: str) -> int:
        token = self.current
        if token.kind is not TokenKind.NUMBER or token.suffix or "." in token.text:
            raise error(f"expected a whole number {where}, found {token}", token.span)
        self.advance()
        return int(token.text.replace("_", ""), 0)

    def annotation(self) -> ast.Annotation | None:
        """`: i32` or `: temperature` (§6.5.3). A dimension is a type."""
        if not self.eat_op(":"):
            return None
        token = self.current
        if token.kind is not TokenKind.IDENT:
            raise error(
                f"expected a type after `:`, found {token}",
                token.span,
                "A type is `i32`, `i64`, `f32`, `bool`, or a dimension the "
                "profile declares.",
            )
        self.advance()
        return ast.Annotation(token.span, token.text)

    # -- statements ------------------------------------------------------

    def block(self) -> ast.Block:
        opening = self.expect_op("{", "to open a block")
        statements: list[ast.Stmt] = []
        self.skip_separators()
        while not self.at_op("}"):
            if self.at_end():
                raise error(
                    "this block is never closed",
                    opening.span,
                    "A `{` needs a matching `}`.",
                )
            statements.append(self.statement())
            if not self.at_op("}"):
                self.separator()
            self.skip_separators()
        closing = self.advance()
        return ast.Block(opening.span.to(closing.span), tuple(statements))

    def separator(self) -> None:
        if self.current.kind is not TokenKind.NEWLINE:
            raise error(
                f"expected the end of the statement, found {self.current}",
                self.current.span,
                "Statements are separated by a new line or a `;`.",
            )
        self.advance()

    def statement(self) -> ast.Stmt:
        token = self.current
        if token.is_kw("let"):
            return self.let()
        if token.is_kw("return"):
            self.advance()
            if self.current.kind in (TokenKind.NEWLINE, TokenKind.EOF) or self.at_op(
                "}"
            ):
                return ast.Return(token.span)
            value = self.expression()
            return ast.Return(token.span.to(value.span), value)
        if token.is_kw("break"):
            self.advance()
            return ast.Break(token.span)
        if token.is_kw("continue"):
            self.advance()
            return ast.Continue(token.span)
        if token.is_kw("for"):
            return self.for_loop()
        if token.is_kw("while"):
            raise self.not_yet(token, "while", "for i in 0..99 { … }")
        if token.is_kw("try", "catch"):
            raise self.not_yet(token, token.text, "`else` or `match`")

        target = self.expression()
        if self.current.kind is TokenKind.OP and self.current.text in _ASSIGNMENTS:
            operator = self.advance()
            value = self.expression()
            return ast.Assign(target.span.to(value.span), target, operator.text, value)
        return ast.ExprStmt(target.span, target)

    def not_yet(self, token: Token, what: str, instead: str):
        return error(
            f"`{what}` is planned and not built yet",
            token.span,
            f"Until it is, {instead} says the same thing.",
        )

    def let(self) -> ast.Let:
        keyword = self.advance()
        name = self.identifier("after `let`")
        annotation = self.annotation()
        self.expect_op("=", "after the name in a `let`")
        value = self.expression()
        return ast.Let(keyword.span.to(value.span), name, value, annotation)

    def for_loop(self) -> ast.For:
        keyword = self.advance()
        variable = self.identifier("after `for`")
        if not self.eat_kw("in"):
            raise error(
                f"expected `in` after the loop's name, found {self.current}",
                self.current.span,
                "A loop reads `for i in 0..9 { … }`.",
            )
        iterable = self.range_or_expression()
        body = self.block()
        return ast.For(keyword.span.to(body.span), variable, iterable, body)

    def range_or_expression(self) -> ast.Range | ast.Expr:
        low = self.expression()
        if not self.eat_op(".."):
            return low
        high = self.expression()
        return ast.Range(low.span.to(high.span), low, high)

    # -- expressions -------------------------------------------------------

    def expression(self) -> ast.Expr:
        """§6.3.1's table, one method per row, loosest binding first."""
        value = self.or_expr()
        if self.current.kind is TokenKind.UNIT:
            raise self.stray_unit(self.current)
        return value

    def condition(self, keyword: str) -> ast.Expr:
        """An expression where `=` is a mistake worth naming (§6.4.2)."""
        value = self.expression()
        if self.at_op("="):
            raise error(
                "`=` assigns a value; a condition compares with `==`",
                self.current.span,
                f"Did you mean `==` after `{keyword}`?",
            )
        return value

    def stray_unit(self, token: Token):
        if token.text == "%":
            return error(
                "`%` is a unit suffix and not an operator",
                token.span,
                "Write `mod` for a remainder, or glue the `%` to a number: `75%`.",
            )
        return error(
            f"`{token.text}` is a unit, and a unit belongs to a number",
            token.span,
            f"Write it glued to a number: `5{token.text}`.",
        )

    def _left_assoc(self, operators: tuple[str, ...], operand) -> ast.Expr:
        left = operand()
        while True:
            token = self.current
            if token.kind not in (TokenKind.OP, TokenKind.KEYWORD):
                return left
            if token.text not in operators:
                return left
            self.advance()
            right = operand()
            left = ast.Binary(left.span.to(right.span), token.text, left, right)

    def or_expr(self) -> ast.Expr:
        return self._left_assoc(("or",), self.and_expr)

    def and_expr(self) -> ast.Expr:
        return self._left_assoc(("and",), self.not_expr)

    def not_expr(self) -> ast.Expr:
        """`not` binds looser than comparison: `not a > b` is `not (a > b)`."""
        if keyword := self.eat_kw("not"):
            operand = self.not_expr()
            return ast.Unary(keyword.span.to(operand.span), "not", operand)
        return self.comparison()

    def comparison(self) -> ast.Expr:
        """Non-associative (§6.3.1): `a < b < c` is a mistake, not a chain."""
        left = self.fallback()

        if keyword := self.eat_kw("is"):
            negated = self.eat_kw("not") is not None
            state, span = self.state_name(keyword.span)
            return ast.IsCheck(left.span.to(span), left, state, negated)

        token = self.current
        if not (token.kind is TokenKind.OP and token.text in _COMPARISONS):
            return left
        self.advance()
        right = self.fallback()
        following = self.current
        if following.kind is TokenKind.OP and following.text in _COMPARISONS:
            raise error(
                "two comparisons in a row do not chain here",
                following.span,
                "Write `a < b and b < c`.",
            )
        return ast.Binary(left.span.to(right.span), token.text, left, right)

    def state_name(self, after: Span) -> tuple[str, Span]:
        token = self.current
        text = token.text
        known = token.kind is TokenKind.KEYWORD and text in _STATE_KEYWORDS
        if not known and not (token.kind is TokenKind.IDENT and text == "valid"):
            raise error(
                f"expected `valid`, `unavailable` or `invalid`, found {token}",
                token.span if token.kind is not TokenKind.EOF else after,
            )
        self.advance()
        return text, token.span

    def fallback(self) -> ast.Expr:
        """`a else b` — the validity fallback (§6.3.6)."""
        return self._left_assoc(("else",), self.bit_or)

    def bit_or(self) -> ast.Expr:
        return self._left_assoc(("|",), self.bit_xor)

    def bit_xor(self) -> ast.Expr:
        return self._left_assoc(("^",), self.bit_and)

    def bit_and(self) -> ast.Expr:
        return self._left_assoc(("&",), self.shift)

    def shift(self) -> ast.Expr:
        return self._left_assoc(("<<", ">>"), self.additive)

    def additive(self) -> ast.Expr:
        return self._left_assoc(("+", "-"), self.multiplicative)

    def multiplicative(self) -> ast.Expr:
        return self._left_assoc(("*", "/", "mod"), self.unary)

    def unary(self) -> ast.Expr:
        token = self.current
        if token.is_op("-", "~"):
            self.advance()
            operand = self.unary()
            return ast.Unary(token.span.to(operand.span), token.text, operand)
        return self.postfix()

    def postfix(self) -> ast.Expr:
        value = self.primary()
        while True:
            if self.at_op("("):
                value = self.call(value)
            elif self.at_op("["):
                self.advance()
                index = self.range_or_expression()
                closing = self.expect_op("]", "after an index")
                value = ast.Index(value.span.to(closing.span), value, index)
            else:
                return value

    def call(self, callee: ast.Expr) -> ast.Call:
        if not isinstance(callee, ast.Name):
            raise error("only a name can be called", callee.span)
        self.advance()
        args: list[ast.Expr | ast.Unit] = []
        if not self.at_op(")"):
            while True:
                args.append(self.argument())
                if not self.eat_op(","):
                    break
        closing = self.expect_op(")", "after a call's arguments")
        return ast.Call(callee.span.to(closing.span), callee, tuple(args))

    def argument(self) -> ast.Expr | ast.Unit:
        """§6.14: an argument is an expression, or a unit for §6.3.10.

        A unit spelled with letters — `min`, `lux` — arrives here as an
        ordinary name and is recognised as a unit later, where the
        profile is known. Only a symbol form is unmistakable this early.
        """
        if self.current.kind is TokenKind.UNIT:
            token = self.advance()
            return ast.Unit(token.span, token.text)
        return self.expression()

    def primary(self) -> ast.Expr:
        token = self.current

        if token.kind is TokenKind.NUMBER:
            return self.number()
        if token.kind is TokenKind.STRING:
            self.advance()
            return ast.StringLit(token.span, token.value)
        if token.kind is TokenKind.DATETIME:
            self.advance()
            date, time = split_datetime(token.value)
            return ast.DateTime(token.span, date, time)
        if token.kind is TokenKind.IDENT:
            return self.name()
        if token.is_kw("true", "false"):
            self.advance()
            return ast.BoolLit(token.span, token.text == "true")
        if token.is_kw("unavailable", "invalid"):
            # A state written as a value, which only `match` can use
            # meaningfully (§6.3.5). Where it is meaningless, saying so
            # is a later stage's job — the parser records what was
            # written.
            self.advance()
            return ast.StateLit(token.span, token.text)
        if token.is_kw("if"):
            return self.if_expression()
        if token.is_kw("match"):
            return self.match_expression()
        if token.is_op("("):
            self.advance()
            inner = self.expression()
            self.expect_op(")", "to close a group")
            return inner
        if token.kind is TokenKind.UNIT:
            raise error(
                f"`{token.text}` is a unit, and a unit belongs to a number",
                token.span,
                "Write `mod` for a remainder, or glue the unit on: `75%`."
                if token.text == "%"
                else f"Write it glued to a number: `5{token.text}`.",
            )
        raise error(f"expected a value, found {token}", token.span)

    def number(self) -> ast.Expr:
        first = self.advance()
        head = ast.Number(first.span, first.text.replace("_", ""), first.suffix)
        if not first.suffix:
            # §6.1.5 promises this one by name: `5 min` is two tokens, and
            # nothing else can follow a number on the same line.
            following = self.current
            if following.kind is TokenKind.IDENT:
                raise error(
                    f"`{following.text}` cannot follow a number",
                    following.span,
                    f"A unit is glued to its number: write `{first.text}"
                    f"{following.text}`.",
                )
            return head
        # §6.1.6: suffixed numbers written next to each other are one value.
        parts = [head]
        while self.current.kind is TokenKind.NUMBER and self.current.suffix:
            token = self.advance()
            parts.append(
                ast.Number(token.span, token.text.replace("_", ""), token.suffix)
            )
        if len(parts) == 1:
            return head
        return ast.Duration(parts[0].span.to(parts[-1].span), tuple(parts))

    def name(self) -> ast.Name:
        """A local, or a dotted import name looked up whole (§6.3.7).

        A part after a dot may be a keyword. `fan.on()` is the most
        ordinary line anyone will write in this language's first
        embedding, and entity names belong to the embedder rather than
        to the grammar — nothing but a name can stand after a `.`, so
        there is no ambiguity to protect against.
        """
        first = self.advance()
        parts = [first.text]
        end = first.span
        while self.at_op("."):
            self.advance()
            token = self.current
            if token.kind not in (TokenKind.IDENT, TokenKind.KEYWORD):
                raise error(f"expected a name after `.`, found {token}", token.span)
            self.advance()
            parts.append(token.text)
            end = token.span
        return ast.Name(first.span.to(end), tuple(parts))

    def if_expression(self) -> ast.If:
        keyword = self.advance()
        condition = self.condition("if")
        then = self.block()
        otherwise: ast.Block | ast.If | None = None
        if self.eat_kw("else"):
            otherwise = self.if_expression() if self.at_kw("if") else self.block()
        end = otherwise.span if otherwise is not None else then.span
        return ast.If(keyword.span.to(end), condition, then, otherwise)

    def match_expression(self) -> ast.Match:
        keyword = self.advance()
        subject = self.condition("match")
        self.expect_op("{", "to open a `match`")
        arms: list[ast.Arm] = []
        self.skip_separators()
        while not self.at_op("}"):
            if self.at_end():
                raise error("this `match` is never closed", keyword.span)
            arms.append(self.arm())
            if not self.at_op("}"):
                if self.current.kind is TokenKind.NEWLINE or self.at_op(","):
                    self.advance()
                else:
                    raise error(
                        f"expected the end of the arm, found {self.current}",
                        self.current.span,
                        "Arms are separated by a new line or a `,`.",
                    )
            self.skip_separators()
        closing = self.advance()
        if not arms:
            raise error(
                "a `match` needs at least one arm",
                keyword.span.to(closing.span),
            )
        return ast.Match(keyword.span.to(closing.span), subject, tuple(arms))

    def arm(self) -> ast.Arm:
        pattern = self.pattern()
        self.expect_op("->", "after a pattern")
        body = self.expression()
        return ast.Arm(pattern.span.to(body.span), pattern, body)

    def pattern(self) -> ast.Pattern:
        token = self.current
        if token.is_kw("else"):
            self.advance()
            return ast.ElsePattern(token.span)
        if token.is_kw("unavailable", "invalid"):
            self.advance()
            return ast.StatePattern(token.span, token.text)
        if token.kind is TokenKind.OP and token.text in _COMPARISONS:
            self.advance()
            value = self.bit_or()
            return ast.ComparePattern(token.span.to(value.span), token.text, value)
        value = self.bit_or()
        if self.eat_op(".."):
            high = self.bit_or()
            span = value.span.to(high.span)
            return ast.RangePattern(span, ast.Range(span, value, high))
        return ast.ValuePattern(value.span, value)


def parse(source: str, file: str = "<script>") -> ast.Program:
    """Parse a whole script. Raises `CompileError` on the first mistake."""
    tokens = tokenize(source, file)
    span = Span(file, 0, len(source), 1, 1)
    return _Parser(tokens).program(span)


__all__ = ["parse"]
