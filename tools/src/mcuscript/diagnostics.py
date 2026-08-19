# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0
"""Where a compiler says what went wrong.

Specification §6.7 makes diagnostics part of the language rather than a
quality of one implementation, and states three obligations: name the
thing and say what to do, never cite the specification in a message, and
say what was expected in the words of the language. This module is what
the rest of the front end says it through, and its shape follows from
those three.

A `Diagnostic` therefore has two halves. The **message** names what is
wrong, in one sentence. The **notes** say what to do about it, and they
are separate rather than appended so that nothing is tempted to write a
paragraph where a command belongs.

Errors are raised rather than collected, one at a time. That is a real
limitation — a script with four mistakes reports one, is fixed, and
reports the next — and it is recorded here rather than hidden because
recovery is a design problem of its own: a parser that guesses where a
statement resumed can invent errors that are worse than the one it
recovered from. The type carries a list so that recovery can arrive
without changing every call site.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Span:
    """A stretch of source, in characters, with its line and column.

    Offsets are into the source string as Python sees it, so a `°` is
    one unit and not two. Line and column are 1-based, because they are
    for people.
    """

    file: str
    start: int
    end: int
    line: int
    column: int

    def to(self, other: Span) -> Span:
        """The span reaching from the start of this one to the end of that."""
        return Span(self.file, self.start, other.end, self.line, self.column)

    def __str__(self) -> str:
        return f"{self.file}:{self.line}:{self.column}"


@dataclass(frozen=True)
class Diagnostic:
    """One thing that is wrong, and what to do about it."""

    message: str
    span: Span
    notes: tuple[str, ...] = ()

    def render(self, source: str) -> str:
        """The message with the offending line under it, Elm-style.

        The caret is what makes a diagnostic usable by somebody who did
        not write the compiler: it answers *where* before the sentence
        has to.
        """
        lines = source.splitlines()
        out = [f"{self.span}: {self.message}"]
        index = self.span.line - 1
        if 0 <= index < len(lines):
            text = lines[index]
            out.append(f"  {text}")
            width = max(1, self.span.end - self.span.start)
            out.append("  " + " " * (self.span.column - 1) + "^" * width)
        out.extend(f"  {note}" for note in self.notes)
        return "\n".join(out)


@dataclass
class CompileError(Exception):
    """Compilation stopped, and these are the reasons.

    The list is a list because collecting several is where this is
    going; today the front end raises with exactly one.
    """

    diagnostics: list[Diagnostic] = field(default_factory=list)

    def __post_init__(self) -> None:
        super().__init__(self.diagnostics[0].message if self.diagnostics else "")

    @property
    def first(self) -> Diagnostic:
        return self.diagnostics[0]

    def render(self, source: str) -> str:
        return "\n\n".join(d.render(source) for d in self.diagnostics)


def error(message: str, span: Span, *notes: str) -> CompileError:
    """Build the one-diagnostic error the front end raises."""
    return CompileError([Diagnostic(message, span, tuple(notes))])
