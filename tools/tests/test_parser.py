# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0
"""The parser against specification §6.2 to §6.14.

Precedence is checked by *shape* rather than by poking at fields: a
rendering of the tree back into fully parenthesised source says what
§6.3.1's table says, and a single string per case is readable enough to
be argued with.
"""

from __future__ import annotations

import pytest

from mcuscript import ast
from mcuscript.diagnostics import CompileError
from mcuscript.parser import parse


def shape(node) -> str:
    """Fully parenthesised source, for comparing against §6.3.1."""
    match node:
        case ast.Binary():
            return f"({shape(node.left)} {node.op} {shape(node.right)})"
        case ast.Unary():
            return f"({node.op} {shape(node.operand)})"
        case ast.IsCheck():
            not_ = " not" if node.negated else ""
            return f"({shape(node.operand)} is{not_} {node.state})"
        case ast.Name():
            return node.text
        case ast.Number():
            return node.text + node.suffix
        case ast.Duration():
            return "+".join(p.text + p.suffix for p in node.parts)
        case ast.DateTime():
            return f"@{node.date}|{node.time}"
        case ast.BoolLit():
            return "true" if node.value else "false"
        case ast.StringLit():
            return f'"{node.value}"'
        case ast.Call():
            return f"{node.callee.text}({', '.join(shape(a) for a in node.args)})"
        case ast.Unit():
            return node.text
        case ast.Index():
            return f"{shape(node.target)}[{shape(node.index)}]"
        case ast.Range():
            return f"{shape(node.low)}..{shape(node.high)}"
        case ast.If():
            tail = f" else {shape(node.otherwise)}" if node.otherwise else ""
            return f"(if {shape(node.condition)}{tail})"
        case ast.Match():
            return f"(match {shape(node.subject)} {len(node.arms)} arms)"
        case ast.Block():
            return "{" + "; ".join(shape(s) for s in node.statements) + "}"
        case ast.ExprStmt():
            return shape(node.value)
        case ast.Let():
            kind = f": {node.annotation.name}" if node.annotation else ""
            return f"let {node.name}{kind} = {shape(node.value)}"
        case ast.Assign():
            return f"{shape(node.target)} {node.op} {shape(node.value)}"
        case ast.Return():
            return "return" if node.value is None else f"return {shape(node.value)}"
        case ast.For():
            return f"for {node.variable} in {shape(node.iterable)} {shape(node.body)}"
    return type(node).__name__.lower()


def expression(source: str):
    program = parse(source, "t.mcs")
    assert program.expression is not None
    return program.expression


def only_statement(source: str):
    program = parse("on e {\n" + source + "\n}", "t.mcs")
    return program.entries[0].body.statements[0]


def refusal(source: str) -> CompileError:
    with pytest.raises(CompileError) as caught:
        parse(source, "t.mcs")
    return caught.value


def rendered(error: CompileError) -> str:
    return error.first.message + " " + " ".join(error.first.notes)


# -- §6.3.1 precedence -------------------------------------------------


@pytest.mark.parametrize(
    ("source", "tree"),
    [
        ("1 + 2 * 3", "(1 + (2 * 3))"),
        ("1 * 2 + 3", "((1 * 2) + 3)"),
        ("1 - 2 - 3", "((1 - 2) - 3)"),
        ("a mod b + 1", "((a mod b) + 1)"),
        ("-x + 1", "((- x) + 1)"),
        ("~a | b", "((~ a) | b)"),
        # Python's order and not C's: this reads as it looks.
        ("a & mask == 0", "((a & mask) == 0)"),
        ("a | b ^ c & d", "(a | (b ^ (c & d)))"),
        ("a << 2 | b", "((a << 2) | b)"),
        # `else` between arithmetic and comparison, per §1.3.1's example.
        ("temp else 20 > 25", "((temp else 20) > 25)"),
        ("a + b else 0", "((a + b) else 0)"),
        # `not` looser than comparison, tighter than `and`.
        ("not temp > 25", "(not (temp > 25))"),
        ("not a and b", "((not a) and b)"),
        ("a and b or c", "((a and b) or c)"),
        ("a or b and c", "(a or (b and c))"),
        ("a is not valid", "(a is not valid)"),
        ("a + 1 is invalid", "((a + 1) is invalid)"),
    ],
)
def test_precedence(source, tree):
    assert shape(expression(source)) == tree


def test_comparison_does_not_chain():
    assert "a < b and b < c" in rendered(refusal("a < b < c"))


def test_parentheses_win():
    assert shape(expression("(1 + 2) * 3")) == "((1 + 2) * 3)"


# -- §6.2 the shape of a program ---------------------------------------


def test_a_file_that_is_one_expression_is_a_program():
    program = parse("(sensor.temp - 32) / 1.8", "t.mcs")
    assert program.expression is not None
    assert program.entries == ()


def test_a_file_of_declarations():
    program = parse("on a { 1 }\nfn b() { 2 }\non c { 3 }", "t.mcs")
    assert [e.name for e in program.entries] == ["a", "c"]
    assert [f.name for f in program.functions] == ["b"]
    assert len(program.declaration_order) == 3


def test_an_expression_and_a_declaration_do_not_mix():
    assert "one expression" in rendered(refusal("1 + 1\non a { 2 }"))


def test_an_empty_file_is_refused():
    assert "empty" in refusal("").first.message


def test_a_recursion_cap_is_written_with_limit():
    program = parse("fn f(n) limit 5 { f(n) }", "t.mcs")
    assert program.functions[0].limit == 5


def test_a_parameter_may_carry_a_type():
    program = parse("fn f(c: f32, n) { c }", "t.mcs")
    names = [
        (p.name, p.annotation.name if p.annotation else None)
        for p in program.functions[0].params
    ]
    assert names == [("c", "f32"), ("n", None)]


# -- §6.4 statements ---------------------------------------------------


def test_let_with_and_without_a_type():
    assert shape(only_statement("let total: i64 = 0")) == "let total: i64 = 0"
    assert shape(only_statement("let t = 1")) == "let t = 1"


def test_a_dimension_may_stand_where_a_type_does():
    # §6.5.3: a dimension is a type, so the parser must not privilege
    # the four dimensionless names.
    assert shape(only_statement("let t: temperature = 1")) == "let t: temperature = 1"


@pytest.mark.parametrize("op", ["=", "+=", "-=", "*=", "/="])
def test_assignment_operators(op):
    assert shape(only_statement(f"fan.speed {op} 3")) == f"fan.speed {op} 3"


def test_assignment_is_not_an_expression():
    assert "`==`" in rendered(refusal("on e { if x = 5 { 1 } }"))


def test_return_with_and_without_a_value():
    assert shape(only_statement("return")) == "return"
    assert shape(only_statement("return 1 + 2")) == "return (1 + 2)"


def test_a_for_loop_over_a_range():
    assert shape(only_statement("for i in 0..9 { i }")) == "for i in 0..9 {i}"


def test_break_and_continue():
    assert isinstance(only_statement("break"), ast.Break)
    assert isinstance(only_statement("continue"), ast.Continue)


@pytest.mark.parametrize("word", ["while", "try", "catch"])
def test_a_reserved_word_says_it_is_planned(word):
    error = refusal("on e { " + word + " a { 1 } }")
    assert "planned and not built" in error.first.message


# -- §6.3.4 and §6.3.5 if and match ------------------------------------


def test_if_is_an_expression():
    tree = shape(expression("if a { 1 } else if b { 2 } else { 0 }"))
    assert tree == "(if a else (if b else {0}))"


def test_if_as_a_statement_needs_no_else():
    assert isinstance(only_statement("if a { fan.on() }"), ast.ExprStmt)


def test_match_arms_may_be_separated_by_newlines_or_commas():
    with_newlines = expression("match t {\n> 1 -> 2\nelse -> 0\n}")
    with_commas = expression("match t { > 1 -> 2, else -> 0 }")
    assert len(with_newlines.arms) == len(with_commas.arms) == 2


def test_every_kind_of_pattern():
    tree = expression(
        "match t {\n"
        "unavailable -> 0\n"
        "invalid -> 1\n"
        "> 28 -> 2\n"
        "24..28 -> 3\n"
        "9 -> 4\n"
        "else -> 5\n"
        "}"
    )
    kinds = [type(arm.pattern).__name__ for arm in tree.arms]
    assert kinds == [
        "StatePattern",
        "StatePattern",
        "ComparePattern",
        "RangePattern",
        "ValuePattern",
        "ElsePattern",
    ]


def test_an_arm_may_produce_a_non_valid_value():
    # `invalid -> invalid` is the one way a script says so (§6.3.5).
    tree = expression("match t { invalid -> invalid, else -> 0 }")
    assert isinstance(tree.arms[0].pattern, ast.StatePattern)


def test_a_match_needs_an_arm():
    assert "at least one arm" in refusal("match t { }").first.message


# -- §6.1.6, §6.1.7, §6.3.7, §6.3.10 -----------------------------------


def test_adjacent_suffixed_numbers_are_one_duration():
    assert shape(expression("3h 45min")) == "3h+45min"
    assert shape(expression("1h30min")) == "1h+30min"


def test_a_lone_suffixed_number_is_not_a_duration():
    assert isinstance(expression("5min"), ast.Number)


def test_a_point_in_time():
    assert shape(expression('@"2026-08-18 13:25"')) == "@2026-08-18|13:25"
    assert shape(expression('@"13:25"')) == "@|13:25"


def test_a_dotted_name_is_one_name():
    name = expression("sensor.living_room.temp")
    assert name.parts == ("sensor", "living_room", "temp")
    assert name.is_dotted


def test_a_call_on_a_dotted_name():
    assert shape(expression("fan.set(3)")) == "fan.set(3)"


def test_a_conversion_takes_a_unit():
    assert shape(expression("to_i32(t, °C)")) == "to_i32(t, °C)"


def test_a_unit_outside_a_number_is_refused():
    assert "mod" in rendered(refusal("3 % 2"))


def test_a_space_before_a_unit_is_refused_by_name():
    assert "glued" in rendered(refusal("on e { let a = 5 min }"))


# -- diagnostics carry a place -----------------------------------------


def test_a_refusal_points_at_the_line():
    error = refusal("on e {\n  let a = 1\n  let b = &\n}")
    assert error.first.span.line == 3


def test_rendering_shows_the_source_line():
    source = "on e {\n  a < b < c\n}"
    error = refusal(source)
    assert "a < b < c" in error.render(source)


def test_a_keyword_may_be_a_name_part():
    # `fan.on()` is the most ordinary line in this language's first
    # embedding, and `on` declares an entry point (§6.3.7).
    assert shape(expression("fan.on()")) == "fan.on()"
    assert expression("a.if.match.for").parts == ("a", "if", "match", "for")


def test_a_state_is_a_value_as_well_as_a_pattern():
    assert isinstance(expression("invalid"), ast.StateLit)
    assert isinstance(only_statement("fan.speed = unavailable").value, ast.StateLit)


def test_a_block_that_is_never_closed_points_at_its_opening():
    error = refusal("on e {\n  let a = 1\n")
    assert "never closed" in error.first.message
