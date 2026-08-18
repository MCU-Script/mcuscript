<!--
SPDX-FileCopyrightText: 2026 The MCUScript Contributors
SPDX-License-Identifier: Apache-2.0
-->

# The MCUScript specification

- Specification version: **0.1.0-draft**
- Status: **complete in draft, and fully executed.** All five chapters
  have an implementation: a verifier, an interpreter and a C backend,
  and a differential test that runs the same container through both
  backends and compares the bytes. **Every instruction the document
  defines works end to end in both backends** — `core`, `i64`,
  `i64div`, `float`, `call`, `bits` and `loop`. No group is reserved
  any more.

This is the contract. Everything else in this repository is an
implementation of it, including the reference compiler, the VM and the
C backend, and a third party implementing any of those from this
document alone should arrive at something that interoperates.

What the contract covers, and what it deliberately does not: this
document defines what a **conforming container** is and what a runtime
does with one. It does not oblige a runtime to establish that its input
is conforming, and §2.6 explains why a language with two backends cannot
make that a conformance rule without implying a guarantee it has no way
to keep. Getting a container from a compiler to a device unaltered is
the embedder's concern, identically for either backend.

## What is specified here, and what is not

Specified: the value model, the binary container, the instruction set
and its semantics, the loading and linking rules, and the errors. A
conforming implementation agrees with this document on all of them.

**Not** specified, on purpose:

- **The surface syntax.** A compiler reads source and emits a
  container; this document describes the container. The language's
  grammar gets its own document, and a second front end producing
  conforming containers is legitimate.
- **How a container reaches a device**, what vouches for it, and where
  it is stored. It may arrive over an authenticated channel, be
  embedded in a firmware image, or sit on a filesystem as a file.
  That is the embedder's, and the container is deliberately built so an
  embedder can attach whatever it needs (§2, ancillary sections).
- **What the host offers.** The set of entities and host functions a
  script may reach, their names, and what happens when one is written,
  belong to the embedder. This document specifies only how a script
  *refers* to them and how those references are resolved.
- **When a write takes effect.** Whether an embedder applies writes
  immediately or buffers them to a commit point is its policy. What
  this document does fix is that a script always reads back what it
  wrote (§1.6) — the two are independent, and only the second is
  observable to a script.
- **Which units exist.** The language defines the *mechanism* — a
  literal may carry a unit suffix, a suffix belongs to a dimension, a
  dimension normalizes to a base unit — and a **profile** supplies the
  table. Profiles are versioned separately and pinned in the container
  header.

## The two backends

Every program has two lowerings and must have both: a container of
bytecode for the VM, and C source compiled into the firmware. **They
must produce identical results.** This is not an aspiration; it is what
makes the choice between them a deployment decision rather than a
semantic one, and it is why this document pins down behaviour that a
language of this size might otherwise leave to the implementation —
integer wrapping, division by zero, shift counts, the propagation of
absent values.

Where identity depends on how the embedder compiles the generated C —
the floating-point cases — the document states the requirement on the
build (§1.5), and it states it from measurement: a careless build does
diverge, and the test suite proves it by compiling one program both
ways and asserting that the results come apart.

**It is bit-identity, not a tolerance**, and §1.5.1 says why: a
comparison feeds a branch, so one ULP of disagreement is not one ULP of
output, it is a different arm of the ladder.

## Conformance

There are three kinds of implementation, and each conforms to a
different thing.

A **compiler** conforms if every container it emits is conforming
(§2.6).

A **runtime** conforms if it:

1. produces, for every conforming container, the results this document
   prescribes;
2. implements at least the `core` instruction group, and refuses at load
   any container whose header requires a group it does not implement, or
   whose profile pin, format version or magic do not match (§2.5, §2.7).

A runtime's behaviour on a **non-conforming** container is undefined,
and that is deliberate rather than an omission — see §2.6, which says
why a language with two backends cannot make the promise the other
reading would imply. A runtime that wants to be safe against arbitrary
input contains a verifier; that is the third kind.

A **verifier** conforms if it accepts exactly the conforming containers
and refuses everything else with the error this document names (§2.6.0).
It is an optional component, and `corpus/` is what one is checked
against.

## Document map

| Document | Contents |
|---|---|
| [01-value-model.md](01-value-model.md) | Types, slots, validity states, numeric semantics |
| [02-container.md](02-container.md) | The binary format, its sections, and what makes a container conforming |
| [03-instructions.md](03-instructions.md) | The instruction set, group by group, with a worked example |
| [04-linking.md](04-linking.md) | The constant, entry-point and import tables; name resolution; every error |
| [05-execution.md](05-execution.md) | Invocation, frames, recursion, faults, termination |
| [corpus/](corpus/) | **Containers, with the verdict each must get.** Not prose — how an implementation checks itself against the four documents above |

All five exist in draft, and each round of work on them changes the
ones before. Writing 3 to 5 changed 1 and 2 twice: `DUP` turned out to
be the one instruction that pushes more than it pops, and the group
table gained two entries.

Then implementing 2 and 4 changed them again, in eight places, and the
list is worth keeping because it is what the exercise is for:

- the checksum said "CRC32", which names at least four incompatible
  functions — now CRC-32/ISO-HDLC, by name;
- the `ENTR` record was missing the flag §4.3 said it had, and the
  recursion cap §5.4 requires;
- the string area's encoding was described as "length-prefixed" and
  never specified;
- "at most 256 constants" was 255;
- `HOST` was both mandatory and omittable;
- a function's **code region** was never defined, so "a branch outside
  the function" had no meaning;
- two refusals had no names (`reserved_field_set`, `unreachable_code`);
- and the worked example in §3.9 printed a branch offset of `+7` where
  the encoder computes `+5`.

None of those is a change of design. Every one of them is a place where
the document read as though it said something and did not, and no
amount of re-reading had found them.

Then the VM and the C backend found the next set, which is the one the
prediction above was about. Writing `call` found four more, and the
first two are the interesting kind — a chapter that had been read many
times and still did not say the thing it was about:

- **a function had no arity.** §3.6 said arguments become the callee's
  first locals and §4.3's record did not say how many there were, so a
  caller's pushes could not be counted and every local had to be an
  argument. `param_count` is now in the record;
- **`max_call_depth` was over-estimated.** The verifier took a cycle's
  worst case to be its cap times its member count, and the runtime
  counter §5.4 specifies counts entries into the component — so the
  bound is the cap, whatever the cycle's shape. The two numbers had
  never met because nothing executed a cycle;
- entry points had to be forbidden parameters, which nothing had said,
  because the host has no argument channel and the two backends would
  have disagreed about what an unsupplied one holds;
- a function no entry point reaches had to become `unreachable_code`,
  for the reason §2.6.1 already gives about dead bytes, plus one more:
  it is a container only one backend can express.

The corresponding defect in the code is worth naming too, because it is
what the exercise buys. The C loader's check that code regions tile
`CODE` was wrong in a way that made every two-function container
`malformed_section` — and every container until now had one function.

Then the [corpus](corpus/) found three more, and it found them while
being *written* rather than while running — its rule that every named
refusal must have a container is what does the work:

- **`import_limit` named nothing** and is gone. Neither implementation
  had ever raised it, and its two possible readings are
  `unknown_import` and "this build is too small" — the second of which
  cannot be in a conformance taxonomy, because it refuses a container
  this document calls well-formed;
- **`kind_mismatch` and `access_denied` have two occasions each**, and
  §4.6 listed one. A container can contradict *itself* about an import
  as well as contradict the registry, and only the second needs an
  embedder — which decides whether a host toolchain must refuse or
  accept;
- **`duplicate_import` was filed as a linking error** and needs no
  registry to see.

Then measuring the runtime's footprint found the sixteenth, and this one
was a place where the document was right and only one implementation had
read it. §2.6 point 1 says an instruction's opcode must be "defined in a
required group": an opcode from a group the header does not declare is
undefined *for that container*. The host verifier did that; the C loader
checked only whether the opcode existed, so a container declaring `core`
and containing `add.i64` was refused by one and **executed** by the
other. §2.5 now states the duty separately instead of leaving it inside a
compound sentence, because the check reads like a courtesy to small
builds and is not one — under-declaration is how a container reaches an
implementation that lacks the group with nothing left to stop it.

Two things that follow are worth writing down. The corpus did not catch
this, and could not have: its completeness rule asks whether every
*named refusal* has a container, and a rule nobody implemented produces
no new name. And the divergence is the two-implementation design paying
for itself — one loader alone would have been self-consistently wrong.

## The change of 2026-08-17

The seventeenth correction is not a correction at all but a change of
what this document *is for*, in one place, and it is worth separating
from the list above.

§2.6 used to make verification a **conformance rule**: an implementation
that ran unverified containers did not conform. It now defines what a
conforming **container** is, and leaves deciding that about arbitrary
bytes to an optional component (§2.6.0).

The reason is the two backends. The same source is equally expressible
as a container for a VM or as C built into the firmware, and nothing
protects the C on its way to a device. Obliging every runtime to police
its input gave one of two equivalent paths a guarantee the other cannot
have — and invited the reading that the language protects a device
against code it did not produce, which it does not and cannot. The
properties in §2.6 are unchanged, down to the arithmetic; what moved is
whose duty they are. Reasoning: ADR 0006.

## Versioning

Three version numbers appear in this project and they are not the same
thing:

- the **specification version** (this document, `0.1.0-draft`), which
  is what an implementation claims to conform to;
- the **container format version**, a single integer in the header
  (§2.1), incremented whenever a change would make an older reader
  misread a newer file — a reader refuses anything above the version it
  knows;
- the **profile version**, owned by the profile, pinned in the header,
  and checked at load, because a changed base unit makes existing
  bytecode silently wrong (§1.4).

Before 1.0 the specification version may break anything. From 1.0 the
container format version is the compatibility promise.
