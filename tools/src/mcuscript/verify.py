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
    #: Slots an invocation starting here needs: this frame plus every
    #: frame that can be live below it (§5.3). This is the number a
    #: device sizes a buffer from; ``max_call_depth`` counts frames, and
    #: frames are not a resource.
    max_slots: int = 0
    #: Which strongly connected component of the call graph the function
    #: belongs to, named by its **lowest member's index** (§4.3). Two
    #: functions share a runtime recursion counter exactly when they
    #: share this (§5.4). The naming is normative rather than an
    #: implementation's own, because the container declares it.
    component: int = 0


def verify(
    container: Container, *, implemented: frozenset[Group] = IMPLEMENTED_GROUPS
) -> dict[str, FunctionFacts]:
    """Verify a container. Raises :class:`~mcuscript.errors.Refused`, or
    returns the facts it computed, per function name."""
    container.check_groups(implemented)
    facts = analyze(container)

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
        if fn.component != computed.component:
            # A runtime takes this one on trust and shares a recursion
            # counter by it, so a wrong grouping is a cap that does not
            # bind — two functions in one cycle counting separately.
            raise refuse(
                Refusal.MALFORMED_SECTION,
                where=fn.name,
                detail=f"declares call-graph component {fn.component}, "
                f"belongs to {computed.component}",
            )
    return facts


def analyze(container: Container) -> dict[str, FunctionFacts]:
    """Compute the resource numbers without checking them against the
    container's own. This is what an encoder calls to fill them in; a
    loader calls :func:`verify`.

    The cycle checks of §5.4 run here rather than in :func:`verify`,
    because they are not a comparison against a declared number — an
    uncapped cycle has no worst case for an encoder to write down.
    """
    regions = _code_regions(container)
    facts = {}
    for index, fn in enumerate(container.functions):
        facts[fn.name] = FunctionFacts(
            _walk(container, fn, index, regions[index]), 0, 0
        )
    graph = _call_graph(
        container, regions, {name: f.max_stack for name, f in facts.items()}
    )
    return {
        name: replace(
            f,
            max_call_depth=graph.call_depth[name],
            recursion_cap=graph.cap[name],
            max_slots=graph.slots[name],
            component=graph.component[name],
        )
        for name, f in facts.items()
    }


# -- code regions ---------------------------------------------------------


def _code_regions(container: Container) -> list[tuple[int, int]]:
    """Each function owns a half-open byte range of ``CODE``.

    The ranges tile the section: a branch target outside the function's
    own range is refused (§2.6), so the extent has to be defined, and
    defining it as a tiling is what makes "outside" mean something. It
    also leaves no unaccounted bytes in the section.

    The records are required to arrive in code order (§4.3), so this is
    one walk rather than a sort. That is a rule about the writer, and it
    costs a writer nothing: code goes into the section in some order
    already, and the records can be numbered in the same one.
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

    regions: list[tuple[int, int]] = []
    expected = 0
    for index, fn in enumerate(container.functions):
        start = fn.code_offset
        if start != expected:
            raise refuse(
                Refusal.MALFORMED_SECTION,
                where=fn.name,
                detail=f"code starts at {start}, the previous function ends "
                f"at {expected}"
                + ("" if index == 0 else "; records must be in code order"),
            )
        last = index == n - 1
        end = (
            len(container.code) if last else container.functions[index + 1].code_offset
        )
        if end <= start:
            raise refuse(
                Refusal.MALFORMED_SECTION,
                where=fn.name,
                detail="empty code region",
            )
        regions.append((start, end))
        expected = end
    return regions


# -- the type-stack walk --------------------------------------------------


def stack_shapes(container: Container) -> dict[str, dict[int, Stack]]:
    """The verified type stack entering every reachable instruction.

    The C backend needs it: knowing the depth at each instruction is what
    turns a stack machine into named local variables. It comes from the
    verifier rather than from a second walk, because a second walk is a
    second thing to be wrong.
    """
    regions = _code_regions(container)
    out = {}
    for index, fn in enumerate(container.functions):
        shapes: dict[int, Stack] = {}
        _walk(container, fn, index, regions[index], shapes)
        out[fn.name] = shapes
    return out


def _walk(
    container: Container,
    fn: Function,
    index: int,
    region: tuple[int, int],
    record: dict[int, Stack] | None = None,
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
    successors: dict[int, set[int]] = {}
    back_edges: list[tuple[int, int]] = []
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
            if record is not None:
                record[pc] = stack

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
                if not (start <= target < end):
                    raise refuse(
                        Refusal.BAD_BRANCH_TARGET,
                        where=where(pc),
                        detail=f"target {target - start} is outside {fn.name}'s code",
                    )
                successors.setdefault(pc, set()).add(target)
                if target <= pc:
                    back_edges.append((pc, target))
                work.append((target, stack))
                if op.name == "jmp":
                    break
            successors.setdefault(pc, set()).add(after)
            if after >= end:
                raise refuse(
                    Refusal.BAD_BRANCH_TARGET,
                    where=where(pc),
                    detail="execution runs off the end of the function; "
                    "the last instruction on every path must be a return",
                )
            pc = after

    _check_coverage(covered, fn)
    _check_termination(code, fn, start, back_edges, successors)
    return high_water


def _check_termination(
    code: bytes,
    fn: Function,
    start: int,
    back_edges: list[tuple[int, int]],
    successors: dict[int, set[int]],
) -> None:
    """Every cycle in the control flow graph is bounded (§3.8).

    The proof this looks for is deliberately the crudest one that works.
    A back edge is a cycle, so make each back edge land on a
    ``loop.guard``: then the guard runs on every traversal, and since it
    decrements an ``i32`` that the loop does not otherwise write, the
    cycle can turn at most as many times as that counter's entry value.
    Termination follows from the counter being finite, not from anyone
    reading the number — which is why nothing here evaluates the bound
    and why the runtime does not carry one.

    Requiring the guard **at** the loop header rather than merely
    somewhere inside it is what keeps this a comparison instead of a
    dominator computation. A guard buried in an ``if`` inside the body
    would not run on every turn, and a producer that wants a bound
    writes it at the top anyway.
    """
    if not back_edges:
        return

    predecessors: dict[int, set[int]] = {}
    for pc, targets in successors.items():
        for target in targets:
            predecessors.setdefault(target, set()).add(pc)

    for branch, header in back_edges:
        where = f"{fn.name}+{branch - start}"
        guard = BY_CODE.get(code[header])
        if guard is None or guard.poly is not Poly.LOOP_GUARD:
            raise refuse(
                Refusal.UNGUARDED_LOOP,
                where=where,
                detail=f"jumps back to {header - start}, which is not a loop.guard",
            )
        counter = code[header + 1]

        # The natural loop of this back edge: the header, plus every
        # node that reaches the branch without going through the header.
        body = {header}
        pending = [branch]
        while pending:
            node = pending.pop()
            if node in body:
                continue
            body.add(node)
            pending.extend(predecessors.get(node, ()))

        for node in sorted(body):
            op = BY_CODE.get(code[node])
            if op is None or op.poly is not Poly.LOCAL_SET:
                continue
            if code[node + 1] == counter:
                raise refuse(
                    Refusal.LOOP_COUNTER_WRITTEN,
                    where=f"{fn.name}+{node - start}",
                    detail=f"local {counter} is the counter of the loop at "
                    f"{header - start}, so the bound would not hold",
                )


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

    if op.poly is Poly.LOOP_GUARD:
        want = _local(fn, operand, where)
        if want is not ValType.I32:
            raise refuse(
                Refusal.TYPE_MISMATCH,
                where=where,
                detail=f"a loop counter is i32, local {operand} is {want}",
            )
        return stack
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
        rest, taken = _pop(stack, callee.param_count, where, op)
        _expect(taken, callee.param_types, where, op)
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


@dataclass(frozen=True, slots=True)
class _Graph:
    call_depth: dict[str, int]
    cap: dict[str, int]
    slots: dict[str, int]
    component: dict[str, int]


def _call_graph(
    container: Container, regions: list[tuple[int, int]], stacks: dict[str, int]
) -> _Graph:
    """Worst-case call depth and slot use per function, and the cap of
    the cycle each one belongs to.

    A cap belongs to a **cycle**, not to a function (§5.4): ``a → b → a``
    consumes the stack exactly as ``a → a`` does, and a rule about
    self-calls would let the harder-to-notice case through. So the graph
    is condensed into its strongly connected components, and every
    component that is a cycle needs a cap — and only a cycle may have
    one, because a cap that bounds nothing is a number that reads as a
    safeguard and is not.
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

    # A function nothing can reach is the defect `unreachable_code`
    # catches inside a function, one level up: it cannot execute, so it
    # is not a safety problem, but it is either an encoder bug or
    # something smuggled in. It is also a program the two backends do
    # not agree on — a C compiler rejects a static function nobody
    # calls, and a VM never notices.
    reached: set[int] = set()
    work = [i for i, fn in enumerate(container.functions) if fn.invocable]
    while work:
        node = work.pop()
        if node in reached:
            continue
        reached.add(node)
        work.extend(edges[node])
    for index, fn in enumerate(container.functions):
        if index not in reached:
            raise refuse(
                Refusal.UNREACHABLE_CODE,
                where=fn.name,
                detail="no entry point reaches this function",
            )

    components = _tarjan(edges)
    component_of = {node: i for i, comp in enumerate(components) for node in comp}

    caps: dict[int, int] = {}
    for i, comp in enumerate(components):
        cyclic = len(comp) > 1 or any(node in edges[node] for node in comp)
        declared = {container.functions[node].recursion_cap for node in comp}
        names = ", ".join(container.functions[node].name for node in comp)
        if not cyclic:
            caps[i] = 0
            if declared != {0}:
                raise refuse(
                    Refusal.RECURSION_CAP_MISMATCH,
                    where=names,
                    detail="declares a cap but is in no cycle",
                )
            continue
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

    def frame(node: int) -> int:
        fn = container.functions[node]
        return len(fn.local_types) + stacks[fn.name]

    # A component's cost, in frames and in slots. The counter of §5.4
    # is per component and counts entries into *any* member, so a capped
    # component contributes at most `cap` frames however the cycle is
    # spelled — `a → b → a → b → a` is five, exactly as `a → a → a → a →
    # a` is. Slots take the largest member, since which of them fills
    # those frames is data.
    def frames(i: int) -> int:
        return caps[i] if caps[i] else 1

    def component_slots(i: int) -> int:
        return frames(i) * max(frame(node) for node in components[i])

    depth: dict[int, int] = {}
    slots: dict[int, int] = {}

    def below(i: int, of) -> int:
        return max(
            (
                of(component_of[callee])
                for node in components[i]
                for callee in edges[node]
                if component_of[callee] != i
            ),
            default=0,
        )

    def component_depth(i: int) -> int:
        if i not in depth:
            depth[i] = frames(i) + below(i, component_depth)
        return depth[i]

    def component_slot_total(i: int) -> int:
        if i not in slots:
            slots[i] = component_slots(i) + below(i, component_slot_total)
        return slots[i]

    return _Graph(
        call_depth={
            fn.name: component_depth(component_of[index]) - 1
            for index, fn in enumerate(container.functions)
        },
        cap={
            fn.name: caps[component_of[index]]
            for index, fn in enumerate(container.functions)
        },
        slots={
            fn.name: component_slot_total(component_of[index])
            for index, fn in enumerate(container.functions)
        },
        # Named by the lowest member's index, not by Tarjan's numbering:
        # this value is written into the container (§4.3), so it has to
        # be the same in every implementation and derivable from the
        # function table alone.
        component={
            fn.name: min(components[component_of[index]])
            for index, fn in enumerate(container.functions)
        },
    )


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
