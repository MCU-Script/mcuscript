<!--
SPDX-FileCopyrightText: 2026 The MCUScript Contributors
SPDX-License-Identifier: Apache-2.0
-->

# MCUScript

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Status: pre-1.0](https://img.shields.io/badge/status-pre--1.0-orange.svg)](#status)

**A small scripting language for microcontrollers. One source, two
backends: a compact bytecode for a tiny on-device VM, or plain C
compiled into the firmware — every program expressible both ways, with
the same behaviour either way.**

## What it guarantees, and what it does not

MCUScript is a language with two backends. It guarantees that the same
source produces the same behaviour on both, that the reference
implementation of the compiler emits conforming containers, and that the
reference implementation of the runtime executes conforming containers
as specified. About code the reference implementation did not produce,
the reference runtime guarantees nothing; on non-conforming input its
behaviour is undefined.

How an artifact travels from the compiler to a device, and how it is
protected on the way, is the embedder's concern — **equally for both
backends**. That is a deliberate line rather than a gap: transpiled C
can be tampered with exactly as bytecode can, and a language that
policed one path and could not police the other would be read as safe
when it is not. If your delivery path is untrusted, you want an
authenticated channel, a verifier, or both; the specification defines
what a verifier decides ([§2.6](spec/02-container.md)) and
[`spec/corpus/`](spec/corpus/) is what one is checked against. Reasoning
in [ADR 0006](docs/adr/draft/0006-three-contracts-not-one-promise.md).

MCUScript is a standalone project in its own organization,
[`mcu-script`](https://github.com/mcu-script), developed
independently. [MCUHome](https://github.com/mcu-home/mcuhome), which
turns YAML device descriptions into Zephyr firmware, is its first and
reference embedder — not its owner. Being useful to projects that have
never heard of MCUHome is a design goal, not a side effect.

## Status

**The back end works; the language is specified and not built.**
Chapters 1 to 5 of [the specification](spec/) are written and
implemented — the container format, the verifier, the VM in C, and the C
backend — and a differential test runs the same container through both
backends and compares the bytes. Every instruction the specification
defines works end to end in both of them.

[Chapter 6](spec/06-syntax.md) is the surface syntax: it plans the whole
language, marks every construct **built**, **planned** or **excluded**,
and names the four instructions the built half still needs. Its lexer
and parser exist — `mcuscript parse <file>` reads a script and prints
its syntax tree — and nothing yet turns that tree into a container, so
**there is no compiler.** Programs are written in an assembler, on
purpose: it let the format, the verifier, the VM and the C backend be
built against each other before anybody argued about how an `if` should
look.

Do not depend on this repository. The specification is at
`0.1.0-draft` and says so; ADR 0002 marks each remaining item as
**decided**, **recorded direction** or **on the table**, and a good deal
is still the third of those.

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
2. **Always transpilable to C** as well, and built into the firmware
   that way instead. The two are *alternatives*, not a feature and an
   extra: during development you push bytecode and iterate in seconds,
   and on a sleepy battery device you bake the same script into the
   image and link no VM at all. Which one a deployment uses is a
   choice; being able to do both is not.
3. **Modular**, because most scripts are formulas. A device that only
   evaluates expressions should link only an expression evaluator —
   and dropping the optional instruction groups really does drop their
   code, which is now measured rather than claimed.

Requirement 2 is what shapes the rest. Two backends generate from one
typed intermediate representation, and a construct only one of them can
express is a bug rather than a feature — which is why the language is
statically typed, why the compiler and not the runtime computes stack
depth, and why recursion is capped rather than open-ended.

What that buys, and what nothing else currently offers in one package:
**one source, two backends, identical behaviour**, held to it by
differential tests.

## What it costs

Measured on linked images, not estimated: the engine is **3.1 KB of
flash** on a Cortex-M33 for an expression-only build and **5.6 KB** with
every instruction group, no static RAM, and about 1 KB the embedder
declares for a loaded program and its slots. On a Cortex-M0+, which has
neither a divide instruction nor an FPU, the full build is 8.8 KB — the
compiler's support library is part of the bill, which is also why 64-bit
division is a group you can leave out.

Half of that is the interpreter and the other half is what the
instruction groups add, so leaving groups out is most of what there is
to leave out. The loader is 1.7 KB and the same size in every
configuration, because it does not know what an instruction is.

Which is also the honest answer to "will it fit": if it does not, the
second backend costs nothing at all, because generated C links neither
the loader nor the VM. The whole table, the method, and the run on a
real nRF5340 are in
[ADR 0004 §4.9](docs/adr/draft/0004-two-backends-one-container.md), and
`python tools/measure_footprint.py` reproduces it wherever there is an
ARM cross compiler.

## What it looks like

Decided and written down in [chapter 6](spec/06-syntax.md), and not yet
compiled by anything:

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

Two kinds of absence, not one: a sensor that has no reading yet is
`unavailable` and usually wants a fallback, while a sensor reporting a
fault is `invalid` and must not be quietly papered over. Collapsing
them into a single `null` is what makes template languages fragile.

Which units exist is deliberately **not** the language's business, and
there is no exception: it fixes no dimension and no base unit, not even
for time, and it has no clock of its own. The language knows the
mechanism — suffix → dimension → base unit, plus the notations for
durations (`3h 45min`) and points in time (`@"2026-08-18 13:25"`) — and
a **profile** supplies the table. `°C`, `%` and `lux` come from a home
profile that an embedder ships, which is what keeps a general language
from quietly becoming a home-automation one.

## The specification

[spec/](spec/) is the contract: the value model, the container format,
the instruction set, linking and execution. A third party should be
able to write a conforming VM from it alone — and the implementation in
this repository is how that claim gets checked, because writing it has
corrected the document sixteen times and the list is kept in
[spec/README.md](spec/README.md).

[spec/corpus/](spec/corpus/) is how *you* would check: containers with
the verdict each must get, as bytes, so a loader written from the
document can be pointed at them without running any of this code.

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
- [0004](docs/adr/draft/0004-two-backends-one-container.md) — how the
  two backends are kept identical, decided while writing them
- [0005](docs/adr/draft/0005-the-conformance-corpus.md) — the
  conformance corpus: what binds the two loaders to one verdict
- [0006](docs/adr/draft/0006-three-contracts-not-one-promise.md) — what
  this project guarantees, and why the runtime stopped verifying
- [0007](docs/adr/draft/0007-loops-are-bounded-not-metered.md) — loops,
  bounded by a guard rather than by an instruction budget
- [0008](docs/adr/draft/0008-the-language-owns-no-dimensions.md) — why
  the language fixes no unit, no base unit and no clock
- [0009](docs/adr/draft/0009-the-surface-syntax.md) — the surface
  syntax, planned whole before any of it is compiled

## Contributing

The most useful contributions right now are not code — see
[CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache-2.0 — see [LICENSE](LICENSE). The repository is
[REUSE](https://reuse.software/)-compliant.
