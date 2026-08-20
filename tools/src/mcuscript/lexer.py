# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0
"""Source text to tokens, per specification §6.1.

Three things here are decisions rather than mechanics, and each is where
the chapter's prose becomes a rule a program can follow.

**A number and its unit suffix are one token** (§6.1.5). That is what
keeps `%` from ever being an operator and what makes `5 min` a different
thing to say than `5min` — the first is two tokens and gets told so.
The lexer does not judge whether a suffix exists in the profile; it
records what was written, and the profile is consulted later.

**`@` on a string is a point in time** (§6.1.7), so nothing inside the
quotes can collide with an operator. The shape is checked here, because
it is lexical; the meaning is the profile's and is not.

**A newline is a statement separator except where it cannot be**
(§6.1.10). A line ending in an operator, an opener or a comma has not
finished, and neither has one whose next token is a closer. The rule
looks backwards and stops there, which is why `} else` belongs on one
line: a `match` arm may begin with `>` or with `else`, so a forward rule
over operators would eat the separator between two arms.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass

from .diagnostics import Span, error

# -- the vocabulary ----------------------------------------------------

KEYWORDS = frozenset(
    {
        "and",
        "break",
        "catch",
        "continue",
        "else",
        "false",
        "fn",
        "for",
        "if",
        "in",
        "invalid",
        "is",
        "let",
        "limit",
        "match",
        "mod",
        "not",
        "on",
        "or",
        "return",
        "true",
        "try",
        "unavailable",
        "while",
    }
)

#: Recognised in a type position and ordinary identifiers everywhere
#: else (§6.5.3), so they are not in `KEYWORDS`.
TYPE_NAMES = frozenset({"i32", "i64", "f32", "bool"})

#: Longest first, so that `<<` is never read as two `<`.
OPERATORS = (
    "->", "..", "<<", ">>", "<=", ">=", "==", "!=", "+=", "-=", "*=", "/=",
    "+", "-", "*", "/", "=", "<", ">", "&", "|", "^", "~",
    "(", ")", "{", "}", "[", "]", ",", ".", ":",
)  # fmt: skip


def is_identifier(text: str) -> bool:
    """Whether a word is an identifier (§6.1.3), keywords not considered.

    The scanner's rule read as a question, for the two callers that have
    a whole word already and no source position: a profile's dimension
    names and a registry's entity names (§7.2.2, §7.3.2).
    """
    if not text or not (text[0].isascii() and (text[0].isalpha() or text[0] == "_")):
        return False
    return all(char.isascii() and (char.isalnum() or char == "_") for char in text)


#: Non-letter characters a unit suffix may contain (§6.1.5). Letters are
#: allowed too, and there Unicode rather than ASCII, because `µs` and `Ω`
#: are units people write and neither is an identifier.
SUFFIX_SYMBOLS = frozenset("%‰°")

#: A newline after one of these cannot be a separator: the statement is
#: not finished yet.
_CONTINUES_AFTER = frozenset(
    set(OPERATORS) - {")", "}", "]"} | {"and", "or", "not", "is", "else",
    "let", "if", "match", "for", "in", "while", "limit", "on", "fn", "mod"}
)  # fmt: skip

#: A newline before one of these is not a separator either — but the set
#: is deliberately tiny, and only closers and joiners are in it.
#:
#: The obvious larger set, "anything that cannot begin a statement", is
#: wrong here and the parser found it: a `match` arm may begin with a
#: comparison (`> 28°C ->`), with `else`, or with a negative number, so
#: suppressing a newline before those swallows the separator between two
#: arms and turns `1` and `> 75% -> 3` into one comparison. Continuation
#: therefore looks backwards only, and `} else` goes on one line.
_CONTINUES_BEFORE = frozenset({")", "]", "}", ",", ".", "->", ".."})

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_HEX = re.compile(r"0[xX][0-9A-Fa-f_]+")
_BIN = re.compile(r"0[bB][01_]+")
_DEC = re.compile(r"[0-9][0-9_]*(\.[0-9][0-9_]*)?([eE][+-]?[0-9]+)?")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_TIME = re.compile(r"\d{2}:\d{2}(:\d{2})?")


class TokenKind(enum.Enum):
    IDENT = "ident"
    KEYWORD = "keyword"
    NUMBER = "number"
    STRING = "string"
    DATETIME = "datetime"
    UNIT = "unit"
    OP = "op"
    NEWLINE = "newline"
    EOF = "eof"


@dataclass(frozen=True)
class Token:
    kind: TokenKind
    text: str
    span: Span
    #: NUMBER only: the unit suffix exactly as written, or "".
    suffix: str = ""
    #: STRING and DATETIME: the contents, with escapes resolved.
    value: str = ""

    def is_op(self, *texts: str) -> bool:
        return self.kind is TokenKind.OP and self.text in texts

    def is_kw(self, *texts: str) -> bool:
        return self.kind is TokenKind.KEYWORD and self.text in texts

    def __str__(self) -> str:
        if self.kind is TokenKind.NEWLINE:
            return "end of line"
        if self.kind is TokenKind.EOF:
            return "end of file"
        return f"`{self.text}{self.suffix}`"


class _Lexer:
    def __init__(self, source: str, file: str) -> None:
        self.src = source
        self.file = file
        self.pos = 0
        self.line = 1
        self.bol = 0  # offset of the beginning of the current line

    # -- position bookkeeping -----------------------------------------

    def _span(self, start: int, line: int, bol: int) -> Span:
        return Span(self.file, start, self.pos, line, start - bol + 1)

    def _here(self) -> Span:
        column = self.pos - self.bol + 1
        return Span(self.file, self.pos, self.pos + 1, self.line, column)

    def _newline(self) -> None:
        self.line += 1
        self.bol = self.pos

    # -- scanning ------------------------------------------------------

    def tokens(self) -> list[Token]:
        raw: list[Token] = []
        while True:
            token = self._next()
            raw.append(token)
            if token.kind is TokenKind.EOF:
                break
        return _filter_newlines(raw)

    def _next(self) -> Token:
        self._skip_blanks()
        if self.pos >= len(self.src):
            return Token(TokenKind.EOF, "", self._here())

        start, line, bol = self.pos, self.line, self.bol
        char = self.src[self.pos]

        if char == "\n":
            self.pos += 1
            span = self._span(start, line, bol)
            self._newline()
            return Token(TokenKind.NEWLINE, "\n", span)

        if char == "@":
            return self._datetime(start, line, bol)

        if char == '"':
            return self._string(start, line, bol)

        if char.isdigit():
            return self._number(start, line, bol)

        match = _IDENT.match(self.src, self.pos)
        if match:
            self.pos = match.end()
            if self.pos < len(self.src) and self.src[self.pos] in SUFFIX_SYMBOLS:
                # A word running straight into `°`, `%` or `‰` is a unit
                # and not a name: `c°C` and `d%` are the spellings a
                # profile uses for hundredths and tenths, and a name
                # cannot contain those characters at all (§6.1.5). This
                # is the argument position of §6.3.10 — glued to a
                # number, a suffix never reaches here.
                return self._unit(start, line, bol)
            text = match.group()
            kind = TokenKind.KEYWORD if text in KEYWORDS else TokenKind.IDENT
            return Token(kind, text, self._span(start, line, bol))

        return self._operator(start, line, bol)

    def _unit(self, start: int, line: int, bol: int) -> Token:
        """One unit spelling, from wherever in it the scan stands."""
        while self.pos < len(self.src):
            char = self.src[self.pos]
            if char.isalpha() or char in SUFFIX_SYMBOLS:
                self.pos += 1
            else:
                break
        span = self._span(start, line, bol)
        return Token(TokenKind.UNIT, self.src[start : self.pos], span)

    def _skip_blanks(self) -> None:
        while self.pos < len(self.src):
            char = self.src[self.pos]
            if char == "\r":
                # CRLF is one line ending and the CR is not a token.
                self.pos += 1
            elif char in " \t":
                self.pos += 1
            elif char == "#":
                while self.pos < len(self.src) and self.src[self.pos] != "\n":
                    self.pos += 1
            else:
                return

    # -- numbers -------------------------------------------------------

    def _number(self, start: int, line: int, bol: int) -> Token:
        for pattern in (_HEX, _BIN):
            match = pattern.match(self.src, self.pos)
            if match:
                self.pos = match.end()
                return self._with_suffix(match.group(), start, line, bol)

        match = _DEC.match(self.src, self.pos)
        assert match is not None  # the caller checked for a digit
        # `2..5` needs no special case: a fraction's dot must be followed
        # by a digit, so the pattern stops at the first `.` of a range.
        self.pos = match.end()
        return self._with_suffix(match.group(), start, line, bol)

    def _with_suffix(self, text: str, start: int, line: int, bol: int) -> Token:
        begin = self.pos
        while self.pos < len(self.src):
            char = self.src[self.pos]
            if char.isalpha() or char in SUFFIX_SYMBOLS:
                self.pos += 1
            else:
                break
        suffix = self.src[begin : self.pos]
        return Token(TokenKind.NUMBER, text, self._span(start, line, bol), suffix)

    # -- strings and points in time --------------------------------------

    def _string(self, start: int, line: int, bol: int) -> Token:
        value = self._quoted(start, line, bol)
        return Token(
            TokenKind.STRING,
            self.src[start : self.pos],
            self._span(start, line, bol),
            value=value,
        )

    def _datetime(self, start: int, line: int, bol: int) -> Token:
        self.pos += 1  # the @
        if self.pos >= len(self.src) or self.src[self.pos] != '"':
            raise error(
                "`@` marks a point in time and must be followed by a quoted one",
                self._span(start, line, bol),
                'For example: @"2026-08-18 13:25".',
            )
        value = self._quoted(self.pos, line, bol)
        span = self._span(start, line, bol)
        _check_datetime(value, span)
        return Token(TokenKind.DATETIME, self.src[start : self.pos], span, value=value)

    def _quoted(self, start: int, line: int, bol: int) -> str:
        self.pos += 1  # the opening quote
        out: list[str] = []
        while True:
            if self.pos >= len(self.src) or self.src[self.pos] == "\n":
                raise error(
                    "this text is never closed",
                    self._span(start, line, bol),
                    "A string ends with the quote it started with, on the same line.",
                )
            char = self.src[self.pos]
            if char == '"':
                self.pos += 1
                return "".join(out)
            if char != "\\":
                out.append(char)
                self.pos += 1
                continue
            self.pos += 1
            out.append(self._escape(line, bol))

    def _escape(self, line: int, bol: int) -> str:
        simple = {'"': '"', "\\": "\\", "n": "\n", "t": "\t"}
        start = self.pos - 1
        if self.pos >= len(self.src):
            raise error("this text is never closed", self._span(start, line, bol))
        char = self.src[self.pos]
        if char in simple:
            self.pos += 1
            return simple[char]
        if char == "u" and self.src[self.pos + 1 : self.pos + 2] == "{":
            end = self.src.find("}", self.pos)
            if end != -1:
                digits = self.src[self.pos + 2 : end]
                if digits and all(c in "0123456789abcdefABCDEF" for c in digits):
                    self.pos = end + 1
                    return chr(int(digits, 16))
        self.pos += 1
        raise error(
            f"`\\{char}` is not one of the escapes this language has",
            self._span(start, line, bol),
            'The escapes are \\" \\\\ \\n \\t and \\u{…}.',
        )

    # -- operators -------------------------------------------------------

    def _operator(self, start: int, line: int, bol: int) -> Token:
        rest = self.src[self.pos :]

        # `&&` and `||` are checked before the table, because `&` and `|`
        # are in it and would otherwise swallow the first half.
        for pair, word in (("&&", "and"), ("||", "or")):
            if rest.startswith(pair):
                self.pos += 2
                raise error(
                    f"`{pair}` is not an operator here",
                    self._span(start, line, bol),
                    f"Write `{word}`.",
                )

        # A unit standing on its own: an argument to one of §6.3.10's
        # conversions. Glued to a number it never reaches here.
        if rest[0] in SUFFIX_SYMBOLS:
            return self._unit(start, line, bol)

        for op in OPERATORS:
            if rest.startswith(op):
                self.pos += len(op)
                return Token(TokenKind.OP, op, self._span(start, line, bol))

        char = rest[0]
        self.pos += 1
        span = self._span(start, line, bol)
        if char == ";":
            return Token(TokenKind.NEWLINE, ";", span)
        advice = {
            "!": ("`!` is not an operator here", "`not` negates, and `!=` compares."),
            "?": (
                "`?` is not an operator here",
                "A conditional is written `if … { … } else { … }`.",
            ),
        }
        if char in advice:
            message, note = advice[char]
            raise error(message, span, note)
        raise error(f"`{char}` means nothing in this language", span)


def split_datetime(value: str) -> tuple[str, str]:
    """The inside of `@"…"` as a date and a time, either of them possibly empty.

    Written once because three readers need it and one of them is not in
    this file: a profile's epoch is the same notation (§7.2.4).
    """
    date, _, time = value.partition(" ") if " " in value else value.partition("T")
    if not time and ":" in date:
        return "", date
    return date, time


def _check_datetime(value: str, span: Span) -> None:
    """§6.1.7 fixes what may stand inside `@"…"`, and nothing else may."""
    date, time = split_datetime(value)
    ok = (
        (_DATE.fullmatch(value) is not None)
        or (_TIME.fullmatch(value) is not None)
        or (_DATE.fullmatch(date) is not None and _TIME.fullmatch(time) is not None)
    )
    if not ok:
        raise error(
            f'"{value}" is not a date or a time this language reads',
            span,
            "The forms are YYYY-MM-DD, hh:mm, hh:mm:ss, and a date and a "
            "time joined by a space or a T.",
        )


def _filter_newlines(raw: list[Token]) -> list[Token]:
    """Drop the newlines §6.1.10 says are not separators.

    Backwards is the rule that carries the weight: a line ending in an
    operator or an opener has not finished. Forwards is a short list of
    closers and joiners, for the same reason and with no ambiguity in
    it — see `_CONTINUES_BEFORE` for why it may not grow.
    """
    out: list[Token] = []
    for index, token in enumerate(raw):
        if token.kind is TokenKind.NEWLINE and token.text == "\n":
            previous = out[-1] if out else None
            if previous is None or previous.kind is TokenKind.NEWLINE:
                continue  # blank lines are not separators either
            if previous.text in _CONTINUES_AFTER:
                continue
            following = _next_real(raw, index + 1)
            if following is not None and following.text in _CONTINUES_BEFORE:
                continue
        out.append(token)
    return out


def _next_real(raw: list[Token], start: int) -> Token | None:
    for token in raw[start:]:
        if token.kind is not TokenKind.NEWLINE:
            return token
    return None


def tokenize(source: str, file: str = "<script>") -> list[Token]:
    """Every token in `source`, ending with one `EOF`."""
    return _Lexer(source, file).tokens()
