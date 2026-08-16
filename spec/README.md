<!--
SPDX-FileCopyrightText: 2026 The MCUScript Contributors
SPDX-License-Identifier: Apache-2.0
-->

# The MCUScript specification

- Specification version: **0.1.0-draft**
- Status: **in progress** — see the document map below for what exists

This is the contract. Everything else in this repository is an
implementation of it, including the reference compiler, the VM and the
C backend, and a third party implementing any of those from this
document alone should arrive at something that interoperates.

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

Where identity cannot be guaranteed by the specification alone — the
floating-point cases, which depend on how the embedder compiles the
generated C — the document says so and states the requirement on the
build (§1.5).

## Conformance

An implementation conforms if it:

1. accepts every container this document calls well-formed, and
   **refuses** every container it does not, with the error this
   document names;
2. produces, for every well-formed container, the results this document
   prescribes;
3. performs load-time verification unconditionally (§2.6) — this is not
   a build option, because the alternative is a VM that sizes its own
   stack from a number an untrusted file supplied;
4. implements at least the `core` instruction group, and refuses at
   load any container requiring a group it does not implement (§2.5).

## Document map

| Document | Contents | Status |
|---|---|---|
| [01-value-model.md](01-value-model.md) | Types, slots, validity states, numeric semantics | written |
| [02-container.md](02-container.md) | The binary format, sections, verification, loading | written |
| 03-instructions.md | The instruction table and per-instruction semantics | not written |
| 04-linking.md | The host interface, name resolution, the error taxonomy | not written |
| 05-execution.md | Entry points, frames, termination, faults | not written |

Chapters 3 to 5 are next. Nothing in 1 and 2 is expected to survive
untouched until they exist — a value model is only as good as the
instructions that turn out to need it.

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
