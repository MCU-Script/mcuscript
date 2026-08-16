<!--
SPDX-FileCopyrightText: 2026 The MCUHome Contributors
SPDX-License-Identifier: Apache-2.0
-->

# MCUScript

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Status: design phase](https://img.shields.io/badge/status-design_phase-lightgrey.svg)](#status)

**A small scripting language for microcontrollers: expressions and
automation logic, compiled on a host, executed by a tiny VM on the
device.**

## Status

**Nothing is implemented.** This repository exists so the design has a
home before the first line of code — there is no language, no compiler,
no VM, and no API yet. What exists is the accumulated context: the
requirements, constraints and prior decisions that a scripting engine
for [MCUHome](https://github.com/mcu-home/mcuhome) has to satisfy,
collected in [docs/adr/](docs/adr/).

Do not depend on this repository. Nothing here is stable, and the
central question — whether MCUScript is built at all, or whether
MCUHome adopts an existing engine such as
[Berry](https://github.com/berry-lang/berry) — is still open by design
(see [ADR draft 0002](docs/adr/draft/0002-inherited-context.md)).

## The idea

MCUHome describes smart home devices in YAML and compiles them into
Zephyr firmware. Hardware wiring, drivers and the Matter data model are
compile-time — that is deliberate and stays. What YAML cannot express
well is *logic*: "report the average of these two sensors", "turn the
buzzer on when CO₂ stays above 2000 ppm for two minutes", "clamp this
value unless the other sensor is stale".

Two tiers are wanted, and the second is what makes this a language
rather than a config feature:

1. **Expressions** — a single side-effect-free value. Variables, the
   ternary conditional, null coalescing, arithmetic, and read-only
   access to other channels. No statements, no loops, no user-defined
   functions, no state — so evaluation needs no heap and no garbage
   collector, and references between channels form a static graph the
   builder validates at compile time.
2. **Scripts** — stateful logic: hooks (`on_boot`), timers, actions,
   user automations. This is where a real VM is needed.

The intended shape, if MCUScript is built: **one** language whose
expression subset *is* tier 1; compilation to a compact bytecode on the
host (the builder is always in the loop — a device-side parser buys
nothing); a VM assembled from feature modules, so a device that only
evaluates expressions links only an expression VM; and the language
kept statically analyzable enough that the same source can be
transpiled to C instead of shipping a VM at all.

None of that is decided. It is the hypothesis this project exists to
test.

## Relationship to MCUHome

MCUScript is a **standalone project**, not an MCUHome subcomponent
(product-owner decision, 2026-08-07): its own repository, a cleanly
versioned C API toward its embedders, and MCUHome pinning a concrete
MCUScript release exactly as it pins Zephyr and the Matter SDK. The
engine evolves independently; MCUHome follows deliberately, once a
release is proven. Being useful to projects that have never heard of
MCUHome is a design goal, not a side effect.

MCUHome is where the *first* requirements come from, and its design
documents are the source of everything recorded here so far — see
[ADR draft 0002](docs/adr/draft/0002-inherited-context.md), which cites
each of them.

## Design decisions

Decisions live in [docs/adr/](docs/adr/) as architecture decision
records, draft-first: a decision is a living document while the thing
it decides about is being built, and becomes an immutable final ADR
written from the real result. Read those before assuming anything about
this project's direction.

## License

Apache-2.0 — see [LICENSE](LICENSE). Same license as the rest of the
MCUHome project (mcuhome ADR 0003); the repository is
[REUSE](https://reuse.software/)-compliant.
