# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0
"""A textual assembler and disassembler for the container format.

There is no compiler yet and no surface syntax, and this is how the
back end gets tested without either. The assembler produces real
containers from text, so the verifier, the VM and the C backend can be
exercised on programs that no parser could yet produce — including the
malformed ones a corpus needs.

It is deliberately not a compiler in disguise. It resolves names to
indices, lays out code and computes the resource numbers; it does not
optimise, reorder or infer types. What it emits is what was written.

Syntax::

    ; a comment
    .profile 1 0.1                 ; id, then major.minor

    .entity read i32 temp dim 1    ; read | write | rw
    .entity write i32 fan.speed dim 1
    .hostfn i32 clamp i32 i32      ; return type, name, parameter types
    .const big i32 100000          ; a named constant-pool entry

    .entry on_temp -> i32          ; host-invocable, and takes no arguments
      .local previous i32
      load.h temp
      const.i32.s16 280
      gt.i32
      jmp_if_false else_arm
      const.i32.s8 3
      ret_v
    else_arm:
      const.i32.s8 0
      ret_v

    .fn countdown -> i32           ; not invocable from the host
      .param n i32                 ; parameters first; they are locals too
      .local scratch i32
      .cap 5                       ; recursion cap for this cycle

Everything an instruction refers to is written by name: a constant, a
local, an import, a function, a branch target. Indices exist only in the
binary. A container with an out-of-range index is a thing the verifier
must refuse, so it is built in Python by a test, never written here.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .container import (
    Access,
    Constant,
    Container,
    Function,
    Import,
    ImportKind,
)
from .opcodes import BY_CODE, BY_NAME, TYPE_BY_NAME, Op, Operand, ValType
from .verify import analyze

_ACCESS = {"read": Access.READ, "write": Access.WRITE, "rw": Access.BOTH}
_ACCESS_NAME = {v: k for k, v in _ACCESS.items()}


class AsmError(Exception):
    def __init__(self, line: int, message: str) -> None:
        self.line = line
        super().__init__(f"line {line}: {message}")


@dataclass(slots=True)
class _Insn:
    op: Op
    operand: str | None
    line: int
    offset: int = 0


@dataclass(slots=True)
class _Func:
    name: str
    invocable: bool
    return_type: ValType
    #: Parameters first, then the rest — they share one index space
    #: because a parameter *is* a local (§3.6).
    locals: list[tuple[str, ValType]]
    param_count: int
    cap: int
    insns: list[_Insn]
    labels: dict[str, int]
    line: int


def assemble(text: str) -> Container:
    """Assemble source text into a container with its resource numbers
    filled in."""
    parser = _Parser(text)
    parser.run()
    return parser.build()


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.profile = (0, 0, 0)
        self.constants: list[tuple[str, Constant]] = []
        self.imports: list[Import] = []
        self.functions: list[_Func] = []
        self.current: _Func | None = None

    # -- pass 1: read the text ------------------------------------------

    def run(self) -> None:
        for lineno, raw in enumerate(self.text.splitlines(), start=1):
            line = raw.split(";", 1)[0].strip()
            if not line:
                continue
            tokens = line.split()
            while tokens and tokens[0].endswith(":"):
                self._label(tokens.pop(0)[:-1], lineno)
            if not tokens:
                continue
            if tokens[0].startswith("."):
                self._directive(tokens, lineno)
            else:
                self._instruction(tokens, lineno)

    def _label(self, name: str, lineno: int) -> None:
        fn = self._need_function(lineno, "a label")
        if name in fn.labels:
            raise AsmError(lineno, f"label '{name}' is already defined")
        fn.labels[name] = len(fn.insns)

    def _need_function(self, lineno: int, what: str) -> _Func:
        if self.current is None:
            raise AsmError(lineno, f"{what} outside a function")
        return self.current

    def _directive(self, tokens: list[str], lineno: int) -> None:
        head, args = tokens[0], tokens[1:]
        if head == ".profile":
            if len(args) != 2 or "." not in args[1]:
                raise AsmError(lineno, ".profile takes an id and major.minor")
            major, _, minor = args[1].partition(".")
            self.profile = (
                _int(args[0], lineno),
                _int(major, lineno),
                _int(minor, lineno),
            )
        elif head == ".entity":
            self._entity(args, lineno)
        elif head == ".hostfn":
            self._hostfn(args, lineno)
        elif head == ".const":
            self._const(args, lineno)
        elif head in (".entry", ".fn"):
            self._function(head == ".entry", args, lineno)
        elif head in (".param", ".local"):
            self._slot(head, args, lineno)
        elif head == ".cap":
            fn = self._need_function(lineno, ".cap")
            if len(args) != 1:
                raise AsmError(lineno, ".cap takes a depth")
            fn.cap = _int(args[0], lineno)
        else:
            raise AsmError(lineno, f"unknown directive '{head}'")

    def _slot(self, head: str, args: list[str], lineno: int) -> None:
        fn = self._need_function(lineno, head)
        if len(args) != 2:
            raise AsmError(lineno, f"{head} takes a name and a type")
        if any(name == args[0] for name, _ in fn.locals):
            raise AsmError(lineno, f"'{args[0]}' is already declared")
        if head == ".param":
            # Parameters are the callee's *first* locals, so a parameter
            # after a plain local would need the record to carry a second
            # index space. It does not, and does not need to.
            if fn.param_count != len(fn.locals):
                raise AsmError(lineno, ".param must come before every .local")
            if fn.invocable:
                raise AsmError(
                    lineno,
                    f"'{fn.name}' is host-invocable and cannot take parameters; "
                    "a script reads what triggered it from an entity",
                )
            fn.param_count += 1
        fn.locals.append((args[0], _type(args[1], lineno)))

    def _entity(self, args: list[str], lineno: int) -> None:
        dimension = 0
        if len(args) >= 5 and args[3] == "dim":
            dimension = _int(args[4], lineno)
            args = args[:3]
        if len(args) != 3:
            raise AsmError(
                lineno,
                ".entity takes an access, a type, a name and an optional 'dim n'",
            )
        access = _ACCESS.get(args[0])
        if access is None:
            raise AsmError(lineno, f"'{args[0]}' is not read, write or rw")
        self._add_import(
            Import(
                args[2], ImportKind.ENTITY, access, _type(args[1], lineno), dimension
            ),
            lineno,
        )

    def _hostfn(self, args: list[str], lineno: int) -> None:
        if len(args) < 2:
            raise AsmError(lineno, ".hostfn takes a return type and a name")
        return_type = _type(args[0], lineno, allow_void=True)
        params = tuple(_type(a, lineno) for a in args[2:])
        self._add_import(
            Import(args[1], ImportKind.FUNCTION, Access.NONE, return_type, 0, params),
            lineno,
        )

    def _add_import(self, imp: Import, lineno: int) -> None:
        if any(existing.name == imp.name for existing in self.imports):
            raise AsmError(lineno, f"'{imp.name}' is already imported")
        self.imports.append(imp)

    def _const(self, args: list[str], lineno: int) -> None:
        if len(args) != 3:
            raise AsmError(lineno, ".const takes a name, a type and a value")
        name, type_ = args[0], _type(args[1], lineno)
        if any(existing == name for existing, _ in self.constants):
            raise AsmError(lineno, f"constant '{name}' is already defined")
        if type_ is ValType.F32:
            value: int | float = float(args[2])
        elif type_ is ValType.BOOL:
            raise AsmError(lineno, "bool has its own instructions and no pool entry")
        else:
            value = _int(args[2], lineno)
        self.constants.append((name, Constant(type_, value)))

    def _function(self, invocable: bool, args: list[str], lineno: int) -> None:
        return_type = ValType.VOID
        if len(args) == 3 and args[1] == "->":
            return_type = _type(args[2], lineno)
        elif len(args) != 1:
            raise AsmError(lineno, "a function takes a name and an optional '-> type'")
        name = args[0]
        if any(fn.name == name for fn in self.functions):
            raise AsmError(lineno, f"'{name}' is already defined")
        self.current = _Func(name, invocable, return_type, [], 0, 0, [], {}, lineno)
        self.functions.append(self.current)

    def _instruction(self, tokens: list[str], lineno: int) -> None:
        fn = self._need_function(lineno, "an instruction")
        op = BY_NAME.get(tokens[0])
        if op is None:
            raise AsmError(lineno, f"unknown instruction '{tokens[0]}'")
        wants = op.operand is not Operand.NONE
        if wants and len(tokens) != 2:
            raise AsmError(lineno, f"{op.name} takes one operand")
        if not wants and len(tokens) != 1:
            raise AsmError(lineno, f"{op.name} takes no operand")
        fn.insns.append(_Insn(op, tokens[1] if wants else None, lineno))

    # -- pass 2: lay out and resolve ------------------------------------

    def build(self) -> Container:
        code = bytearray()
        functions: list[Function] = []
        const_index = {name: i for i, (name, _) in enumerate(self.constants)}
        import_index = {imp.name: i for i, imp in enumerate(self.imports)}
        function_index = {fn.name: i for i, fn in enumerate(self.functions)}

        for fn in self.functions:
            if not fn.insns:
                raise AsmError(fn.line, f"'{fn.name}' has no instructions")
            offset = 0
            for insn in fn.insns:
                insn.offset = offset
                offset += insn.op.size
            local_index = {name: i for i, (name, _) in enumerate(fn.locals)}

            start = len(code)
            for position, insn in enumerate(fn.insns):
                code += self._encode(
                    fn,
                    insn,
                    position,
                    const_index,
                    import_index,
                    function_index,
                    local_index,
                )
            functions.append(
                Function(
                    name=fn.name,
                    code_offset=start,
                    return_type=fn.return_type,
                    local_types=tuple(t for _, t in fn.locals),
                    invocable=fn.invocable,
                    recursion_cap=fn.cap,
                    param_count=fn.param_count,
                )
            )

        container = Container(
            code=bytes(code),
            constants=[c for _, c in self.constants],
            functions=functions,
            imports=list(self.imports),
            profile_id=self.profile[0],
            profile_major=self.profile[1],
            profile_minor=self.profile[2],
        )
        from .opcodes import groups_used

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

    def _encode(
        self,
        fn: _Func,
        insn: _Insn,
        position: int,
        const_index: dict[str, int],
        import_index: dict[str, int],
        function_index: dict[str, int],
        local_index: dict[str, int],
    ) -> bytes:
        op, arg, line = insn.op, insn.operand, insn.line
        out = bytearray([op.code])
        if op.operand is Operand.NONE:
            return bytes(out)
        assert arg is not None

        if op.operand is Operand.OFF16:
            if arg not in fn.labels:
                raise AsmError(line, f"unknown label '{arg}'")
            target_position = fn.labels[arg]
            target = (
                fn.insns[target_position].offset
                if target_position < len(fn.insns)
                else insn.offset + op.size
            )
            delta = target - (insn.offset + op.size)
            if not -0x8000 <= delta <= 0x7FFF:
                raise AsmError(line, f"branch to '{arg}' is out of range")
            return bytes(out) + delta.to_bytes(2, "little", signed=True)

        if op.operand is Operand.IMM8:
            value = _int(arg, line)
            if not -128 <= value <= 127:
                raise AsmError(line, f"{value} does not fit an imm8")
            return bytes(out) + value.to_bytes(1, "little", signed=True)

        if op.operand is Operand.IMM16:
            value = _int(arg, line)
            if not -0x8000 <= value <= 0x7FFF:
                raise AsmError(line, f"{value} does not fit an imm16")
            return bytes(out) + value.to_bytes(2, "little", signed=True)

        if op.operand is Operand.TYPE8:
            # A type name, not an index: `const.invalid i32`.
            out.append(_type(arg, line).value)
            return bytes(out)

        table, index = self._resolve(
            op, arg, line, const_index, import_index, function_index, local_index
        )
        if index > 255:
            raise AsmError(line, f"{table} index {index} does not fit a byte")
        out.append(index)
        return bytes(out)

    @staticmethod
    def _resolve(
        op: Op,
        arg: str,
        line: int,
        const_index: dict[str, int],
        import_index: dict[str, int],
        function_index: dict[str, int],
        local_index: dict[str, int],
    ) -> tuple[str, int]:
        if op.name in ("load.l", "store.l", "loop.guard"):
            table, lookup = "local", local_index
        elif op.name in ("load.h", "store.h", "call.h"):
            table, lookup = "import", import_index
        elif op.name == "call":
            table, lookup = "function", function_index
        else:
            table, lookup = "constant", const_index
        if arg not in lookup:
            raise AsmError(line, f"unknown {table} '{arg}'")
        return table, lookup[arg]


def _type(token: str, line: int, *, allow_void: bool = False) -> ValType:
    t = TYPE_BY_NAME.get(token)
    if t is None or (t is ValType.VOID and not allow_void):
        raise AsmError(line, f"'{token}' is not a type")
    return t


def _int(token: str, line: int) -> int:
    try:
        return int(token, 0)
    except ValueError:
        raise AsmError(line, f"'{token}' is not a number") from None


# -- disassembly ----------------------------------------------------------


def disassemble(container: Container) -> str:
    """Render a container as assembler source.

    Round-tripping is a test rather than a convenience: assembling the
    output must reproduce the input's bytes, which is the cheapest check
    that the encoder and the decoder agree about every field.
    """
    out: list[str] = [
        f".profile {container.profile_id} "
        f"{container.profile_major}.{container.profile_minor}",
        "",
    ]
    for imp in container.imports:
        if imp.kind == ImportKind.ENTITY:
            line = f".entity {_ACCESS_NAME[imp.access]} {imp.type} {imp.name}"
            if imp.dimension:
                line += f" dim {imp.dimension}"
        else:
            line = f".hostfn {imp.type} {imp.name}"
            line += "".join(f" {t}" for t in imp.param_types)
        out.append(line)
    if container.imports:
        out.append("")

    names = _constant_names(container)
    for name, constant in zip(names, container.constants, strict=True):
        out.append(f".const {name} {constant.type} {constant.value}")
    if container.constants:
        out.append("")

    regions = _regions(container)
    for index, fn in enumerate(container.functions):
        out.extend(_disassemble_function(container, fn, regions[index], names))
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def _constant_names(container: Container) -> list[str]:
    return [f"k{i}" for i in range(len(container.constants))]


def _regions(container: Container) -> list[tuple[int, int]]:
    order = sorted(
        range(len(container.functions)),
        key=lambda i: container.functions[i].code_offset,
    )
    regions = [(0, 0)] * len(container.functions)
    for position, index in enumerate(order):
        start = container.functions[index].code_offset
        end = (
            len(container.code)
            if position == len(order) - 1
            else container.functions[order[position + 1]].code_offset
        )
        regions[index] = (start, end)
    return regions


def _disassemble_function(
    container: Container, fn: Function, region: tuple[int, int], const_names: list[str]
) -> list[str]:
    start, end = region
    head = f"{'.entry' if fn.invocable else '.fn'} {fn.name}"
    if fn.return_type is not ValType.VOID:
        head += f" -> {fn.return_type}"
    lines = [head]
    local_names = [f"v{i}" for i in range(len(fn.local_types))]
    for i, (name, type_) in enumerate(zip(local_names, fn.local_types, strict=True)):
        lines.append(f"  {'.param' if i < fn.param_count else '.local'} {name} {type_}")
    if fn.recursion_cap:
        lines.append(f"  .cap {fn.recursion_cap}")

    labels = _branch_targets(container.code, start, end)
    pc = start
    while pc < end:
        op = BY_CODE[container.code[pc]]
        if pc in labels:
            lines.append(f"{labels[pc]}:")
        text = op.name
        if op.operand is not Operand.NONE:
            text += " " + _render_operand(
                container, fn, op, container.code, pc, labels, const_names, local_names
            )
        lines.append(f"  {text}")
        pc += op.size
    if end in labels:
        lines.append(f"{labels[end]}:")
    return lines


def _branch_targets(code: bytes, start: int, end: int) -> dict[int, str]:
    targets = []
    pc = start
    while pc < end:
        op = BY_CODE[code[pc]]
        if op.is_branch:
            delta = int.from_bytes(code[pc + 1 : pc + 3], "little", signed=True)
            targets.append(pc + op.size + delta)
        pc += op.size
    return {t: f"L{i}" for i, t in enumerate(sorted(set(targets)))}


def _render_operand(
    container: Container,
    fn: Function,
    op: Op,
    code: bytes,
    pc: int,
    labels: dict[int, str],
    const_names: list[str],
    local_names: list[str],
) -> str:
    if op.operand is Operand.OFF16:
        delta = int.from_bytes(code[pc + 1 : pc + 3], "little", signed=True)
        return labels[pc + op.size + delta]
    if op.operand is Operand.IMM8:
        return str(int.from_bytes(code[pc + 1 : pc + 2], "little", signed=True))
    if op.operand is Operand.IMM16:
        return str(int.from_bytes(code[pc + 1 : pc + 3], "little", signed=True))
    if op.operand is Operand.TYPE8:
        return str(ValType(code[pc + 1]))
    index = code[pc + 1]
    if op.name in ("load.l", "store.l", "loop.guard"):
        return local_names[index]
    if op.name in ("load.h", "store.h", "call.h"):
        return container.imports[index].name
    if op.name == "call":
        return container.functions[index].name
    return const_names[index]
