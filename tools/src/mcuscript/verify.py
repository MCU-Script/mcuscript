# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0
"""The verifier of specification §2.6.

It establishes, before any instruction runs, that the container's code
cannot do anything the runtime would otherwise have to check for: every
opcode is defined, every branch lands on an instruction boundary going
forward, the operand stack is type-consistent along every path, and the
resource numbers the container declares are the ones its code actually
needs.

The last point is the load-bearing one. ``max_stack`` comes from an
untrusted file and the VM allocates from it, so this verifier does not
ask whether the number is plausible — it **recomputes** it and refuses
the container if the file disagrees.

This is the host-side copy. It exists for diagnostics: it can afford to
say which instruction, on which path, with which stack. The normative
one is the runtime's, because that is the one standing between a pushed
container and a device, and a corpus of containers with expected
verdicts keeps the two from drifting.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .container import Access, Container, Function, ImportKind
from .errors import Refusal, refuse
from .opcodes import BY_CODE, IMPLEMENTED_GROUPS, Group, Poly, ValType

Stack = tuple[ValType, ...]


@dataclass(frozen=True, slots=True)
class FunctionFacts:
    """What the verifier computed for one function."""

    max_stack: int
    #: Frames below this function's own, along the deepest call chain.
    max_call_depth: int
    #: The recursion cap of the call-graph cycle this function is in, or 0.
    recursion_cap: int


def verify(
    container: Container, *, implemented: frozenset[Group] = IMPLEMENTED_GROUPS
) -> dict[str, FunctionFacts]:
    """Verify a container. Raises :class:`~mcuscript.errors.Refused`, or
    returns the facts it computed, per function name."""
    container.check_groups(implemented)
    regions = _code_regions(container)
    facts = {}
    for index, fn in enumerate(container.functions):
        stack_depth = _walk(container, fn, index, regions[index])
        facts[fn.name] = FunctionFacts(stack_depth, 0, 0)

    call_depths, caps = _call_graph(container, regions)
    for fn in container.functions:
        facts[fn.name] = replace(
            facts[fn.name],
            max_call_depth=call_depths[fn.name],
            recursion_cap=caps[fn.name],
        )

    for fn in container.functions:
        computed = facts[fn.name]
        if fn.max_stack != computed.max_stack:
            raise refuse(
                Refusal.STACK_DEPTH_MISMATCH,
                where=fn.name,
                detail=f"declares {fn.max_stack}, needs {computed.max_stack}",
            )
        if fn.max_call_depth != computed.max_call_depth:
            raise refuse(
                Refusal.CALL_DEPTH_MISMATCH,
                where=fn.name,
                detail=f"declares {fn.max_call_depth}, needs {computed.max_call_depth}",
            )
    return facts


def analyze(container: Container) -> dict[str, FunctionFacts]:
    """Compute the resource numbers without checking them against the
    container's own. This is what an encoder calls to fill them in; a
    loader calls :func:`verify`."""
    regions = _code_regions(container)
    facts = {}
    for index, fn in enumerate(container.functions):
        facts[fn.name] = FunctionFacts(
            _walk(container, fn, index, regions[index]), 0, 0
        )
    call_depths, caps = _call_graph(container, regions)
    return {
        name: replace(f, max_call_depth=call_depths[name], recursion_cap=caps[name])
        for name, f in facts.items()
    }


# -- code regions ---------------------------------------------------------


def _code_regions(container: Container) -> list[tuple[int, int]]:
    """Each function owns a half-open byte range of ``CODE``.

    The ranges tile the section: a branch target outside the function's
    own range is refused (§2.6), so the extent has to be defined, and
    defining it as a tiling is what makes "outside" mean something. It
    also leaves no unaccounted bytes in the section.
    """
    n = len(container.functions)
    if n == 0:
        if container.code:
            raise refuse(
                Refusal.MALFORMED_SECTION,
                where="CODE",
                detail="code but no function declares it",
            )
        return []

    order = sorted(range(n), key=lambda i: container.functions[i].code_offset)
    regions: list[tuple[int, int]] = [(0, 0)] * n
    expected = 0
    for position, index in enumerate(order):
        start = container.functions[index].code_offset
        if start != expected:
            raise refuse(
                Refusal.MALFORMED_SECTION,
                where=container.functions[index].name,
                detail=f"code starts at {start}, the previous function ends "
                f"at {expected}",
            )
        last = position == n - 1
        end = (
            len(container.code)
            if last
            else (container.functions[order[position + 1]].code_offset)
        )
        if end <= start:
            raise refuse(
                Refusal.MALFORMED_SECTION,
                where=container.functions[index].name,
                detail="empty code region",
            )
        regions[index] = (start, end)
        expected = end
    return regions


# -- the type-stack walk --------------------------------------------------


def _walk(
    container: Container, fn: Function, index: int, region: tuple[int, int]
) -> int:
    """Abstract-interpret one function; return the maximum stack depth.

    The abstraction is the *types* on the stack, nothing else. That is
    the whole trick behind untagged slots (§1.2): if the type at every
    stack position is the same by every route to an instruction, the
    runtime never has to ask.
    """
    start, end = region
    code = container.code
    at: dict[int, Stack] = {}
    covered = bytearray(end - start)
    work: list[tuple[int, Stack]] = [(start, ())]
    high_water = 0

    def where(pc: int) -> str:
        return f"{fn.name}+{pc - start}"

    while work:
        pc, stack = work.pop()
        while True:
            high_water = max(high_water, len(stack))
            seen = at.get(pc)
            if seen is not None:
                if seen != stack:
                    raise refuse(
                        Refusal.INCONSISTENT_JOIN,
                        where=where(pc),
                        detail=f"reached with [{_fmt(stack)}] and [{_fmt(seen)}]",
                    )
                break
            at[pc] = stack

            op = BY_CODE.get(code[pc])
            if op is None:
                raise refuse(
                    Refusal.UNDEFINED_OPCODE,
                    where=where(pc),
                    detail=f"0x{code[pc]:02X}",
                )
            if not container.required_groups & op.group.mask:
                raise refuse(
                    Refusal.UNDEFINED_OPCODE,
                    where=where(pc),
                    detail=f"{op.name} is in group '{op.group.name.lower()}', "
                    "which the header does not require",
                )
            if pc + op.size > end:
                raise refuse(
                    Refusal.TRUNCATED_INSTRUCTION,
                    where=where(pc),
                    detail=f"{op.name} needs {op.size} bytes, "
                    f"{end - pc} remain in this function",
                )
            for i in range(op.size):
                covered[pc - start + i] += 1

            operand = _operand(code, pc, op)
            stack = _apply(container, fn, op, operand, stack, where(pc))
            high_water = max(high_water, len(stack))
            after = pc + op.size

            if op.name in ("ret", "ret_v"):
                break
            if op.is_branch:
                target = after + operand
                if target <= pc:
                    raise refuse(
                        Refusal.BACKWARD_BRANCH,
                        where=where(pc),
                        detail=f"jumps to {target - start}, at or before itself",
                    )
                if not (start <= target < end):
                    raise refuse(
                        Refusal.BAD_BRANCH_TARGET,
                        where=where(pc),
                        detail=f"target {target - start} is outside {fn.name}'s code",
                    )
                work.append((target, stack))
                if op.name == "jmp":
                    break
            if after >= end:
                raise refuse(
                    Refusal.BAD_BRANCH_TARGET,
                    where=where(pc),
                    detail="execution runs off the end of the function; "
                    "the last instruction on every path must be a return",
                )
            pc = after

    _check_coverage(covered, fn)
    return high_water


def _check_coverage(covered: bytearray, fn: Function) -> None:
    """Each reachable byte must be decoded exactly once.

    Every pc is decoded at most once, so a byte covered **twice** means
    two instruction boundaries overlap: a branch landed in the middle of
    an instruction and the code has two readings. That is the oldest
    trick against a bytecode verifier, and the coverage count is what
    catches it — checking targets against a list of boundaries would
    only work if the list were complete, and completeness is the thing
    in question.

    A byte covered **never** is code no path reaches. It cannot execute,
    so it is not a safety problem, but it is either an encoder bug or
    something smuggled in, and a container should mean one thing.
    """
    for offset, count in enumerate(covered):
        if count == 0:
            raise refuse(
                Refusal.UNREACHABLE_CODE,
                where=f"{fn.name}+{offset}",
                detail="no path reaches this byte",
            )
        if count > 1:
            raise refuse(
                Refusal.BAD_BRANCH_TARGET,
                where=f"{fn.name}+{offset}",
                detail="two instruction decodings overlap here, so a branch "
                "target is not on an instruction boundary",
            )


def _operand(code: bytes, pc: int, op) -> int:
    from .opcodes import Operand

    if op.operand is Operand.NONE:
        return 0
    raw = code[pc + 1 : pc + op.size]
    if op.operand is Operand.IMM8:
        return int.from_bytes(raw, "little", signed=True)
    if op.operand is Operand.IMM16:
        return int.from_bytes(raw, "little", signed=True)
    if op.operand is Operand.IDX8:
        return raw[0]
    return int.from_bytes(raw, "little", signed=True)  # OFF16


def _fmt(stack: Stack) -> str:
    return " ".join(str(t) for t in stack) or "empty"


def _pop(stack: Stack, n: int, where: str, op) -> tuple[Stack, Stack]:
    if len(stack) < n:
        raise refuse(
            Refusal.STACK_UNDERFLOW,
            where=where,
            detail=f"{op.name} needs {n}, the stack holds {len(stack)}",
        )
    return stack[: len(stack) - n], stack[len(stack) - n :]


def _expect(got: Stack, want: tuple[ValType, ...], where: str, op) -> None:
    if got != want:
        raise refuse(
            Refusal.TYPE_MISMATCH,
            where=where,
            detail=f"{op.name} takes [{_fmt(want)}], the stack offers [{_fmt(got)}]",
        )


def _apply(
    container: Container, fn: Function, op, operand: int, stack: Stack, where: str
) -> Stack:
    """The stack effect of one instruction, as types."""
    if op.poly is None:
        rest, taken = _pop(stack, len(op.pops), where, op)
        _expect(taken, op.pops, where, op)
        if op.name == "const.i32":
            _pool(container, operand, ValType.I32, where)
        return rest + op.pushes

    if op.poly is Poly.LOCAL_GET:
        return (*stack, _local(fn, operand, where))
    if op.poly is Poly.LOCAL_SET:
        want = _local(fn, operand, where)
        rest, taken = _pop(stack, 1, where, op)
        _expect(taken, (want,), where, op)
        return rest
    if op.poly is Poly.HOST_GET:
        imp = _import(container, operand, where)
        if imp.kind != ImportKind.ENTITY:
            raise refuse(Refusal.KIND_MISMATCH, where=where, detail=imp.name)
        if not imp.access & Access.READ:
            raise refuse(
                Refusal.ACCESS_DENIED,
                where=where,
                detail=f"{imp.name} is not readable",
            )
        return (*stack, imp.type)
    if op.poly is Poly.HOST_SET:
        imp = _import(container, operand, where)
        if imp.kind != ImportKind.ENTITY:
            raise refuse(Refusal.KIND_MISMATCH, where=where, detail=imp.name)
        if not imp.access & Access.WRITE:
            raise refuse(
                Refusal.ACCESS_DENIED,
                where=where,
                detail=f"{imp.name} is not writable",
            )
        rest, taken = _pop(stack, 1, where, op)
        _expect(taken, (imp.type,), where, op)
        return rest
    if op.poly is Poly.HOST_CALL:
        imp = _import(container, operand, where)
        if imp.kind != ImportKind.FUNCTION:
            raise refuse(Refusal.KIND_MISMATCH, where=where, detail=imp.name)
        rest, taken = _pop(stack, len(imp.param_types), where, op)
        _expect(taken, imp.param_types, where, op)
        return rest if imp.type is ValType.VOID else (*rest, imp.type)
    if op.poly is Poly.CALL:
        callee = _function(container, operand, where)
        rest, taken = _pop(stack, len(callee.local_types[: _arity(callee)]), where, op)
        _expect(taken, tuple(callee.local_types[: _arity(callee)]), where, op)
        return (
            rest if callee.return_type is ValType.VOID else (*rest, callee.return_type)
        )
    if op.poly is Poly.DROP:
        rest, _ = _pop(stack, 1, where, op)
        return rest
    if op.poly is Poly.DUP:
        _, taken = _pop(stack, 1, where, op)
        return stack + taken
    if op.poly is Poly.SELECT:
        rest, taken = _pop(stack, 2, where, op)
        if taken[0] != taken[1]:
            raise refuse(
                Refusal.TYPE_MISMATCH,
                where=where,
                detail=f"else takes two values of one type, got "
                f"{taken[0]} and {taken[1]}",
            )
        return (*rest, taken[0])
    if op.poly is Poly.PREDICATE:
        rest, _ = _pop(stack, 1, where, op)
        return (*rest, ValType.BOOL)
    if op.poly is Poly.RET:
        if fn.return_type is not ValType.VOID:
            raise refuse(
                Refusal.UNBALANCED_RETURN,
                where=where,
                detail=f"{fn.name} returns {fn.return_type}, ret yields nothing",
            )
        if stack:
            raise refuse(
                Refusal.UNBALANCED_RETURN,
                where=where,
                detail=f"the stack still holds [{_fmt(stack)}]",
            )
        return stack
    if op.poly is Poly.RET_V:
        if fn.return_type is ValType.VOID:
            raise refuse(
                Refusal.UNBALANCED_RETURN,
                where=where,
                detail=f"{fn.name} returns nothing, ret_v yields a value",
            )
        rest, taken = _pop(stack, 1, where, op)
        _expect(taken, (fn.return_type,), where, op)
        if rest:
            raise refuse(
                Refusal.UNBALANCED_RETURN,
                where=where,
                detail=f"[{_fmt(rest)}] left below the return value",
            )
        return ()
    raise AssertionError(f"unhandled {op.poly}")  # pragma: no cover


def _arity(fn: Function) -> int:
    """Arguments become the callee's first locals (§3.6); the record does
    not distinguish them, so a function's arity is carried by the caller's
    expectation. Until the ``call`` group is implemented end to end this
    is every local, which is the conservative reading."""
    return len(fn.local_types)


def _local(fn: Function, index: int, where: str) -> ValType:
    if index >= len(fn.local_types):
        raise refuse(
            Refusal.INDEX_OUT_OF_RANGE,
            where=where,
            detail=f"local {index}, {fn.name} declares {len(fn.local_types)}",
        )
    return fn.local_types[index]


def _import(container: Container, index: int, where: str):
    if index >= len(container.imports):
        raise refuse(
            Refusal.INDEX_OUT_OF_RANGE,
            where=where,
            detail=f"import {index}, the table holds {len(container.imports)}",
        )
    return container.imports[index]


def _function(container: Container, index: int, where: str) -> Function:
    if index >= len(container.functions):
        raise refuse(
            Refusal.INDEX_OUT_OF_RANGE,
            where=where,
            detail=f"function {index}, the table holds {len(container.functions)}",
        )
    return container.functions[index]


def _pool(container: Container, index: int, want: ValType, where: str) -> None:
    if index >= len(container.constants):
        raise refuse(
            Refusal.INDEX_OUT_OF_RANGE,
            where=where,
            detail=f"constant {index}, the pool holds {len(container.constants)}",
        )
    if container.constants[index].type is not want:
        raise refuse(
            Refusal.TYPE_MISMATCH,
            where=where,
            detail=f"constant {index} is {container.constants[index].type}, "
            f"the instruction wants {want}",
        )


# -- the call graph -------------------------------------------------------


def _call_graph(
    container: Container, regions: list[tuple[int, int]]
) -> tuple[dict[str, int], dict[str, int]]:
    """Worst-case call depth per function, and the cap of the cycle each
    one belongs to.

    A cap belongs to a **cycle**, not to a function (§5.4): ``a → b → a``
    consumes the stack exactly as ``a → a`` does, and a rule about
    self-calls would let the harder-to-notice case through. So the graph
    is condensed into its strongly connected components, and every
    component that is a cycle needs a cap.
    """
    n = len(container.functions)
    edges: list[set[int]] = [set() for _ in range(n)]
    for index, (start, end) in enumerate(regions):
        pc = start
        while pc < end:
            op = BY_CODE[container.code[pc]]
            if op.poly is Poly.CALL:
                edges[index].add(container.code[pc + 1])
            pc += op.size

    components = _tarjan(edges)
    component_of = {node: i for i, comp in enumerate(components) for node in comp}

    caps: dict[int, int] = {}
    for i, comp in enumerate(components):
        cyclic = len(comp) > 1 or any(node in edges[node] for node in comp)
        if not cyclic:
            caps[i] = 0
            continue
        declared = {container.functions[node].recursion_cap for node in comp}
        names = ", ".join(container.functions[node].name for node in comp)
        if declared == {0}:
            raise refuse(
                Refusal.UNCAPPED_RECURSION,
                where=names,
                detail="a cycle in the call graph without a declared cap",
            )
        if len(declared) > 1:
            raise refuse(
                Refusal.UNCAPPED_RECURSION,
                where=names,
                detail="the functions in one cycle declare different caps: "
                + ", ".join(str(c) for c in sorted(declared)),
            )
        caps[i] = declared.pop()

    # Frames occupied by a component: one for an ordinary function, and
    # for a cycle a sound upper bound of cap × members.
    def frames(i: int) -> int:
        return caps[i] * len(components[i]) if caps[i] else len(components[i])

    depth: dict[int, int] = {}

    def component_depth(i: int) -> int:
        if i in depth:
            return depth[i]
        below = 0
        for node in components[i]:
            for callee in edges[node]:
                j = component_of[callee]
                if j != i:
                    below = max(below, component_depth(j))
        depth[i] = frames(i) + below
        return depth[i]

    result_depth = {}
    result_caps = {}
    for index, fn in enumerate(container.functions):
        i = component_of[index]
        result_depth[fn.name] = component_depth(i) - 1
        result_caps[fn.name] = caps[i]
    return result_depth, result_caps


def _tarjan(edges: list[set[int]]) -> list[list[int]]:
    """Strongly connected components, in reverse topological order."""
    index_of: dict[int, int] = {}
    low: dict[int, int] = {}
    on_stack: set[int] = set()
    stack: list[int] = []
    components: list[list[int]] = []
    counter = 0

    for root in range(len(edges)):
        if root in index_of:
            continue
        # Iterative, because a deep call chain must not blow the host's
        # Python stack while checking a program that cannot recurse.
        work: list[tuple[int, list[int]]] = [(root, sorted(edges[root]))]
        index_of[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            node, pending = work[-1]
            if pending:
                child = pending.pop()
                if child not in index_of:
                    index_of[child] = low[child] = counter
                    counter += 1
                    stack.append(child)
                    on_stack.add(child)
                    work.append((child, sorted(edges[child])))
                elif child in on_stack:
                    low[node] = min(low[node], index_of[child])
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index_of[node]:
                component = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                components.append(component)
    return components
