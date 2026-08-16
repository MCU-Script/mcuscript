<!--
SPDX-FileCopyrightText: 2026 The MCUScript Contributors
SPDX-License-Identifier: Apache-2.0
-->

# 0003 — The name, the organization, and what this project is positioned as

- Status: draft
- Date: 2026-08-16

## Context

The name "MCUScript" was a working title derived from MCUHome. Two
things put it in question at once, and they pull in opposite
directions.

**Scope.** Once units became a language feature — `24.5°C`, `5min`,
`75%` — the language started to look like a home-automation DSL rather
than a general one, and a general name over a domain-specific language
is a promise the project cannot keep. The product owner raised exactly
this (2026-08-16): *"MCUScript suggests a general scripting language for MCUs, but if we
define things like °C as units — as datatypes, in effect — the field of
application is really aimed more at home automation and the like."*

**Ownership.** A repository named MCUScript inside the `mcu-home`
organization reads as a component of MCUHome. That contradicts the
2026-08-07 charter, which says the engine is *"a fully standalone
project"* with MCUHome pinning releases of it the way it pins Zephyr —
and it discourages anyone else from embedding it. But renaming to
something domain-flavoured (`heim`, `hearth`, …) would have made the
scope problem worse, not better.

Alternatives that were considered and dropped: **Heim** (German/Old
Norse for home; the strongest of the domain-flavoured names, with
`heimc`/`libheim-vm` tooling and a `heim-lang` repository), **Hearth**,
**Habit**, **Dwell**, and `HeimScript` as a searchability compromise.

## Decision

### 1. The scope problem is solved by profiles, not by the name

The language knows only the *mechanism*: a literal may carry a unit
suffix, a suffix belongs to a dimension, a dimension has a base unit,
and the compiler normalizes to it. Which dimensions exist and what they
are called is a **profile**, supplied by the embedder. `°C`, `%`, `lux`
are MCUHome's *home profile*, not MCUScript vocabulary.

With that split, a general name is accurate, and the same mechanism
serves industry, agriculture or sensing profiles later. The profile
layer is part of the boundary rule of [ADR 0001](0001-record-mcuscript-decisions-here.md).

### 2. The name stays MCUScript

Product owner, 2026-08-16: *"even if we focus on our own concrete project
at first, that leaves room for extensibility and general, broad use
later."* The initial focus on MCUHome
is a starting point, not a scope.

### 3. Its own GitHub organization: `mcuscript-lang`

Product owner, 2026-08-16, verbatim: **"mcuscript-lang/mcuscript auf
github, so soll es sein!"**

Positioning and ownership are separate problems, and the ownership one
is solved organizationally rather than by a different name. MCUScript
lives in the `mcuscript-lang` organization; **MCUHome is its first and
reference embedder, not its owner.** The shared "MCU" prefix then reads
as "same ecosystem" — the ESPHome/ESP-IDF relationship — rather than as
dependency, and it works as cross-discovery in both directions.

Concretely, and this is what distinguishes it from a MCUHome
subdirectory:

- copyright is held by **The MCUScript Contributors**, never by The
  MCUHome Contributors;
- this repository has its own ADR sequence, its own release cadence and
  its own version number;
- MCUHome pins a released MCUScript version the way it pins Zephyr and
  the Matter SDK, and follows deliberately once a release is proven;
- nothing here may depend on MCUHome. The dependency arrow points one
  way, always.

The product owner's stated reason for the organization is that the
compiler, the transpiler and later the profiles can be run as their own
projects inside it. **How the code is actually cut into repositories is
a separate, open question** — see below.

### 4. Apache-2.0

Product owner, 2026-08-16 — closing the question component-model.md §10
deliberately left open *"at project creation"*, which is now. Weighed
against MIT: MIT is the norm among the MCU scripting languages (Berry,
Lua, Wren, MicroPython are all MIT) and is GPLv2-compatible, which
Apache-2.0 is not. Apache-2.0 won on consistency with the rest of the
product owner's work (mcuhome ADR 0003) and on its explicit patent
grant; the GPLv2 incompatibility is the accepted price.

### 5. The README carries the positioning, not the name

Perceived independence comes from the first paragraph a visitor reads,
not from the repository path. The README states plainly that MCUScript
is a standalone language that MCUHome embeds — and does not open with
MCUHome.

## Consequences

- The repository is `mcuscript-lang/mcuscript`. Every link, template
  and license header in it names that org, and this had to be corrected
  once already: the scaffold was created under `mcu-home/mcuscript`
  before this conversation was available.
- The units question stops being a naming question. It becomes a
  question about profiles — where they live, how they are versioned,
  and who may define one — and profiles now need a home of their own.
- MCUHome gains an obligation it does not have yet: it must publish and
  version a home profile as an artifact, because a profile is part of
  the bytecode ABI (see [ADR 0002](0002-inherited-context.md) §4).
- **Open — the repository topology inside the organization.** The
  product owner wants compiler, transpiler and profiles as separate
  projects. The counter-argument on the table is that compiler,
  transpiler and VM share an AST, a type system, the dimension
  mechanism and the bytecode definition, so splitting them early buys
  version skew and three-PR semantic changes, and specifically breaks
  differential testing, which needs both backends tested against the
  same spec in the same commit. The shape suggested against that: a
  monorepo `mcuscript-lang/mcuscript`, an early `mcuscript-lang/spec`
  because the spec is the contract for third-party implementations, and
  `mcuscript-lang/profile-home` as the first profile and the template
  for others, with the VM as a Zephyr module the first sensible split
  once it is stable. The product owner has not answered this, so
  nothing here is decided beyond the one repository that exists.
- **Open — verification of the name.** Collision checks on GitHub,
  PyPI/crates.io and as a domain, and a searchability check, were
  recommended in the same conversation and have not been carried out.
  The name is decided; whether it is *available* everywhere the project
  will want it is unverified.
- **Open — the docs domain.** MCUHome publishes under `mcuhome.org`;
  a project in its own organization needs its own, and none is
  registered.
