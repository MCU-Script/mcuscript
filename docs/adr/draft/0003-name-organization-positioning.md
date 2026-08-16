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

### 3. Its own GitHub organization: `MCU-Script`

Product owner, 2026-08-16, verbatim: **"mcuscript-lang/mcuscript auf
github, so soll es sein!"** — and then, creating it the same day, named
it **`MCU-Script`** instead, deliberately mirroring `MCU-Home`. The
repository is `mcu-script/mcuscript`.

The change is worth a sentence, because it inverts one of the arguments
that produced the original name. `-lang` was partly a searchability
device: one-word language names usually need the suffix to be findable
at all. That reason lapsed — the collision check below found the field
clear, so there is nothing to disambiguate from — and the parallel to
`MCU-Home` buys something the suffix did not. Two organizations named
the same way read as one ecosystem containing two projects, which is
exactly the relationship, and it makes the cross-discovery argument
below literal rather than hopeful.

Positioning and ownership are separate problems, and the ownership one
is solved organizationally rather than by a different name. MCUScript
lives in the `mcu-script` organization; **MCUHome is its first and
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

### 4. One repository to start with: a monorepo

Product owner, 2026-08-16. The organization exists so that the
compiler, the transpiler and later the profiles *can* become their own
projects — but they do not start that way.

Compiler, transpiler and VM share an AST, a type system, the dimension
mechanism and the bytecode definition. Split across repositories from
day one, that buys version skew ("compiler 0.4 needs spec 0.3, the VM
only speaks 0.2") and turns every semantic change into three pull
requests. It also breaks the one practice the project cannot do
without: differential testing needs **both backends tested against the
same spec in the same commit**. Splitting later is always possible;
re-merging is not.

So `mcu-script/mcuscript` holds the compiler, both backends, the VM,
the test harness — **and the specification**, as a top-level `spec/`
directory with its own version number.

Keeping the specification in is that same argument applied harder, not
an exception to it. The spec *is* the bytecode definition, so it is the
most tightly coupled thing in the repository rather than the least;
splitting it out would mean two pull requests for every semantic change
during exactly the period when the semantics change daily, and it would
reintroduce the "compiler 0.4 needs spec 0.3" skew the monorepo exists
to avoid. The pattern elsewhere agrees: languages with one
implementation keep the specification beside it (Go's is a file in the
Go repository; Zig and Lua likewise), and languages with several split
it out (WebAssembly, C#) — and this project has none yet. The
citability a separate repository would buy comes from *publishing* the
specification, which a monorepo does just as well. `spec/` is a
top-level directory precisely so that the split is one clean cut on the
day a second implementation justifies it.

**`profile-home` does get its own repository** (product owner,
2026-08-16), and it belongs to this organization rather than to
MCUHome. Its coupling runs the other way from the spec's: a profile
depends on the profile *format*, a narrow and deliberately stable
interface, not on any compiler internal. Two further reasons make the
separation structural rather than tidy. A community profile cannot live
inside the language repository by definition, so the mechanism has to
work from outside — and `profile-home` is where that gets proved. And
§1 of this ADR says `°C` and `lux` must not be MCUScript vocabulary; a
separate repository makes that boundary physical instead of merely
documented.

It is a *general* home-automation profile with MCUHome as its first
consumer, not MCUHome's private file — the product owner's reasoning
being that profiles should be usable by others, even though this one
will grow from MCUHome's needs at first. Under `mcu-home` it would have
been one project's internal detail, and the community-profile mechanism
would have had no worked example.

It is created when the specification defines the profile format, not
before. An empty repository says nothing.

The VM as a Zephyr module is the first sensible split of the monorepo
itself, once it is stable: an embedder should be able to pull it
through `west.yml` without dragging the compiler along.

### 5. Apache-2.0

Product owner, 2026-08-16 — closing the question component-model.md §10
deliberately left open *"at project creation"*, which is now. Weighed
against MIT: MIT is the norm among the MCU scripting languages (Berry,
Lua, Wren, MicroPython are all MIT) and is GPLv2-compatible, which
Apache-2.0 is not. Apache-2.0 won on consistency with the rest of the
product owner's work (mcuhome ADR 0003) and on its explicit patent
grant; the GPLv2 incompatibility is the accepted price.

### 6. The README carries the positioning, not the name

Perceived independence comes from the first paragraph a visitor reads,
not from the repository path. The README states plainly that MCUScript
is a standalone language that MCUHome embeds — and does not open with
MCUHome.

## Consequences

- The repository is `mcu-script/mcuscript`. Every link, template
  and license header in it names that org, and this had to be corrected
  once already: the scaffold was created under `mcu-home/mcuscript`
  before this conversation was available.
- The units question stops being a naming question. It becomes a
  question about profiles — where they live, how they are versioned,
  and who may define one — and profiles now need a home of their own.
- MCUHome gains an obligation it does not have yet: it must publish and
  version a home profile as an artifact, because a profile is part of
  the bytecode ABI (see [ADR 0002](0002-inherited-context.md) §4).
- The organization holds one repository today and will hold two: the
  monorepo, and `profile-home` once the profile format exists.
- The name survives the collision check the conversation recommended
  and never performed (carried out 2026-08-16): **the namespace is
  clear.** Verified by direct lookup — no `mcuscript` or
  `mcu-script` organization, user or repository on GitHub, and both
  names 404 on PyPI and npm. Verified by search only, so weaker: no
  crate of either name on crates.io; no MCU vendor ships anything
  branded "MCU Script" (the
  scripting features in MCUXpresso, STM32CubeProgrammer, MPLAB and the
  Renesas and Silicon Labs tools are automation surfaces, not named
  languages); and `.mcs` is associated with old Mathcad images and
  Intel MCS-86 hex objects, not with any live language. The nearest
  neighbour is `mcscript`, a Minecraft datapack compiler — one letter
  away, but a different audience, and dormant.
- **`mcuscript.org` is registered** (product owner, 2026-08-16). The
  project has its own domain, separate from `mcuhome.org`, which is the
  last piece of the standalone posture: own organization, own name, own
  domain, own license header.
