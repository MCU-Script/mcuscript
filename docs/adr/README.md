<!--
SPDX-FileCopyrightText: 2026 The MCUScript Contributors
SPDX-License-Identifier: Apache-2.0
-->

# Architecture Decision Records

MCUScript design decisions, in lightweight
[MADR](https://adr.github.io/madr/) style: **Context / Decision /
Consequences**, plus a status.

**Scope (boundary rule, ADR 0001):** the design has three layers and
only the first lives here — **the language** (grammar, type system, the
unit mechanism, the bytecode container and its verifier, the VM and its
feature modules, the C API toward embedders). **A profile** — which
dimensions exist, how units are spelled, which base unit each
normalizes to — belongs to that profile's own repository. **An
embedding** — which of the embedder's configuration lowers to script,
how a script reaches a device, which flash region holds it — belongs to
the embedder, today
[mcu-home/mcuhome](https://github.com/mcu-home/mcuhome/tree/main/docs/adr)
and
[mcu-home/mcuhome-sdk](https://github.com/mcu-home/mcuhome-sdk/tree/main/docs/adr).
That holds even while MCUHome is the only embedder there is.

## Lifecycle: draft first, final when real

ADRs follow the draft-first lifecycle of
[mcuhome ADR 0021](https://github.com/mcu-home/mcuhome/blob/main/docs/adr/0021-draft-first-adr-lifecycle.md),
adopted here because it is a good process, not because MCUHome owns the
process (ADR 0003):
an ADR starts in [`draft/`](draft/) as a **living document** — while
the thing it decides about is being built, changes land as better text,
never as amendment or erratum sections; git history is the changelog.
`draft` describes the document's maturity, not missing approval. When
the component is implemented and verified, the ADR is finalized:
rewritten from the real result and moved to this directory with a
`Finalized:` date, immutable from then on except for its status line.
Numbers come from one sequence and follow the document for life.

Statuses: `draft` (in `draft/`), `accepted`, `deferred`,
`superseded by NNNN`.

## Final ADRs

None. Nothing is implemented, so nothing can be written from a real
result yet.

## Draft ADRs

| ADR | Title |
|---|---|
| [0001](draft/0001-record-mcuscript-decisions-here.md) | Record MCUScript decisions in this repository |
| [0002](draft/0002-inherited-context.md) | Inherited context: what is already decided, and where it is written down |
| [0003](draft/0003-name-organization-positioning.md) | The name, the organization, and what this project is positioned as |

Start with [0002](draft/0002-inherited-context.md). It marks every item
as **decided**, **recorded direction** or **on the table**, and its §8
is the list of open questions — which is the actual work list.
