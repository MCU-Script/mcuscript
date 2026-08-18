<!--
SPDX-FileCopyrightText: 2026 The MCUScript Contributors
SPDX-License-Identifier: Apache-2.0
-->

# 0007 — Loops are bounded, not metered

- Status: draft — decision taken, specification rewritten to it and both
  backends built (2026-08-18).
- Date: 2026-08-18

## Context

Until now the `loop` group was reserved and empty, and specification
§3.8 explained why in a way that turned out not to survive its own
project.

The old text said a conforming container has no backward jump, so every
control flow graph is acyclic, so termination is a property of the
container. It then constrained the future group in advance: *"a counted
loop with a bound the compiler can evaluate, not a general backward
branch. A construct whose iteration count depends on data would put
termination back into the runtime and take the budget question with
it."*

That sentence was written before §5.4's recursion counter was worked
out, and §5.4 does the exact thing the sentence forbids. Recursion
depth *is* data. The specification's own answer is a declared cap plus
a counter that both backends run and that faults on exceeding it —
with termination still proved from the container, because the proof
rests on the cap being finite rather than on anyone predicting the
depth. Repetition and recursion are the same problem, and the project
had already solved it once.

Two smaller findings sharpened the shape.

**The backward branch is already implementable.** `JMP` carries a
signed `off16`, the VM has always read it as `int16_t`, and the ban
lived in exactly one line of the host verifier. So whatever the `loop`
group is, it is not "the instruction that jumps backwards".

**The C backend does not care.** Its docstring claimed forward-only
`goto` was load-bearing. It is not: the backend reads each pc's
operand-stack shape out of the verifier's recorded map rather than
walking it forward, so a loop header already carries the depth its back
edge has to agree with — and `inconsistent_join` is what enforces the
agreement. The claim was inherited from the rule rather than measured
against the code.

Loops were also, separately, a product-owner commitment: the language
gets them, and it is not worth designing the bytecode twice.

## Decision

**One instruction, and it is the bound rather than the branch.**

```
0xA0  LOOP.GUARD idx8   ; --local[idx8]; below zero → iteration_limit
```

1. **A backward branch is `JMP` with a negative offset**, and needs no
   new encoding. What a container with a cycle must declare is the
   `loop` group — not because the branch needs it, but because a build
   without the group would otherwise run the cycle unbounded, and the
   header is that build's one chance to refuse (§2.5).
2. **The counter is an ordinary `i32` local**, set by ordinary
   instructions. Not runtime-owned machinery: a local costs the frame
   nothing it was not already paying, nests correctly because the
   producer zeroes it on entry, and lowers to a countdown any C
   programmer would recognise. A counter never given a value is zero,
   so it faults on the first turn — the safe direction to fail in.
3. **A conforming container has two properties per back edge** (§3.8.1):
   the branch lands *on* a `LOOP.GUARD`, and nothing inside the loop
   assigns that guard's counter. Together they are the termination
   proof: the guard runs once per turn, it strictly decreases an `i32`
   the loop does not otherwise touch, and an `i32` is finite.
4. **Nothing evaluates the bound.** No implementation carries a maximum
   iteration count, no verifier judges whether a number is reasonable,
   and a data-dependent iteration count is perfectly conforming. The
   count decides how many turns happen; the counter decides how many
   turns *can*.
5. **Requiring the guard at the loop header** rather than merely inside
   the body is deliberate. A guard behind a branch would not run on
   every turn, so it would bound nothing — and checking "at the header"
   is a byte comparison where "dominates the back edge" is a dominator
   computation. A producer that wants a bound writes it at the top
   anyway.
6. **A fourth fault, `iteration_limit`** (§5.5). §5.5 said there were
   three and deliberately no others; the sentence now says four, and
   the new one stands beside `recursion_limit` for the same reason —
   neither means the program was wrong, both mean this run needed more
   than the producer allowed for.
7. **Still no execution budget.** No instruction counter, no per-opcode
   cost, nothing in the dispatch loop (§5.6). That was always the
   expensive reading of "bound the program" and it stays refused. A
   guard is paid for by the loop that asked for it; a container without
   cycles pays nothing.
8. **Two refusals replace one.** `backward_branch` is gone;
   `unguarded_loop` and `loop_counter_written` are the two ways a cycle
   fails to be bounded. Both are host-verifier business (ADR 0006) —
   the runtime executes the guard and does not check that one exists.

## Consequences

- **A build without the group is byte-identical to before this
  change.** Measured on cortex-m33, `no loop` comes out at 5,596 bytes,
  which is exactly what `full` measured the day before. Nothing
  regressed for anyone who does not use loops.
- **A build with loops pays 384 bytes**, and almost none of it is the
  instruction. Measured on `vm.o`, cortex-m33, `-Os`:

  | | bytes |
  |---|---:|
  | without the group | 3,058 |
  | guard at `0x96`, packed against `bits` | 3,106 |
  | guard at `0xA0`, its group's range | 3,416 |

  So the case body is **48 bytes** and the other **310** are the
  dispatch table: `0xA0` is the only opcode in the gap between `bits`
  and `i64div`, and one opcode in a hole makes GCC re-lower the whole
  switch. This is a cost of the group *layout* — contiguous ranges per
  group, which is what lets a narrowed build drop a contiguous span —
  and not of loops. It is recorded rather than fixed: moving the range
  would renumber every group to save 310 bytes, and the invariant is
  worth more than that. The useful corollary is that a **second** loop
  instruction would cost about 48 bytes, because the expensive part is
  already paid.
- **The differential tests cover the new shape**, which is where the
  claim lives: a loop that ends by its own test, one that runs out of
  turns (fault and exit code included), one whose counter was never set,
  nested loops with an inner counter the outer body resets, and a loop
  around a host write where order is what could break silently.
- **`spec/corpus/` gained the two refusals and lost one.**
  `ok-every-group` now really means every group.
- **The reserved-group test lost its subject.** Every group this
  version defines is now implemented, so the `unsupported_group` case —
  the one that proves a build refuses at load what it cannot run —
  claims group 7 instead: the shape a container from a later
  specification has. That is arguably the better example anyway.

## Open

- **The recursion cap and the loop bound are now visibly the same
  mechanism with two spellings.** The cap is declared per call-graph
  component in the `ENTR` record and enforced by runtime-held counters;
  the loop bound is an ordinary local the producer initialises. Both are
  right for their case, but a later version might notice they are one
  concept and say so once.
- **Whether a producer must write the bound, and what it defaults to,**
  is a surface-syntax question and belongs to M3. The shape proposed
  and not yet built: the compiler emits no guard at all when it can see
  the count (`for i in 0..10` is a bare backward branch, and costs
  nothing at run time), and requires a written bound exactly when it
  cannot. The provisional default, if any, sits beside the recursion
  cap's provisional 5 — see ADR 0002 §8 question 4.
- **`iteration_limit` is reported with the entry point and the source
  position, like every fault, but not with which loop.** Nothing in the
  container names a loop. If diagnostics want that, the `dbug` section
  is where it would go.
