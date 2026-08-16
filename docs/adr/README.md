<!--
SPDX-FileCopyrightText: 2026 The MCUHome Contributors
SPDX-License-Identifier: Apache-2.0
-->

# Architecture Decision Records

MCUScript design decisions, in lightweight
[MADR](https://adr.github.io/madr/) style: **Context / Decision /
Consequences**, plus a status.

**Scope (boundary rule, ADR 0001):** only decisions about the language,
its compiler, its bytecode and its VM live here — everything an
embedder of MCUScript would need to know. Decisions about *how MCUHome
uses* an engine (which YAML keys lower to script, how a script reaches
a device, which flash region holds it) belong to
[mcu-home/mcuhome](https://github.com/mcu-home/mcuhome/tree/main/docs/adr)
and
[mcu-home/mcuhome-sdk](https://github.com/mcu-home/mcuhome-sdk/tree/main/docs/adr),
even while MCUHome is the only embedder there is.

## Lifecycle: draft first, final when real

ADRs follow the project-wide draft-first lifecycle of
[mcuhome ADR 0021](https://github.com/mcu-home/mcuhome/blob/main/docs/adr/0021-draft-first-adr-lifecycle.md):
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
