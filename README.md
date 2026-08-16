<!--
SPDX-FileCopyrightText: 2026 The MCUScript Contributors
SPDX-License-Identifier: Apache-2.0
-->

# MCUScript

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Status: design phase](https://img.shields.io/badge/status-design_phase-lightgrey.svg)](#status)

**A small scripting language for microcontrollers. One source, two
backends: a compact bytecode for a tiny on-device VM, or plain C
compiled into the firmware — with the same behaviour either way.**

MCUScript is a standalone project. [MCUHome](https://github.com/mcu-home/mcuhome),
which turns YAML device descriptions into Zephyr firmware, is its first
and reference embedder — not its owner. Being useful to projects that
have never heard of MCUHome is a design goal, not a side effect.

## Status

**Nothing is implemented.** There is no language, no compiler, no VM
and no C API. What exists is the design record: the requirements, the
constraints and the decisions taken so far, collected in
[docs/adr/](docs/adr/) with every claim traced to its source.

Do not depend on this repository. Read
[ADR 0002](docs/adr/draft/0002-inherited-context.md) before assuming
anything — it marks each item as **decided**, **recorded direction** or
**on the table**, because most of what is written down is still the
third of those.

## The idea

Users of a smart-home firmware framework need logic: "report the
average of these two sensors", "turn the buzzer on when CO₂ stays above
2000 ppm for two minutes", "clamp this value unless the other sensor is
stale". YAML expresses it badly and C is not something an end user
should have to write — ESPHome's answer is a C++ lambda, and that is
exactly the answer MCUScript exists to avoid.

Three requirements shape everything else:

1. **Always compiled.** A script becomes hardware-independent bytecode
   on the host, never machine code, so the device carries a VM and not
   a compiler.
2. **Optionally transpiled to C** and built into the firmware, for
   sleepy battery devices where a VM is the wrong trade — *optional*,
   because rebuilding the whole firmware for a one-line change is not
   an iteration loop.
3. **Modular**, because most scripts are formulas. A device that only
   evaluates expressions should link only an expression evaluator.

Requirement 2 is the interesting one: it means two backends generating
from one typed intermediate representation, and it is why the language
is statically typed — a dynamically typed language transpiles to C full
of tagged values and runtime dispatch, which throws away the reason for
having a C path at all.

What that buys, and what nothing else currently offers in one package:
**one source, two backends, identical behaviour**, held to it by
differential tests.

## Sketches, not decisions

To make the above concrete — none of this is settled, and all of it is
recorded as *on the table* in
[ADR 0002 §2](docs/adr/draft/0002-inherited-context.md):

```
fan.speed = match temp { > 28°C -> 3, > 25°C -> 2, else -> 0 }
```

Braces rather than significant whitespace, so a script means the same
thing on one line as on five and cannot be broken by reformatting the
YAML around it. `if`/`else` is an expression, so there is no separate
ternary operator to learn. Units are part of the type system — `5min`
and `24.5°C` are single tokens, normalized to a base unit at compile
time, costing nothing at runtime — and comparing a temperature to a
duration is a compile error, in words rather than in jargon.

Which units exist is deliberately **not** the language's business. The
language knows the mechanism (suffix → dimension → base unit); a
**profile** supplies the table. `°C`, `%` and `lux` come from a home
profile that an embedder ships — which is what keeps a general language
from quietly becoming a home-automation one.

## Design decisions

Decisions live in [docs/adr/](docs/adr/) as architecture decision
records, draft-first: a decision is a living document while the thing
it decides is being built, and becomes an immutable final ADR written
from the real result.

- [0001](docs/adr/draft/0001-record-mcuscript-decisions-here.md) —
  where decisions are recorded, and the boundary between the language,
  a profile and an embedding
- [0002](docs/adr/draft/0002-inherited-context.md) — everything
  inherited, with sources; its §8 is the open-questions list
- [0003](docs/adr/draft/0003-name-organization-positioning.md) — the
  name, the organization, the positioning, the license

## Contributing

The most useful contributions right now are not code — see
[CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache-2.0 — see [LICENSE](LICENSE). The repository is
[REUSE](https://reuse.software/)-compliant.
