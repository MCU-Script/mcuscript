# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0
"""The second backend: a container, lowered to plain C.

Every program has two lowerings and must have both (spec/README.md).
This is the other one, and the promise is that they produce identical
results — not that they look alike.

**It consumes the container, not an earlier intermediate form.** Both
backends therefore start from the same bytes: a divergence cannot be
blamed on two different inputs, and a container that arrived over the
air can still be compiled in. It also means this backend inherits the
verifier's work — the types, the depths and the branch targets are
already proved, so nothing here has to check them.

**The lowering is the stack machine, not a reconstructed expression
tree.** Each operand-stack position becomes a pair of C variables and
each branch becomes a forward ``goto``, which the no-backward-jumps rule
makes legal by construction. The result reads like a machine and
compiles like one: any optimizing compiler puts those variables in
registers and the redundant copies vanish. Reconstructing `a + b * c`
would produce prettier C and one more chance to be wrong, and prettier
C was never the requirement.

**Linking is the C linker's.** Each import becomes an `extern` function
the embedder implements. There is no import table and no name resolution
at run time, because for a compiled-in program the embedder's registry
is known at build time — so a script referring to something that is not
there is a link error, at the moment the firmware is built, which is
strictly earlier than the load-time refusal the VM would give.

**Calls become C calls, and the recursion cap becomes a counter.** C has
no cap of its own, so the transpiler emits one per call-graph cycle
(§5.4) — increment on entry, decrement on every path out including the
one a fault takes. Without it the transpiled program would recurse until
the thread stack ran out, which on a device with no MMU is not a crash
but silent corruption, and it would behave differently from the VM.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass

from .container import Container, Function, ImportKind
from .opcodes import BY_CODE, Operand, ValType
from .verify import analyze, stack_shapes

_C_TYPE = {
    ValType.I32: "i32",
    ValType.BOOL: "boolean",
    ValType.I64: "i64",
    ValType.F32: "f32",
}


class UnsupportedProgram(Exception):
    """The container uses something this backend cannot lower yet."""


def mangle(name: str) -> str:
    """A C identifier from an entity name.

    Anything that is not a C identifier character becomes an underscore,
    which can collide — `fan.speed` and `fan_speed` both become
    `fan_speed`. The generator refuses rather than emitting two
    declarations of one symbol and letting the C compiler explain it.
    """
    return re.sub(r"[^A-Za-z0-9_]", "_", name)


@dataclass(frozen=True, slots=True)
class Symbols:
    """The C names a generated translation unit uses.

    ``reads``, ``writes`` and ``calls`` are the extern functions the
    embedder must supply; ``entries`` are what it may call; ``functions``
    are the file's own ``static`` ones, one per record and entry points
    included — an entry point is a function with a wrapper, not a
    different thing.
    """

    reads: tuple[tuple[str, str], ...]  # (entity name, C symbol)
    writes: tuple[tuple[str, str], ...]
    calls: tuple[tuple[str, str], ...]
    entries: tuple[tuple[str, str], ...]
    functions: tuple[tuple[str, str], ...] = ()


def symbols(container: Container) -> Symbols:
    reads, writes, calls, entries, functions = [], [], [], [], []
    seen: dict[str, str] = {}

    def claim(prefix: str, name: str) -> str:
        symbol = f"mcuscript_{prefix}__{mangle(name)}"
        if symbol in seen and seen[symbol] != name:
            raise UnsupportedProgram(
                f"'{name}' and '{seen[symbol]}' both mangle to {symbol}"
            )
        seen[symbol] = name
        return symbol

    for imp in container.imports:
        if imp.kind == ImportKind.FUNCTION:
            calls.append((imp.name, claim("call", imp.name)))
            continue
        if imp.access & 0x01:
            reads.append((imp.name, claim("read", imp.name)))
        if imp.access & 0x02:
            writes.append((imp.name, claim("write", imp.name)))
    for fn in container.functions:
        functions.append((fn.name, claim("fn", fn.name)))
        if fn.invocable:
            entries.append((fn.name, claim("entry", fn.name)))
    return Symbols(
        tuple(reads), tuple(writes), tuple(calls), tuple(entries), tuple(functions)
    )


def generate(container: Container, *, source: str = "a container") -> str:
    """Lower a verified container to one C translation unit."""
    names = symbols(container)
    shapes = stack_shapes(container)
    facts = analyze(container)
    out: list[str] = []
    w = out.append

    w(f"/* Generated by mcuscript from {source}. Do not edit. */")
    w("")
    w("#include <stdbool.h>")
    w("#include <stdint.h>")
    w("")
    w('#include "mcuscript.h"')
    w('#include "mcuscript_ops.h"')
    w("")
    w("/*")
    w(" * REQUIRED BUILD FLAGS: -ffp-contract=off, and not -ffast-math.")
    w(" *")
    w(" * Two roundings, never a fused multiply-add (spec §1.5). The")
    w(" * pragma below says so to compilers that implement it; GCC does")
    w(" * not — it warns that the pragma is ignored and contracts anyway")
    w(" * — so on GCC the flag is the only thing that works. Measured: on")
    w(" * x86-64 with -mfma and -ffp-contract=fast, a*b+c for 1e20, 1e20,")
    w(" * -inf gives NaN through the VM and -inf through this file.")
    w(" */")
    w("#if defined(__clang__) || !defined(__GNUC__)")
    w("#pragma STDC FP_CONTRACT OFF")
    w("#endif")
    w("#if defined(__FAST_MATH__)")
    w(
        '#error "MCUScript requires IEEE-754 arithmetic: -ffast-math is not '
        'a conforming build"'
    )
    w("#endif")
    w("")

    for name, symbol in names.reads:
        w(f"/* {name} */")
        w(f"extern mcuscript_value {symbol}(void);")
    for name, symbol in names.writes:
        w(f"/* {name} */")
        w(f"extern void {symbol}(mcuscript_value value);")
    for name, symbol in names.calls:
        w(f"/* {name} */")
        w(f"extern bool {symbol}(const mcuscript_value *arguments,")
        w(f"{' ' * (len(symbol) + 12)}mcuscript_value *result);")
    if names.reads or names.writes or names.calls:
        w("")

    inner = dict(names.functions)

    # One counter per capped call-graph cycle (§5.4). A counter is
    # static because the cycle is: the same functions are involved
    # whoever called them, and scripts never nest (§5.1), so there is
    # nothing for a per-invocation counter to distinguish.
    counters = _counters(container, facts)
    for _, (counter, cap, members) in sorted(counters.items()):
        w(f"/* recursion cap {cap} over {', '.join(members)} */")
        w(f"static unsigned {counter};")
    if counters:
        w("")

    if len(container.functions) > 1:
        for fn in container.functions:
            w(_prototype(fn, inner[fn.name]) + ";")
        w("")

    for fn in container.functions:
        out.extend(_function(container, fn, shapes[fn.name], inner, facts, counters))
        w("")
    for fn in container.functions:
        if fn.invocable:
            out.extend(_entry_wrapper(fn, dict(names.entries)[fn.name], inner[fn.name]))
            w("")
    return "\n".join(out).rstrip() + "\n"


def _counters(container: Container, facts) -> dict[int, tuple[str, int, list[str]]]:
    """Component -> (C identifier, cap, member names), capped ones only."""
    out: dict[int, tuple[str, int, list[str]]] = {}
    for fn in container.functions:
        f = facts[fn.name]
        if not f.recursion_cap:
            continue
        entry = out.setdefault(
            f.component, (f"mcuscript_recursion__{f.component}", f.recursion_cap, [])
        )
        entry[2].append(fn.name)
    return out


def header(container: Container, *, source: str = "a container") -> str:
    """The declarations an embedder needs to call the generated code."""
    names = symbols(container)
    out = [
        f"/* Generated by mcuscript from {source}. Do not edit. */",
        "",
        "#ifndef MCUSCRIPT_GENERATED_H",
        "#define MCUSCRIPT_GENERATED_H",
        "",
        '#include "mcuscript.h"',
        "",
    ]
    for fn in container.functions:
        if not fn.invocable:
            continue
        symbol = dict(names.entries)[fn.name]
        out.append(f"/* {fn.name} */")
        out.append(f"bool {symbol}(mcuscript_value *result, mcuscript_fault *fault);")
    out += ["", "#endif /* MCUSCRIPT_GENERATED_H */"]
    return "\n".join(out) + "\n"


# -- one function ---------------------------------------------------------


def _slot(depth: int) -> tuple[str, str]:
    return f"v{depth}", f"s{depth}"


def _local(index: int) -> tuple[str, str]:
    return f"l{index}", f"m{index}"


def _read_slot(name: str, type_: ValType) -> str:
    """A slot, as the C value of its verified type."""
    if type_ is ValType.I32:
        return f"mcuscript_op_as_i32({name})"
    if type_ is ValType.I64:
        return f"mcuscript_op_as_i64({name})"
    if type_ is ValType.F32:
        return f"mcuscript_op_as_f32({name})"
    if type_ is ValType.BOOL:
        return f"({name} != 0)"
    raise UnsupportedProgram(f"{type_} is not lowered yet")


def _write_slot(name: str, type_: ValType, expression: str) -> str:
    if type_ is ValType.I32:
        return f"{name} = mcuscript_op_from_i32({expression});"
    if type_ is ValType.I64:
        return f"{name} = mcuscript_op_from_i64({expression});"
    if type_ is ValType.F32:
        # Storing narrows back to binary32 at exactly the point the VM
        # narrows, which is what makes an FPU with wider intermediates
        # unable to separate the two backends.
        return f"{name} = mcuscript_op_from_f32({expression});"
    if type_ is ValType.BOOL:
        return f"{name} = ({expression}) ? 1u : 0u;"
    raise UnsupportedProgram(f"{type_} is not lowered yet")


_ARITHMETIC = {
    "add": ValType.I32,
    "sub": ValType.I32,
    "mul": ValType.I32,
}

#: mnemonic -> (operand type, helper, result type)
_BINARY = {
    f"{stem}.{suffix}": (
        {"i32": ValType.I32, "i64": ValType.I64, "f32": ValType.F32}[suffix],
        f"mcuscript_op_{stem}_{suffix}",
    )
    for suffix in ("i32", "i64", "f32")
    for stem in ("add", "sub", "mul")
}
_BINARY.update(
    {
        "div.f32": (ValType.F32, "mcuscript_op_div_f32"),
    }
)

_DIVISION = {
    "div.i32": (ValType.I32, "mcuscript_op_div_i32"),
    "rem.i32": (ValType.I32, "mcuscript_op_rem_i32"),
    "div.i64": (ValType.I64, "mcuscript_op_div_i64"),
    "rem.i64": (ValType.I64, "mcuscript_op_rem_i64"),
}

_UNARY = {
    "neg.i32": (ValType.I32, ValType.I32, "mcuscript_op_neg_i32"),
    "neg.i64": (ValType.I64, ValType.I64, "mcuscript_op_neg_i64"),
    "neg.f32": (ValType.F32, ValType.F32, "mcuscript_op_neg_f32"),
    "convert.i32_f32": (ValType.I32, ValType.F32, "mcuscript_op_convert_i32_f32"),
}

_COMPARE = {
    f"{stem}.{suffix}": (
        {"i32": ValType.I32, "i64": ValType.I64, "f32": ValType.F32}[suffix],
        operator,
    )
    for suffix in ("i32", "i64", "f32")
    for stem, operator in (
        ("eq", "=="),
        ("ne", "!="),
        ("lt", "<"),
        ("le", "<="),
        ("gt", ">"),
        ("ge", ">="),
    )
}


def _prototype(fn: Function, symbol: str) -> str:
    """The signature every function gets, entry points included.

    Parameters are the first locals (§3.6), so they *are* the C
    parameters — no copy, no second index space. The return value
    travels as a raw slot rather than as a ``mcuscript_value`` because
    that is what the VM carries too; converting happens once, at the
    host boundary, in the wrapper.
    """
    arguments = []
    for i in range(fn.param_count):
        value, state = _local(i)
        arguments.append(f"uint64_t {value}")
        arguments.append(f"uint8_t {state}")
    arguments += [
        "uint64_t *result_value",
        "uint8_t *result_state",
        "mcuscript_fault *fault",
    ]
    return f"static bool {symbol}({', '.join(arguments)})"


def _function(
    container: Container,
    fn: Function,
    shapes: dict,
    inner: dict[str, str],
    facts: dict,
    counters: dict[int, tuple[str, int, list[str]]],
) -> list[str]:
    start = fn.code_offset
    end = start + _region_length(container, fn)
    code = container.code
    targets = _branch_targets(code, start, end)

    body: list[str] = []
    pc = start
    while pc < end:
        op = BY_CODE[code[pc]]
        stack = shapes[pc]
        if pc in targets:
            body.append(f"{targets[pc]}:")
        body.extend(
            "\t" + line
            for line in _instruction(container, fn, op, code, pc, stack, targets, inner)
        )
        pc += op.size

    lines = [_prototype(fn, inner[fn.name]), "{"]
    for i, type_ in enumerate(fn.local_types):
        if i < fn.param_count:
            continue  # a parameter is already declared, as a parameter
        value, state = _local(i)
        lines.append(f"\t/* local {i}: {type_} */")
        lines.append(f"\tuint64_t {value} = 0;")
        lines.append(f"\tuint8_t {state} = MCUSCRIPT_UNAVAILABLE;")
    for i in range(fn.max_stack):
        value, state = _slot(i)
        lines.append(f"\tuint64_t {value} = 0;")
        lines.append(f"\tuint8_t {state} = MCUSCRIPT_VALID;")
    lines.append("\tbool ok = false;")
    # Any of these can go unread — a function with no branch, no host
    # call and no return value touches none of them, and a parameter it
    # ignores is legal too. Casting them away unconditionally is cheaper
    # than working out which.
    lines.append("\t(void)result_value;")
    lines.append("\t(void)result_state;")
    lines.append("\t(void)fault;")
    for i in range(fn.param_count):
        value, state = _local(i)
        lines.append(f"\t(void){value};")
        lines.append(f"\t(void){state};")
    lines.append("")

    counter = counters.get(facts[fn.name].component)
    if counter is not None:
        name, cap, _ = counter
        lines += [
            f"\tif (++{name} > {cap}u) {{",
            "\t\t*fault = MCUSCRIPT_RECURSION_LIMIT;",
            "\t\tgoto done;",
            "\t}",
            "",
        ]

    lines.extend(body)
    # Every path out of the body arrives here, which is what keeps the
    # counter balanced even when a fault is unwinding through it.
    lines.append("done:")
    if counter is not None:
        lines.append(f"\t--{counter[0]};")
    lines.append("\treturn ok;")
    lines.append("}")
    return lines


def _entry_wrapper(fn: Function, symbol: str, inner: str) -> list[str]:
    """What the embedder calls: the same three things `mcuscript_invoke`
    gives it, over a function that speaks in slots."""
    lines = [
        f"/* {fn.name} */",
        f"bool {symbol}(mcuscript_value *result, mcuscript_fault *fault)",
        "{",
        "\tuint64_t value = 0;",
        "\tuint8_t state = MCUSCRIPT_UNAVAILABLE;",
        "\tmcuscript_fault raised = MCUSCRIPT_NO_FAULT;",
        "",
        f"\tif (!{inner}(&value, &state, &raised)) {{",
        "\t\tif (fault != NULL)",
        "\t\t\t*fault = raised;",
        "\t\treturn false;",
        "\t}",
    ]
    if fn.return_type is not ValType.VOID:
        lines += [
            "\tif (result != NULL) {",
            "\t\tresult->as.i64 = 0;",
            f"\t\tresult->as.{_C_TYPE[fn.return_type]} = "
            f"{_read_slot('value', fn.return_type)};",
            "\t\tresult->validity = state;",
            "\t}",
        ]
    else:
        # A void entry point leaves `result` untouched, exactly as
        # `mcuscript_invoke` does when it reaches `RET`.
        lines.append("\t(void)result;")
    lines += ["\treturn true;", "}"]
    return lines


def _region_length(container: Container, fn: Function) -> int:
    end = len(container.code)
    for other in container.functions:
        if fn.code_offset < other.code_offset < end:
            end = other.code_offset
    return end - fn.code_offset


def _branch_targets(code: bytes, start: int, end: int) -> dict[int, str]:
    targets = []
    pc = start
    while pc < end:
        op = BY_CODE[code[pc]]
        if op.is_branch:
            delta = int.from_bytes(code[pc + 1 : pc + 3], "little", signed=True)
            targets.append(pc + op.size + delta)
        pc += op.size
    return {t: f"L{t - start}" for t in sorted(set(targets))}


def _instruction(
    container: Container,
    fn: Function,
    op,
    code: bytes,
    pc: int,
    stack: tuple[ValType, ...],
    targets: dict[int, str],
    inner: dict[str, str],
) -> list[str]:
    depth = len(stack)
    top, top_state = _slot(depth - 1) if depth else ("", "")
    push, push_state = _slot(depth)
    index = code[pc + 1] if op.operand is not Operand.NONE else 0
    name = op.name

    if name == "const.i32.s8":
        literal = int.from_bytes(code[pc + 1 : pc + 2], "little", signed=True)
        return [
            _write_slot(push, ValType.I32, str(literal)),
            f"{push_state} = MCUSCRIPT_VALID;",
        ]
    if name == "const.i32.s16":
        literal = int.from_bytes(code[pc + 1 : pc + 3], "little", signed=True)
        return [
            _write_slot(push, ValType.I32, str(literal)),
            f"{push_state} = MCUSCRIPT_VALID;",
        ]
    if name == "const.i32":
        literal = container.constants[index].value
        return [
            _write_slot(push, ValType.I32, _c_i32(literal)),
            f"{push_state} = MCUSCRIPT_VALID;",
        ]
    if name == "const.i64":
        literal = container.constants[index].value
        return [
            _write_slot(push, ValType.I64, _c_i64(literal)),
            f"{push_state} = MCUSCRIPT_VALID;",
        ]
    if name == "const.f32":
        # The slot holds the bit pattern, so the literal is emitted as
        # bits. A decimal literal would ask the C compiler to re-round
        # it, and the two backends would then disagree about a constant.
        literal = container.constants[index].value
        bits = struct.unpack("<I", struct.pack("<f", literal))[0]
        return [
            f"{push} = 0x{bits:08X}u; /* {literal!r} */",
            f"{push_state} = MCUSCRIPT_VALID;",
        ]
    if name in ("const.true", "const.false"):
        return [
            f"{push} = {1 if name.endswith('true') else 0}u;",
            f"{push_state} = MCUSCRIPT_VALID;",
        ]

    if name == "load.l":
        value, state = _local(index)
        return [f"{push} = {value};", f"{push_state} = {state};"]
    if name == "store.l":
        value, state = _local(index)
        return [f"{value} = {top};", f"{state} = {top_state};"]

    if name == "load.h":
        imp = container.imports[index]
        symbol = f"mcuscript_read__{mangle(imp.name)}"
        return [
            "{",
            f"\tmcuscript_value read = {symbol}();",
            "\t" + _write_slot(push, imp.type, f"read.as.{_C_TYPE[imp.type]}"),
            f"\t{push_state} = read.validity;",
            "}",
        ]
    if name == "store.h":
        imp = container.imports[index]
        symbol = f"mcuscript_write__{mangle(imp.name)}"
        return [
            "{",
            "\tmcuscript_value written;",
            "\twritten.as.i64 = 0;",
            f"\twritten.as.{_C_TYPE[imp.type]} = {_read_slot(top, imp.type)};",
            f"\twritten.validity = {top_state};",
            f"\t{symbol}(written);",
            "}",
        ]
    if name == "call.h":
        imp = container.imports[index]
        symbol = f"mcuscript_call__{mangle(imp.name)}"
        base = depth - len(imp.param_types)
        lines = ["{"]
        if imp.param_types:
            lines.append(f"\tmcuscript_value arguments[{len(imp.param_types)}];")
        for p, type_ in enumerate(imp.param_types):
            value, state = _slot(base + p)
            lines.append(f"\targuments[{p}].as.i64 = 0;")
            lines.append(
                f"\targuments[{p}].as.{_C_TYPE[type_]} = {_read_slot(value, type_)};"
            )
            lines.append(f"\targuments[{p}].validity = {state};")
        lines.append("\tmcuscript_value produced;")
        lines.append("\tproduced.as.i64 = 0;")
        lines.append("\tproduced.validity = MCUSCRIPT_UNAVAILABLE;")
        argument_list = "arguments" if imp.param_types else "NULL"
        lines.append(f"\tif (!{symbol}({argument_list}, &produced)) {{")
        lines.append("\t\t*fault = MCUSCRIPT_HOST_FAULT;")
        lines.append("\t\tgoto done;")
        lines.append("\t}")
        if imp.type is not ValType.VOID:
            value, state = _slot(base)
            lines.append(
                "\t" + _write_slot(value, imp.type, f"produced.as.{_C_TYPE[imp.type]}")
            )
            lines.append(f"\t{state} = produced.validity;")
        lines.append("}")
        return lines

    if name == "drop":
        # Nothing to emit: the slot simply stops being read. The C
        # compiler removes the dead store the producer made.
        return [f"/* drop {top} */"]
    if name == "dup":
        return [f"{push} = {top};", f"{push_state} = {top_state};"]

    if name in _BINARY:
        operand, helper = _BINARY[name]
        a, a_state = _slot(depth - 2)
        b, b_state = _slot(depth - 1)
        expression = f"{helper}({_read_slot(a, operand)}, {_read_slot(b, operand)})"
        return [
            _write_slot(a, operand, expression),
            f"{a_state} = mcuscript_op_worse({a_state}, {b_state});",
        ]
    if name in _DIVISION:
        operand, helper = _DIVISION[name]
        a, a_state = _slot(depth - 2)
        b, b_state = _slot(depth - 1)
        return [
            f"{a_state} = mcuscript_op_worse({a_state}, {b_state});",
            _write_slot(
                a,
                operand,
                f"{helper}({_read_slot(a, operand)}, "
                f"{_read_slot(b, operand)}, &{a_state})",
            ),
        ]
    if name in _UNARY:
        source, result, helper = _UNARY[name]
        return [_write_slot(top, result, f"{helper}({_read_slot(top, source)})")]
    if name == "trunc.f32_i32":
        return [
            _write_slot(
                top,
                ValType.I32,
                f"mcuscript_op_trunc_f32_i32({_read_slot(top, ValType.F32)}, "
                f"&{top_state})",
            )
        ]
    if name == "extend.i32_i64":
        return [
            _write_slot(top, ValType.I64, f"(int64_t){_read_slot(top, ValType.I32)}")
        ]
    if name == "wrap.i64_i32":
        return [_write_slot(top, ValType.I32, f"(int32_t)(uint32_t)(uint64_t){top}")]
    if name in _COMPARE:
        operand, operator = _COMPARE[name]
        a, a_state = _slot(depth - 2)
        b, b_state = _slot(depth - 1)
        expression = f"{_read_slot(a, operand)} {operator} {_read_slot(b, operand)}"
        return [
            _write_slot(a, ValType.BOOL, expression),
            f"{a_state} = mcuscript_op_worse({a_state}, {b_state});",
        ]
    if name == "not":
        return [f"{top} = {top} ? 0u : 1u;"]

    if name == "else":
        value, state = _slot(depth - 2)
        fallback, fallback_state = _slot(depth - 1)
        return [
            f"if ({state} != MCUSCRIPT_VALID) {{",
            f"\t{value} = {fallback};",
            f"\t{state} = {fallback_state};",
            "}",
        ]
    if name in ("is_valid", "is_unavailable", "is_invalid"):
        wanted = {
            "is_valid": "MCUSCRIPT_VALID",
            "is_unavailable": "MCUSCRIPT_UNAVAILABLE",
            "is_invalid": "MCUSCRIPT_INVALID",
        }[name]
        return [
            f"{top} = ({top_state} == {wanted}) ? 1u : 0u;",
            f"{top_state} = MCUSCRIPT_VALID;",
        ]

    if name == "jmp":
        delta = int.from_bytes(code[pc + 1 : pc + 3], "little", signed=True)
        return [f"goto {targets[pc + op.size + delta]};"]
    if name in ("jmp_if_false", "jmp_if_true"):
        delta = int.from_bytes(code[pc + 1 : pc + 3], "little", signed=True)
        label = targets[pc + op.size + delta]
        test = f"{top} == 0" if name == "jmp_if_false" else f"{top} != 0"
        return [
            # An absent reading must not become a wrong action (§1.3.1).
            f"if ({top_state} != MCUSCRIPT_VALID) {{",
            "\t*fault = MCUSCRIPT_ABSENT_CONDITION;",
            "\tgoto done;",
            "}",
            f"if ({test})",
            f"\tgoto {label};",
        ]

    if name == "call":
        callee = container.functions[index]
        base = depth - callee.param_count
        arguments = []
        for p in range(callee.param_count):
            value, state = _slot(base + p)
            arguments += [value, state]
        arguments += ["&call_value", "&call_state", "fault"]
        lines = [
            "{",
            "\tuint64_t call_value = 0;",
            "\tuint8_t call_state = MCUSCRIPT_UNAVAILABLE;",
            f"\tif (!{inner[callee.name]}({', '.join(arguments)}))",
            # The callee already said which fault; saying it again here
            # would overwrite the deeper, truer one.
            "\t\tgoto done;",
        ]
        if callee.return_type is not ValType.VOID:
            value, state = _slot(base)
            lines.append(f"\t{value} = call_value;")
            lines.append(f"\t{state} = call_state;")
        lines.append("}")
        return lines

    if name == "ret":
        return ["ok = true;", "goto done;"]
    if name == "ret_v":
        # The slot already holds the return type's bit pattern, so this
        # is a copy and not a conversion — the same thing the VM does.
        return [
            f"*result_value = {top};",
            f"*result_state = {top_state};",
            "ok = true;",
            "goto done;",
        ]

    raise UnsupportedProgram(f"{name} is not lowered yet")


def _c_i64(value: int) -> str:
    if value == -(2**63):
        return "INT64_MIN"
    return f"INT64_C({value})"


def _c_i32(value: int) -> str:
    # INT32_MIN has no negative literal in C: -2147483648 is unary minus
    # applied to a constant that does not fit an int.
    if value == -(2**31):
        return "INT32_MIN"
    return str(value)
