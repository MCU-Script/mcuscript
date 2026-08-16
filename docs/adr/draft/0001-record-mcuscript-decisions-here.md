<!--
SPDX-FileCopyrightText: 2026 The MCUHome Contributors
SPDX-License-Identifier: Apache-2.0
-->

# 0001 — Record MCUScript decisions in this repository

- Status: draft
- Date: 2026-08-16

## Context

MCUScript starts as an empty repository with a long prehistory. The
decision that a scripting engine grown from MCUHome's expression tier
would be *a project of its own* is itself older than this repository
([component-model.md §10](https://github.com/mcu-home/mcuhome-sdk/blob/main/docs/design/component-model.md),
product owner, 2026-08-07), and everything decided about scripting so
far is written in MCUHome documents, because MCUHome was the only place
to write it.

That is a problem the moment the repository exists: a reader here would
find nothing, a reader there would find scripting decisions scattered
across a design document, four ADRs and a validation gate, and neither
would know which of them still bind. MCUHome's own repositories solved
the same problem twice already — the CLI's decisions were extracted out
of the firmware ADRs into
[cli ADR 0001](https://github.com/mcu-home/cli/blob/main/docs/adr/draft/0001-record-cli-decisions-here.md),
and the project-wide/SDK split was drawn by
[mcuhome ADR 0024](https://github.com/mcu-home/mcuhome/blob/main/docs/adr/draft/0024-sdk-and-tools-repositories.md).

## Decision

MCUScript design decisions are recorded as ADRs in this repository,
following the project-wide draft-first lifecycle of
[mcuhome ADR 0021](https://github.com/mcu-home/mcuhome/blob/main/docs/adr/0021-draft-first-adr-lifecycle.md):
drafts in `docs/adr/draft/` are living documents; a final ADR is
written from the real result once the component is done, and is then
immutable.

**Own number sequence.** MCUHome and mcuhome-sdk share one sequence
because they are two halves of one product; the CLI and the dashboard
have their own. MCUScript is a standalone project with its own
embedders, so it starts at 0001 and counts on its own. An MCUScript ADR
is never cited as "ADR NNNN" outside this repository without the
`mcuscript` prefix, and this repository prefixes foreign numbers the
same way (`mcuhome ADR 0014`, `cli ADR 0003`).

**Boundary rule.** ADRs here may only concern MCUScript itself: the
language and its grammar, the compiler, the bytecode format and its
verifier, the VM and its feature modules, the C API toward embedders,
diagnostics, and this project's own versioning and release rules. The
test: *would this decision still have to be made if the only embedder
were somebody else's project?* If yes, it belongs here. If it is about
what MCUHome does with the engine — which YAML constructs lower to
script, how a script is transported to a device, which flash region
holds it, when a device rebuilds instead of pushing — it belongs in the
MCUHome repositories, and this repository only cites it.

The boundary is stated now, while MCUHome is the only embedder, because
that is exactly when it is easiest to violate.

**Language of record.** Everything in this repository is English, like
every other MCUHome repository, including documents that started life
as a German conversation with the product owner.

## Consequences

- One place to read what is decided about MCUScript, from the first day
  the repository exists rather than after the first extraction round.
- The inherited decisions are not moved out of the MCUHome documents.
  They constrain *MCUHome's use* of an engine and remain correct there;
  [ADR 0002](0002-inherited-context.md) collects them here with
  citations instead of copying ownership.
- A decision that turns out to sit on the boundary is written in the
  repository that owns the *mechanism*, and cited from the other side.
