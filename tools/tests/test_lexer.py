# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0
"""The lexer against specification §6.1."""

from __future__ import annotations

import pytest

from mcuscript.diagnostics import CompileError
from mcuscript.lexer import KEYWORDS, TokenKind, tokenize


def kinds(source: str) -> list[tuple[str, str]]:
    return [(t.kind.value, t.text) for t in tokenize(source)]


def texts(source: str) -> list[str]:
    return [t.text + t.suffix for t in tokenize(source) if t.kind is not TokenKind.EOF]


# -- §6.1.2 comments ---------------------------------------------------


def test_a_comment_runs_to_the_end_of_the_line():
    assert texts("1 # two\n3") == ["1", "\n", "3"]


def test_a_hash_inside_text_is_not_a_comment():
    assert tokenize('"a # b"')[0].value == "a # b"


# -- §6.1.3 identifiers and keywords -----------------------------------


def test_keywords_are_the_ones_the_chapter_lists():
    # The list is normative; a word that drifts out of it silently
    # becomes an identifier somebody can use as an entity name.
    assert "div" not in KEYWORDS, "there is one division and it is `/`"
    assert {"while", "try", "catch"} <= KEYWORDS, "reserved before they are built"
    assert "valid" not in KEYWORDS, "contextual after `is` only (§6.14)"
    assert "i32" not in KEYWORDS, "contextual in a type position only (§6.5.3)"


def test_a_keyword_is_not_an_identifier():
    assert kinds("match")[0] == ("keyword", "match")
    assert kinds("matcher")[0] == ("ident", "matcher")


# -- §6.1.4 and §6.1.5 numbers and their suffixes ----------------------


@pytest.mark.parametrize(
    ("source", "number", "suffix"),
    [
        ("42", "42", ""),
        ("1_000_000", "1_000_000", ""),
        ("0xFF", "0xFF", ""),
        ("0b1010", "0b1010", ""),
        ("3.14", "3.14", ""),
        ("1.5e-3", "1.5e-3", ""),
        ("5min", "5", "min"),
        ("24.5°C", "24.5", "°C"),
        ("75%", "75", "%"),
        ("250‰", "250", "‰"),
    ],
)
def test_a_number_and_its_suffix_are_one_token(source, number, suffix):
    token = tokenize(source)[0]
    assert token.kind is TokenKind.NUMBER
    assert (token.text, token.suffix) == (number, suffix)


def test_a_space_makes_two_tokens():
    # §6.1.5 says this is the whole point of gluing them.
    assert kinds("5 min")[:2] == [("number", "5"), ("ident", "min")]


def test_a_range_is_not_a_fraction():
    assert texts("0..9") == ["0", "..", "9"]
    assert texts("2.5") == ["2.5"]


# -- §6.1.7 points in time ---------------------------------------------


@pytest.mark.parametrize(
    "inside",
    ["2026-08-18", "13:25", "13:25:30", "2026-08-18 13:25", "2026-08-18T13:25:30"],
)
def test_the_accepted_forms(inside):
    token = tokenize(f'@"{inside}"')[0]
    assert token.kind is TokenKind.DATETIME
    assert token.value == inside


@pytest.mark.parametrize("inside", ["18-08-2026", "1:5", "2026-08", "tomorrow"])
def test_and_nothing_else(inside):
    with pytest.raises(CompileError):
        tokenize(f'@"{inside}"')


def test_without_the_marker_it_is_a_string():
    assert tokenize('"2026-08-18"')[0].kind is TokenKind.STRING


def test_the_marker_needs_a_quoted_value():
    with pytest.raises(CompileError) as caught:
        tokenize("@2026")
    assert "point in time" in caught.value.first.message


# -- §6.1.9 operators and the mistakes they catch ----------------------


def test_the_longest_operator_wins():
    assert texts("a <= b") == ["a", "<=", "b"]
    assert texts("a << b") == ["a", "<<", "b"]
    assert texts("a -> b") == ["a", "->", "b"]


@pytest.mark.parametrize(
    ("source", "expected"),
    [("a && b", "and"), ("a || b", "or"), ("a ? b : c", "conditional")],
)
def test_a_borrowed_operator_is_refused_by_name(source, expected):
    with pytest.raises(CompileError) as caught:
        tokenize(source)
    rendered = caught.value.first.message + " ".join(caught.value.first.notes)
    assert expected in rendered


def test_a_lone_unit_is_its_own_token():
    # It is an argument to §6.3.10's conversions, and nothing else.
    token = tokenize("to_i32(x, °C)")[4]
    assert (token.kind, token.text) == (TokenKind.UNIT, "°C")


# -- §6.1.10 statement separators --------------------------------------


def test_a_semicolon_and_a_newline_are_the_same_token():
    assert [t.kind for t in tokenize("a; b")] == [t.kind for t in tokenize("a\nb")]


def test_a_line_ending_in_an_operator_continues():
    assert texts("a +\nb") == ["a", "+", "b"]


def test_a_line_ending_in_a_comma_continues():
    assert texts("f(a,\nb)") == ["f", "(", "a", ",", "b", ")"]


def test_a_newline_before_a_closer_is_not_a_separator():
    assert texts("f(a\n)") == ["f", "(", "a", ")"]


def test_blank_lines_are_not_separators():
    assert texts("a\n\n\nb") == ["a", "\n", "b"]


def test_a_newline_before_a_comparison_stays_a_separator():
    # This is why continuation looks backwards only: a `match` arm may
    # begin with a comparison, and eating this separator would join two
    # arms into one expression.
    assert texts("1\n> 2") == ["1", "\n", ">", "2"]


def test_crlf_is_one_line_ending():
    assert texts("a\r\nb") == ["a", "\n", "b"]


# -- text --------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "value"),
    [
        (r'"a\"b"', 'a"b'),
        (r'"a\\b"', "a\\b"),
        (r'"a\nb"', "a\nb"),
        (r'"a\tb"', "a\tb"),
        (r'"\u{41}"', "A"),
    ],
)
def test_escapes(source, value):
    assert tokenize(source)[0].value == value


def test_an_unknown_escape_is_named():
    with pytest.raises(CompileError) as caught:
        tokenize(r'"\q"')
    assert "\\q" in caught.value.first.message


def test_text_does_not_run_past_the_line():
    with pytest.raises(CompileError) as caught:
        tokenize('"never closed\nmore')
    assert "never closed" in caught.value.first.message


# -- positions ---------------------------------------------------------


def test_a_span_points_where_a_person_would_look():
    token = tokenize("a = 1\nlet b = 2")[4]
    assert token.text == "let"
    assert (token.span.line, token.span.column) == (2, 1)


def test_a_newline_before_else_stays_a_separator():
    # `} else` goes on one line: the forward rule that would allow the
    # break also eats the separator between two `match` arms.
    assert texts("}\nelse") == ["}", "\n", "else"]


def test_a_word_running_into_a_unit_symbol_is_a_unit():
    """`c°C` and `d%` in argument position — §6.1.5.

    The spellings a profile uses for a fine base unit start with a
    letter, so without this rule the lexer would hand the parser a name
    and a symbol, and a script could not name the unit it counts in.
    """
    # A unit spelled with letters alone — `kWh`, `min` — is a name to
    # the lexer and becomes a unit when the conversion resolves it;
    # there is nothing to tell apart in that case.
    for text in ("c°C", "d%", "°C", "%", "‰"):
        tokens = tokenize(f"to_i32(x, {text})", "t")
        kinds = [(t.kind, t.text) for t in tokens]
        assert (TokenKind.UNIT, text) in kinds, kinds


def test_a_plain_word_is_still_a_name():
    kinds = [(t.kind, t.text) for t in tokenize("count = degrees", "t")]
    assert kinds[0] == (TokenKind.IDENT, "count")
    assert kinds[2] == (TokenKind.IDENT, "degrees")
