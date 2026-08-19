<!--
SPDX-FileCopyrightText: 2026 The MCUScript Contributors
SPDX-License-Identifier: Apache-2.0
-->

# 0010 — Four instructions the syntax needed

- Status: draft — decision taken, specification rewritten to it and both
  backends built (2026-08-19).
- Date: 2026-08-19

## Context

Chapter 6 was written from the language downwards and then checked
against the container underneath it. Almost everything the built half of
the syntax says already had a lowering: `if` and `match` are branches,
`else` is one instruction, a unit suffix is a number by the time it
reaches the container. §6.13 named the exceptions — **four `core`
instructions the syntax needs and the instruction set does not have** —
and left their encodings to be assigned when somebody implemented them.
This is that.

Two of them are missing for the same underlying reason: **validity is
not a value in this language, it is a companion**, and there was no
way to *choose* one.

### Boolean `and` and `or`

§6.3.3 decided that `and` and `or` **do not short-circuit**, and §3.3
said the opposite in a sentence written months earlier: *"There is no
`AND` or `OR` instruction. The language's `and` and `or` short-circuit,
which makes them control flow, and the compiler lowers them to
branches."*

The two cannot both stand, and the syntax chapter is the one with the
argument behind it. A branch on a `bool` requires that `bool` to be
`valid` (§1.3.1). So the short-circuiting lowering of `temp > 25 and
humidity > 60`, with the humidity sensor silent, **faults** — on
exactly the input the construct is for. The propagating one yields an
`unavailable` `bool`, which the script can fall back from with `else
false`. Nothing else in the instruction set took two `bool`s: `NOT` is
unary, and the `bits` group's `AND.i32` is a different operation on a
different type.

### A state a program chose

Every validity state in the machine arose as a *side effect* — of an
operand, of a host read with no reading, of division by zero. §6.3.5
needs two things that are not side effects: a `match` whose subject is
not valid must yield that state without evaluating an arm, and
`invalid -> invalid` must be writable, which is how a script says that
a faulted reading stays faulted instead of becoming a number somebody
will later read as a measurement.

## Decision

Four instructions in `core`, at `0x2C`–`0x2F`.

| Opcode | Instruction | Effect |
|---|---|---|
| `0x2C` | `CONST.unavailable type8` | `→ T` |
| `0x2D` | `CONST.invalid type8` | `→ T` |
| `0x2E` | `AND` | `bool bool → bool` |
| `0x2F` | `OR` | `bool bool → bool` |

**1. Validity propagates as the maximum, with no exception for the
booleans.** `false AND unavailable` is `unavailable`, not `false`. The
short answer is defensible in isolation — SQL's three-valued logic gives
it — and it was refused twice over: it would be the only place in the
instruction set where §1.3's one rule does not hold, and it would put a
branch in both backends where there is none today. A script that wants
the short answer writes `… else false` and thereby says so. The same
argument applies to `invalid`, where the case against is stronger: a
defect quietly answered away is a defect nobody reports.

**2. A chosen state's value is zero, normatively.** `0`, `0.0`, `false`.
It is tempting to call the value of a non-valid slot unspecified, and it
would be wrong: a non-valid value still reaches a host write and still
reaches an entry point's result, so an embedder sees those bytes, and
two backends that filled the slot differently would diverge on them
while both claimed to be right.

**3. The type is an operand, not four opcodes per state.** A new operand
kind, `type8`, carrying a type code of §4.1 — not an index, which is
what every other one-byte operand is, and the distinct kind is what
keeps a reader from looking the byte up in a table it has nothing to do
with. `void` is refused.

This looks like a contradiction of §3.2, which puts the type in the
*opcode* and says why: with a type byte, float handling would sit inside
every arithmetic handler and could not be removed with its group. It is
not a contradiction, it is the same rule applied. That argument bites
where the handler differs per type, and here no handler reads the
operand at all — one handler pushes a zero and a state whatever the
byte says. The type exists for the **verifier's** stack, which is
therefore also the only place a wrong one can be caught; nothing
downstream would notice. It follows that `CONST.invalid i64` in a
`core`-only container is conforming, because an `i64`-typed value never
needed the `i64` group — only 64-bit arithmetic did.

**4. `AND` and `OR` are at `0x2E`–`0x2F` rather than beside `NOT` at
`0x1E`.** The bool block had one free code and this needed two. Moving
`NOT` was rejected: §3.4 already states the project's rule that a gap
stays where it is so a reader of an older document lands on nothing
rather than on something else, and renumbering a live opcode is a worse
version of the same hazard. A pair a compiler emits from one construct
is better kept together than split to sit under its heading.

## Consequences

- §3.3 gains six rows and loses the paragraph that said the language
  short-circuits. §6.13 changes from a list of what the container must
  gain to a record of what it gained.
- Two corpus cases (ADR 0005): `ok-chosen-state`, which a verifier that
  reads the `type8` operand as an index will refuse; and
  `chosen-state-of-no-type`, a `void` operand, which is `type_mismatch`
  and which nothing but a verifier can catch.
- The instruction set is complete for the built half of chapter 6.
  Everything still marked **planned** there needs container work that is
  larger than opcodes — an arena section for arrays, a string area and a
  string parameter kind on imports (§6.9, §6.10) — and none of it is
  required by anything marked **built**.
- Code generation, the next step, now has a target for every construct
  the front end accepts.

## What this does not decide

Whether the compiler ever *emits* a branch for `and`. It may not: the
semantics are the propagating ones, and an optimizer that noticed a
provably `valid` operand and short-circuited anyway would be changing
which host calls run. The instructions are the lowering, not a fallback
for one.
