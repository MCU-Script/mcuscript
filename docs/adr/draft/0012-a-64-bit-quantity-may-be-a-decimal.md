<!--
SPDX-FileCopyrightText: 2026 The MCUScript Contributors
SPDX-License-Identifier: Apache-2.0
-->

# 0012 — A 64-bit quantity may be a decimal

- Status: draft — decision taken, specification rewritten to it and both
  backends built (2026-08-20).
- Date: 2026-08-20

## Context

Writing the code generator (ADR 0011) found that the instruction set
converts between `i32` and each of the other types and **not** between
`i64` and `f32`. Three ordinary things had no lowering because of it:

```
to_f32(counter)          # a 64-bit count as a decimal
to_i64(2.5)              # the other direction
a / b                    # two dimensionless i64s — §6.5.5 says f32
```

The first proposal was to leave all three refused: the case looked rare,
and adding the instructions meant a second cross-group dependency in a
set where §3.2 had allowed exactly one.

**The product owner refused that reading, with the argument that
settles it: a dimension's data type is the profile's to choose.** A
profile may hold energy in an `i64` and a ratio in an `f32`, and a
script that divides two energies has a decimal on its hands whatever
anybody prefers. Under the refusal that script has no way to say what it
means — not a clumsy way, none — and the language would be telling a
profile author that some data types are second-class. "It would be odd
if you suddenly could not convert between `i64` and `f32`, and above
all a problem where a dimension is itself defined as one of them."

## Decision

Two instructions in the `float` group:

| Opcode | Instruction | Effect |
|---|---|---|
| `0x72` | `CONVERT.i64_f32` | `i64 → f32`, round-to-nearest-even |
| `0x73` | `TRUNC.f32_i64` | `f32 → i64`, toward zero; `invalid` if NaN or out of range |

**They need `i64` as well as `float`, and that is a dependency rather
than a group.** They sit in the `float` range because that is where
every other conversion to and from a decimal is and a reader looks
there; they touch a type only `i64` puts on the stack, so a container
using one declares **both** bits and an implementation compiles the pair
only where it has both — the product owner's own formulation, and the
same shape §3.2 already allows for `i64div`.

The dependency is in the instruction table rather than in prose: an
opcode may name a second group it needs, and the mask a container
declares is computed from that. A verifier that reads group bits off the
opcode ranges alone gets such a container's mask wrong, which is why
`ok-every-group` in the corpus now contains the pair.

**`CONVERT.i64_f32` rounds and that is not a fault.** 64 bits do not fit
in 24 of mantissa. Round-to-nearest-even is what C does under IEEE-754,
so both backends agree by construction — the same argument that put the
arithmetic helpers in a shared header (ADR 0004).

## Consequences

- The four-way conversion table is complete: every pair of numeric types
  converts, in both directions, and §6.3.10's built-ins work on every
  data type a profile can declare.
- `i64` and `float` are no longer independent in the way §3.2 first
  claimed. The text says so now, and names the two instructions rather
  than leaving a reader to find them.
- Two of the four constructs ADR 0011 recorded as deliberately refused
  are gone. What remains refused is 64-bit bitwise (there are no such
  instructions, §3.7) and a 64-bit loop range (the guard counts in
  `i32`, §3.8) — both about the *instruction set's shape* rather than
  about a type being second-class.
- The runtime grows two handlers in a build that has both groups and
  nothing in a build that does not.
