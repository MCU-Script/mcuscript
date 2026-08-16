<!--
SPDX-FileCopyrightText: 2026 The MCUScript Contributors
SPDX-License-Identifier: Apache-2.0
-->

# 0001 — Record MCUScript decisions in this repository

- Status: draft
- Date: 2026-08-16

## Context

MCUScript starts as an empty repository with a long prehistory. That a
scripting engine grown from MCUHome's expression tier would be *a
project of its own* was decided on 2026-08-07, nine days before this
repository existed
([component-model.md §10](https://github.com/mcu-home/mcuhome-sdk/blob/main/docs/design/component-model.md)),
and the design conversation of 2026-08-16 turned that into a name, an
organization and three technical requirements. Everything decided so
far is written in MCUHome documents and in a chat log, because there was
nowhere else to write it.

That is a problem the moment the repository exists: a reader here would
find nothing, a reader in the MCUHome repositories would find scripting
decisions scattered across a design document, four ADRs and a validation
gate, and neither would know which of them still bind. MCUHome's own
repositories solved the same problem twice already — the CLI's decisions
were extracted out of the firmware ADRs into
[cli ADR 0001](https://github.com/mcu-home/cli/blob/main/docs/adr/draft/0001-record-cli-decisions-here.md),
and the project-wide/SDK split was drawn by
[mcuhome ADR 0024](https://github.com/mcu-home/mcuhome/blob/main/docs/adr/draft/0024-sdk-and-tools-repositories.md).

## Decision

MCUScript design decisions are recorded as ADRs in this repository,
following the draft-first lifecycle of
[mcuhome ADR 0021](https://github.com/mcu-home/mcuhome/blob/main/docs/adr/0021-draft-first-adr-lifecycle.md):
drafts in `docs/adr/draft/` are living documents; a final ADR is
written from the real result once the component is done, and is then
immutable. The lifecycle is **adopted, not inherited** — MCUScript
belongs to its own organization ([ADR 0003](0003-name-organization-positioning.md))
and follows this process because it is a good one, not because MCUHome
owns the process here.

**Own number sequence.** MCUHome and mcuhome-sdk share one sequence
because they are two halves of one product; the CLI and the dashboard
have their own. MCUScript starts at 0001 and counts on its own. An
MCUScript ADR is never cited as "ADR NNNN" outside this repository
without the `mcuscript` prefix, and this repository prefixes foreign
numbers the same way (`mcuhome ADR 0014`, `mcuhome-sdk ADR 0015`,
`cli ADR 0003`).

### The boundary: three layers, not two

The obvious boundary — "the language here, its users elsewhere" — is not
enough, because the design has a third layer between them. A **profile**
fixes the domain vocabulary: which dimensions exist (`duration`,
`temperature`, `percent`, …), which unit suffixes are spelled how, and
which base unit each dimension normalizes to. The *mechanism* is the
language's; the *table* is the domain's.

| Layer | Decided where | Examples |
|---|---|---|
| **The language** | here | grammar, type system, the unit *mechanism*, the bytecode container and its verifier, the VM and its feature modules, the C API toward embedders, diagnostics, this project's versioning |
| **A profile** | in the profile's own repository | which dimensions exist, unit spellings, base units, the value ranges an embedder's actuators expect |
| **An embedding** | in the embedder's repository | which of the embedder's configuration lowers to script, how a script reaches a device, which flash region holds it, when the device rebuilds instead of accepting a push, what its entity registry contains |

The test for this repository: *would this decision still have to be made
if the only embedder were somebody else's project?* If yes, it belongs
here. MCUHome's home profile and MCUHome's script transport both fail
that test and belong to MCUHome — this repository only cites them.

The boundary is stated now, while MCUHome is the only embedder, because
that is exactly when it is easiest to violate.

**Language of record.** Everything in this repository is English, like
every MCUHome repository, including documents that started life as a
German conversation with the product owner.

## Consequences

- One place to read what is decided about MCUScript, from the first day
  the repository exists rather than after the first extraction round.
- The inherited decisions are not moved out of the MCUHome documents.
  They constrain *MCUHome's use* of an engine and remain correct there;
  [ADR 0002](0002-inherited-context.md) collects them here with
  citations instead of copying ownership.
- The profile layer gives the "is MCUScript a home-automation language
  or a general one?" question a structural answer rather than a
  rhetorical one, and it needs its own repository before the first
  profile is written (ADR 0003 leaves the topology open).
- A decision that turns out to sit on a boundary is written in the
  repository that owns the *mechanism*, and cited from the other side.
