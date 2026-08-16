<!--
SPDX-FileCopyrightText: 2026 The MCUScript Contributors
SPDX-License-Identifier: Apache-2.0
-->

# 0002 — Inherited context: what is already decided, and where it is written down

- Status: draft
- Date: 2026-08-16

## Context

MCUScript is a new project for an old idea, and it inherits two bodies
of thinking that live nowhere a contributor could find them. Both come
from [MCUHome](https://github.com/mcu-home/mcuhome) — not because
MCUScript belongs to it, but because MCUHome is where the first
embedder's requirements were worked out, and it happened to be the only
place with a document to write them in.

**The requirements the first embedder wrote down**, 2026-08-03 to
2026-08-11: while MCUHome was designed and built, decisions about
scripting were taken and recorded — never in one place, because there
was no such place. They sit in one design document, five ADRs, a
validation gate, a C header, a glossary and a roadmap entry, spread
over two repositories.

**A design conversation** between the product owner and Claude,
2026-08-16, supplied as a chat export. It is where the name, the
organization and the project's three technical requirements come from,
and it goes considerably further into the language than any MCUHome
document does. It is a *conversation*, not a decision protocol: some of
it is the product owner deciding, most of it is advice he did not
answer, and telling those apart is the single most useful thing this
record does.

Anyone starting work here needs both, because several items are
load-bearing constraints on the language itself (no heap in the
expression tier, static analyzability, a bytecode a device must not be
crashable by) and several are not constraints at all but current
guesses. Rediscovering that distinction from scratch is how a project
accidentally re-decides something the product owner already settled —
or, worse, treats a suggestion as settled.

## Decision

This ADR is a **reference record**. It decides nothing: it collects
what exists, cites the source of each item, and sorts every item into
one of three buckets, which are marked throughout:

| Bucket | Meaning |
|---|---|
| **Decided** | The product owner said it. It binds until he changes it. |
| **Recorded direction** | Written into a MCUHome design document, which makes it product-owner-approved *for MCUHome*. It binds MCUHome; it constrains MCUScript only where MCUScript wants to be embeddable in MCUHome. |
| **On the table** | Proposed in the conversation and not answered. **Not a decision.** Recorded because losing it would mean re-deriving it, and because several items are strong enough that discarding them silently would be a mistake. |

Where a source is a living draft it may move, and this record is then
wrong and gets rewritten. Sources:

| Short form | Document |
|---|---|
| `component-model.md` | [mcuhome-sdk `docs/design/component-model.md`](https://github.com/mcu-home/mcuhome-sdk/blob/main/docs/design/component-model.md) — §10 is the origin of this project |
| `yaml-schema.md` | [mcuhome-sdk `docs/design/yaml-schema.md`](https://github.com/mcu-home/mcuhome-sdk/blob/main/docs/design/yaml-schema.md) |
| `builder-pipeline.md` | [mcuhome-sdk `docs/design/builder-pipeline.md`](https://github.com/mcu-home/mcuhome-sdk/blob/main/docs/design/builder-pipeline.md) |
| `channel.h` | [mcuhome-sdk `include/mcuhome/channel.h`](https://github.com/mcu-home/mcuhome-sdk/blob/main/include/mcuhome/channel.h) |
| mcuhome-sdk ADR 0009 / 0010 / 0014 | Matter-explicit YAML schema / Matter-only, CoAP deferred / generated-tables contract |
| mcuhome-sdk draft ADR 0015 | Update and partition architecture |
| mcuhome ADR 0019 | Session build protocol (cited once, for a name collision) |
| `ROADMAP.md`, `GLOSSAR.md` | MCUHome workspace documents, untracked, product-owner-facing |
| **the conversation** | Design conversation, product owner ↔ Claude, 2026-08-16, chat export. Not in any repository; quoted here because this is the only place it survives |

---

## 1. Where the requirements came from

Everything in this section is a MCUHome document. It is recorded here
because it is the origin of the requirements, **not because MCUHome has
authority over this project** — MCUScript is developed independently of
it (ADR 0003), and MCUHome's own decisions about what to embed are its
own (§3.3). Read this section as "what the first embedder needs and
why", which is exactly the kind of thing a language project wants
written down.

### 1.1 The principle: a script is never the data path

*Recorded direction, component-model.md §10, 2026-08-07.*

Firmware stays individually generated and compiled per device. Drivers,
bus wiring, devicetree and the Matter tables are compile-time — Zephyr
instantiates drivers from devicetree at build time, there is no runtime
bus/address binding, and *"MCUHome will not maintain a parallel driver
stack to get one"*.

A scripting engine is added *"strictly as the filter/hook/automation
layer: it can transform values on their way from a sensor binding to a
channel and it can react to events, but it never becomes the data path
itself and never carries the device's Matter model"*. And: **end users
never write C/C++.**

§10's own framing of its status: *"Not v0.x scope — recorded here so
nothing built before the automation phase closes a door on it. The
formal decision is an ADR at the start of that phase, backed by a
measured prototype."*

### 1.2 Three filter tiers, cheapest one wins

*Recorded direction, component-model.md §10.* The builder picks the
cheapest tier that covers the configuration:

1. **Predefined filters** (`offset`, `range`, later moving average,
   deadband, …) — declarative registry entries. *Everything stateful
   lives here*, with its state owned by the C framework.
2. **Expressions** — deliberately more than arithmetic (product-owner
   scope call: *"end users should normally not need tier 3"*). In
   scope: variables, the ternary conditional, null coalescing (which
   *"pairs naturally with the nullable 'sensor not ready yet' semantics
   of the attribute stores"*), and read-only value access to other
   channels through a fixed method surface. The worked example:

   ```
   humidity_kitchen.value() > 30 ? temp_kitchen.value()
                                 : temp_kitchen.value() * 0.7 + temp_living.value() * 0.3
   ```

   Symfony's ExpressionLanguage is named as the *scope marker*, not as
   a syntax to copy. **The hard line:** an expression is a single
   side-effect-free value — *no statements, no loops, no user-defined
   functions, no state* — so evaluation needs **no heap and no GC**,
   and cross-channel references form a **static dependency graph the
   builder validates** (recompute order, cycles rejected at validate
   time). This tier is explicitly small enough that MCUHome owns its
   implementation.
3. **Scripting engine** — stateful logic, `on_boot`-style hooks,
   timers, actions (e.g. `trigger_measurement()`), user automations.
   For genuinely complex processing (the example: an AMG8833 8×8
   thermal grid) the engine's footprint is *"a fair price"* — though
   known-complex sensors can also land as C components, shrinking how
   often tier 3 is needed at all.

### 1.3 The two candidate tracks

*Recorded direction, component-model.md §10.* To be decided by *"the
automation-phase ADR"*, backed by a measured prototype.

**Track A — adopt an existing engine:**

| Candidate | Verdict as recorded |
|---|---|
| **Berry** | First choice. MIT, MCU-native, Tasmota precedent |
| **Lua** | Second choice |
| Toit | Behind: LGPL VM, ESP-IDF-bound |
| Wren | Behind: dormant since 0.4.0, double-precision-only numbers on single-precision-FPU targets |

**Track B — grow our own** from the tier-2 core. Five elements, all
named: one language whose grammar's expression subset *is* tier 2;
host-side compilation to a compact bytecode — *"the builder is always
in the loop, unlike Tasmota's on-device console — a device-side parser
buys us nothing"*; the VM assembled from feature modules so an
expression-only device links an expression-only VM; the language kept
statically analyzable enough that LIVE mode can transpile to C; and
each element individually proven prior art (Lua `luac`, MicroPython
`.mpy`, Berry solidification; trimmed-library builds; DSL-to-C
transpilers).

The risk is stated precisely, and it is not technical: *"the risk is
not buildability but a decade of ownership: first-class diagnostics,
documentation, a bytecode verifier (pushed bytecode must never crash a
node), and format stability across firmware versions."* **Berry remains
the safety net if this track stalls.**

### 1.4 The standalone-project charter

*Recorded direction, component-model.md §10, product-owner decision of
2026-08-07 — quoted in full because it is this repository's charter:*

> **If this track is chosen, the engine is a fully standalone
> project**: own repository, a cleanly versioned C API toward MCUHome,
> and MCUHome pinning a concrete engine release exactly as it pins
> Zephyr and the Matter SDK — the engine evolves independently, MCUHome
> follows deliberately once a release is proven. Generally useful to
> other projects by design; license chosen at project creation
> (Apache-2.0 vs MIT — adoption argument, deliberately left open). The
> tier-2 expression engine is built with this API discipline from day
> one, so it can be promoted into the standalone project rather than
> rewritten.

Three of its clauses have since been resolved, and the resolutions live
in [ADR 0003](0003-name-organization-positioning.md): the repository
exists, it is in its **own organization** rather than MCUHome's, and
the license is **Apache-2.0**. The last sentence — build tier 2 inside
MCUHome first and promote it later — has been overtaken in sequencing:
the standalone project now starts first (§2.2).

### 1.5 The DEV/LIVE split

*Recorded direction, component-model.md §10.* Not MCUScript's
mechanism, but the reason several language constraints exist:

- A freshly set-up device runs in **DEV** mode: YAML filters are
  lowered to *script* and pushed **without recompiling** — *"config
  iteration lands in seconds"*.
- Once tuned, the user switches to **LIVE**: one full rebuild bakes the
  YAML-defined filters back into **C**, and the engine is linked only
  for what genuinely needs it — *"possibly not at all, which is the
  steady state for battery devices"*.
- Both lowerings of a filter primitive come from **one registry
  definition** and are held equivalent by **golden tests** (same input
  series, identical output).
- The builder classifies every config diff as firmware-affecting
  (wiring, drivers, endpoint structure → rebuild + OTA) or script-only
  (filters, automations → push), and the device's mode is part of the
  canonical model *"so a filter is never applied twice (baked **and**
  scripted)"*.

### 1.6 Fixed constraints for the automation phase

*Recorded direction, component-model.md §10.* All of it binds whatever
engine is chosen:

- the tables contract (mcuhome-sdk ADR 0014) stays the single
  interface — *"a boot script would be a second producer of the same
  tables, never a bypass"*;
- unit conversion into Matter raw units stays in the C binding —
  **scripts work in user units**;
- script transport needs an authenticated channel (the CoAP management
  path) **plus staged apply with fallback to the last good script** —
  *"a broken script degrades to the identity path and logs, it never
  takes the node down"*;
- a **script/firmware binding-API version handshake**, mirroring
  `tables_version`;
- real OTA remains required regardless, for base-image security
  updates.

### 1.7 What the YAML schema already reserves

*Recorded direction, yaml-schema.md, product-owner-approved
2026-08-03.* It describes a *"full declarative automation engine"* as a
product anchor.

- **§1.3 No embedded code.** *"Configs never contain C/C++ snippets
  (ESPHome lambdas are explicitly rejected). Automations are fully
  declarative YAML (§8); if a device needs real code, that is a custom
  component."* mcuhome-sdk ADR 0009 gives the reason: ESPHome's lambdas
  are C++ against ESPHome's runtime API and are *"unrunnable on
  Zephyr"*; they are named as *"what cannot be translated"* when
  importing an ESPHome configuration.
- **§8 `automations:`** specifies the declarative model fully: triggers
  (attribute thresholds with `above`/`below`/`equals` and an optional
  `for:`, `changed:`, `interval:`, `boot:`, a received Matter/CoAP
  command, later button events), conditions (all must hold; `any:`/
  `not:` combinators), actions run sequentially (`command:`, `set:`,
  `delay:`, `log:`, later `scene:`), references as
  `alias.cluster.attribute` (node view) or `peripheral.channel`
  (hardware view), *"both resolve to the same value plumbing"*.
- **§8, deliberately absent:** *"free-form expressions/templates. v1
  offers comparisons, thresholds and durations only. An expression
  language is the single biggest complexity driver in this space —
  reserved as an explicit extension point (`expression:` key) so adding
  it later is non-breaking."*
- Automations run on-device and keep working without network — with
  `network:` absent entirely a config *"degrades to a standalone
  automation controller"*.
- §11 lists *"Expression language in automations — Reserved extension
  point"* among the deferred topics.

The single worked example is
[`docs/design/examples/03-co2-alarm-automation.yaml`](https://github.com/mcu-home/mcuhome-sdk/blob/main/docs/design/examples/03-co2-alarm-automation.yaml)
— a CO₂ guard with `above: 1200` `for: 2min` → LED, `above: 2000` →
LED + buzzer + `delay: 5s` + buzzer off, `below: 900` `for: 5min` →
clear. It is the most concrete statement of what the scripting layer
must be able to express, and it is *declarative YAML*, not script.

### 1.8 What the builder pipeline already says

*Recorded direction, builder-pipeline.md §3.* Stage 4 emits
`mcuhome_config.c/.h`, described as *"endpoint/cluster/automation
tables"*, and:

> Automations compile to a compact static table (triggers, conditions,
> actions as data) interpreted by a small runtime engine — **no
> generated C control flow**.

This predates §10 and describes the *declarative* engine, not a
scripting VM. It matters as a data point about intended shape: the
project's instinct has consistently been *data plus a small
interpreter*, never emitted control flow — with LIVE-mode
transpile-to-C (§1.5) as the deliberate exception. See §3.2.

### 1.9 What the firmware contracts already fix

*Recorded direction.*

**mcuhome-sdk ADR 0014 (generated tables contract, final).** *"Future
automation tables (out of scope for contract v1, see Consequences)
follow the same pattern: one generated file per device, one symbol set
per contract domain."* And in Consequences: *"Automation tables and
actuator write-path semantics are explicitly out of scope for contract
v1 […] and get their own tables/version bump later."* So a scripting
engine's generated data gets **its own symbol set and its own contract
version**, and does not extend the Matter tables.

**`channel.h` (contract v1, hardware-verified).** The channel layer's
scope is *"deliberately narrow"* and names its exclusions:

> Periodic sampling, report-on-delta. **No triggers, no filters, no
> averaging.**

and, about the generated binding structs:

> THIS HEADER IS DUMB DATA ON PURPOSE. […] Every field must therefore
> be something a YAML-driven generator can compute without embedding
> logic: constants, IDs, and integer scale factors — **never
> expressions, never code.** Keep it that way.

Also fixed there: conversion into Matter raw units happens in the
sensor binding, as one integer step —
`raw = round(micro * scale_num / (scale_den * 1e6)) + offset` — which
is the mechanism behind §1.6's *"scripts work in user units"*, and the
place §4 says has to change. Runtime state lives in the poller's
Kconfig-sized static pool, not in the generated arrays, so those stay
`const` and stay in flash — the same discipline a VM's generated data
will be held to.

### 1.10 What flash and transport already reserve

*Recorded direction, mcuhome-sdk draft ADR 0015.* A **script/data area
is already reserved** in every layout table, citing component-model.md
§10:

- reserved regions are *"named in the layout tables, not squeezed in
  later"*; the script area and (on 1 MiB nRF5340 variants) a
  network-core staging region are *"carved from the top of the
  application slot, adjacent to `storage`, so that instantiating one
  moves exactly one boundary and nothing else"*;
- **in v0.x their size is zero**;
- *"The script area is explicitly **not** MCUboot-image-framed:
  `IMAGE_F_NON_BOOTABLE` is a trap (swap loaders scramble the trailer),
  and an extra updateable image conflicts with the seconds-level push,
  staged apply and last-good fallback that component-model.md §10 asks
  for."*
- *"Reservation only; the format is decided in the scripting phase."*
  — that format is MCUScript's bytecode container, and §2.7 is the
  first sketch of it.

On transport: a transfer protocol of MCUHome's own (CoAP over Thread,
which OpenThread already provides) is deferred to the maintenance
channel mcuhome-sdk ADR 0010 reserved, *"where it belongs together with
script push and diagnostics — one channel, designed once"*. Recorded
for that design: MCUboot's signature is the only payload trust anchor
in the existing path — and a script push does not go through MCUboot,
which is why §4 raises who signs pushed bytecode.

The Matter settings partition (fabric credentials, Thread dataset) is
preserved across updates in every layout — *"which is what makes an
update not a re-commissioning"*. A script push must not disturb it.

### 1.11 Where this sits in the plan

`ROADMAP.md`, "Parallele / spätere Stränge": the
*Automations-/Scripting-Phase* comes **after phase 4/5** (dashboard MVP
and component breadth) and consists of the three filter tiers, the
DEV/LIVE split and the engine decision, *"an ADR with a measured prototype at the
start of the phase"*. MCUHome is currently in its CLI phase. **The
scripting phase has not started**, and the ADR with a measured
prototype has not been written.

---

## 2. The design conversation of 2026-08-16

### 2.1 The three requirements — this project's technical charter

**Decided.** The product owner's own numbering, paraphrased closely:

1. **The user script is always compiled** — not to hardware machine
   code but to hardware-independent binary code *"ähnlich wie java"*.
   The stated purpose is to keep the on-MCU VM as small as possible.
2. **Every program must be expressible both ways, always.** Bytecode
   for the VM and transpiled plain C compiled into the firmware are
   **two alternatives, not a feature and an extra** — *"especially for
   Thread SEDs, but also for efficiency in general"*. What is optional
   is the *choice per deployment*, not the capability: during
   development nobody wants to rebuild the whole firmware for a
   one-line change, so the VM path exists; on a battery device the
   VM is the wrong trade, so the C path exists. A construct that only
   one of the two backends can express is therefore **not a language
   feature — it is a bug** (product-owner clarification, 2026-08-16,
   sharpening what "strictly optional" meant in the conversation).
3. **The language must be modular** — usable in parts, e.g. arithmetic
   only, because in reality many scripts are just formulas and
   mathematical expressions and need nothing like function calls.
   Requirement 2 must still hold for the partial configurations.

Plus the audience constraint, stated separately: *"a user of MCUHome should not have to be a
developer and should still be able to write simple scripts."*

Requirement 2 is the same mechanism as §1.5's DEV/LIVE split, seen from
the language side. Requirement 3 is the same as §1.3's "VM assembled
from feature modules". Requirement 1 is the same as §1.3's host-side
compilation. The conversation restates the charter independently and
adds the word **optional** to the C path, which §10 did not say
explicitly.

### 2.2 What else the product owner decided

**Decided**, all 2026-08-16:

| # | Decision | Note |
|---|---|---|
| a | Berry is *"not quite what I would like for the project, which is why I think I will develop a completely separate 'MCUScript'"* | Phrased as intent, not as a formal decision — see §3.3 |
| b | **Python-style syntax is rejected** | Reason: it forces line breaks and indentation; in this use case one often wants 2–3 statements compactly on one line, and inside YAML that means indentation carries two meanings at once |
| c | **The name stays MCUScript** | Because the units problem is solved by profiles, not by renaming — [ADR 0003](0003-name-organization-positioning.md) |
| d | **Own GitHub organization, repo `mcu-script/mcuscript`** | Verbatim, and the only German left in this document because the sentence is the decision: *"mcuscript-lang/mcuscript auf github, so soll es sein!"* — that is how it shall be. The organization was created the same day as **`MCU-Script`**, mirroring `MCU-Home` — [ADR 0003](0003-name-organization-positioning.md) |
| e | Compiler, transpiler and later the profiles should be runnable as their own projects in that org | Settled since: monorepo for the language and its specification, `profile-home` its own repository — ADR 0003 §4 |
| f | **Start with the spec and the bytecode format**, not with the Level-0 prototype | Asked which to start with, he answered: the spec and the bytecode. Note this differs from the MVP advice he was given (§2.3) |
| g | He cannot judge the non-developer perspective himself | *"things automatically seem simple and logical to me that may not be simple for non-developers, and I personally cannot see that"* — a standing constraint on how the language gets validated (§2.9) |

He also confirmed one technical inference himself: units are irrelevant
*inside* the bytecode, because by then everything is normalized to base
units (§2.6).

### 2.3 On the table: static typing and the two-backend invariant

**On the table.** The argument that carries the whole project:

- Requirement 2 dictates **static typing with type inference**. A
  dynamically typed language (Berry, Lua) needs tagged values, boxing
  and runtime dispatch, which transpiles to ugly, inefficient C and
  destroys exactly the SED advantage the C path exists for. Static
  typing gives a clean 1:1 mapping to C, a smaller VM, and errors at
  compile time instead of on the device. For non-developers, inference
  is *more* pleasant than dynamism, because errors appear earlier and
  more comprehensibly. The user writes `x = temp * 1.8 + 32`; the types
  are derived.
- **The biggest trap is backend divergence.** Two backends means
  identical semantics for integer overflow, float rounding, division by
  zero and error handling. The proposal: **define the semantics to
  match C exactly** (`int32_t` wraparound, IEEE-754) so that the VM
  backend is the one that has to conform, and build **differential
  testing from day one** — every test script runs through both
  backends, results must be bit-identical.
- The framing offered for effort: compiler and VM are *"vielleicht
  20 % der Arbeit"*; the other 80 % are bindings, tooling, error
  messages and documentation. *"Languages rarely fail on the technology;
  they fail because nobody maintains the edges."*
- **MVP advice** (not taken, see §2.2f): start with Level 0 only, both
  backends, and the differential test harness — immediately useful and
  it validates the two-backend architecture before control flow and
  functions are added.
- Strategic note: since the combination is unique, *"one source, two backends,
  bit-identical behaviour"* is the project's central
  distinguishing property.

This is the argument that, if it holds, largely settles the
build-versus-adopt question on architecture rather than on measurement.
See §3.3.

### 2.4 On the table: the level split

**On the table.** Three levels, each a Kconfig option, the linker
dropping unused opcodes:

- **Level 0 — expressions**: pure expressions, no allocation, no
  control flow. Compiles to a tiny stack evaluator (estimated
  **< 1–2 KB**) or directly to a C expression.
- **Level 1 — statements**: variables, if/else, loops with an
  iteration limit.
- **Level 2 — functions**, possibly arrays/strings.

Rationale: *"90 % der Skripte sind Formeln."* Note this is a different
axis from §1.2's filter tiers — see §3.1.

Also on the table, as things to nail down before any compiler code:

- **No GC, ideally no heap.** Value semantics, statically dimensioned
  buffers; strings/arrays only with a fixed maximum size or a per-run
  arena. *"a GC on an SED is a nightmare."*
- **Execution budget**: an instruction limit per invocation so a user
  script can never block a Zephyr thread or blow an SED's sleep period.
- **Version the bytecode format and validate it on the device** (magic,
  version, checksum, a verifier). Then scripts update over OTA/Matter
  without flashing firmware — *"that is your actual killer feature
  compared with ESPHome lambdas"*.
- **Design the binding model before the language.** How scripts reach
  entities/sensors/actuators should be generated declaratively from the
  MCUHome config, with codegen for both backends, or bindings get
  written twice.
- **Error messages for non-developers are a feature of their own.**

### 2.5 On the table: syntax

**On the table**, after the product owner rejected Python-style syntax
(§2.2b):

- **Braces as block delimiters, whitespace meaningless**:
  `if temp > 25 { fan.on() } else { fan.off() }` reads identically
  single-line and multi-line, so YAML indentation cannot change the
  meaning of a script. Home Assistant users know braces from Jinja.
- **Newline *or* semicolon as statement separator**, equivalent.
- **if/else is an expression**, Rust/Kotlin style:
  `fan.speed = if temp > 28 { 3 } else if temp > 25 { 2 } else { 0 }`.
  This dissolves the boundary between "formula" and "script": control
  flow is itself an expression, which is what makes the Level-0/Level-1
  split continuous rather than a cliff.
- **No separate ternary `? :`** — an if-expression already *is* the
  ternary, and two spellings for one thing confuse the audience;
  `cond ? a : b` is the most cryptic syntax there is for a
  non-developer. (Note this contradicts §1.2, which names the ternary
  conditional as in-scope for tier 2 — see §3.2.)
- **A `match` expression with guards** for the threshold pattern, which
  is the common case:

  ```
  fan.speed = match temp { > 28 -> 3, > 25 -> 2, else -> 0 }
  ```

  It reads like a table, scales to five levels without becoming an
  unreadable ternary chain, extends later to ranges (`20..25 -> 1`) and
  enum matching without a syntax change, lets the compiler check
  **exhaustiveness** (a missing `else` becomes a comprehensible error
  instead of undefined behaviour), and lowers trivially to an if-chain
  or jump table in C.
- Python affinity is recovered through **vocabulary and semantics**
  (`and`/`or`/`not` rather than `&&`/`||`, no mandatory type
  declarations) rather than through whitespace rules.
- **Embedding**: separate `.mcs` files with inline YAML reserved for
  one-liners and formulas removes the YAML-indentation problem
  entirely. Level 0 is syntax-neutral anyway — `(temp - 32) / 1.8`
  looks the same in every language.

### 2.6 On the table: units, dimensions and profiles

**On the table**, and the richest single part of the conversation. The
*profile* concept that came out of it is load-bearing for
[ADR 0003](0003-name-organization-positioning.md).

- A **pure compile-time feature**: the user writes units, the compiler
  normalizes to one base unit per dimension, and at runtime — VM and C
  alike — only bare integers exist. **Zero overhead**, which is what
  makes it acceptable on an SED.
- Syntax: suffix directly on the literal, no space — `delay 5min`,
  `if runtime > 90s`, `timeout = 1h30min` (composable),
  `brightness = 75%`, `if temp > 24.5°C`.
- **Lexically one token** (number + suffix), so `5 min` versus `5min`
  is not ambiguous and `%` does not collide with a modulo operator —
  if modulo is wanted, spell it `mod`.
- The gain is the **type system behind it**: a duration is its own type,
  not a number. `delay 5` becomes *"delay needs a time — did you
  mean 5s or 5min?"*; `if temp > 5min` becomes *"temp is a temperature,
  5min is a time — those are not comparable"*;
  `runtime + 30s` and `runtime * 2` are fine, `runtime * 30s` is not.
- **Explicit design warning: do not build general dimensional
  analysis** (F#/Boost.Units style, where m/s² arises automatically).
  *"a rabbit hole your audience never needs."*
  Instead a fixed, small list of domain dimensions, each with a fixed
  base unit and permitted operations: `duration` → ms; `temperature` →
  tenths of °C as an integer (`°C`, `°F`, where °F is offset *and*
  factor, converted in the compiler); `percent`; later `lux`, `W`,
  `kWh`, `V`, `A`.
- **Temperature is a special case**: point temperature and temperature
  *difference* are strictly different things (25°C + 25°C is nonsense,
  25°C + 2°C as a delta is not). Modelling that fully is academic;
  pragmatically — allow addition and subtraction, forbid multiplying
  two temperatures, allow °F only on literals.
- **Range checking matters**: `int32` in milliseconds overflows after
  ~24 days, so either time gets `int64` or literals like `30d` are
  rejected at compile time with a clear message.
- **Units are invisible inside the bytecode** but belong in the spec in
  two places:
  1. **The base units are part of the ABI.** When a script reads
     `sensor.temp`, the value the binding delivers at runtime must
     arrive in the base unit the compiler assumed. VM backend, C
     backend and the host must all rely on it, so the base-unit
     definitions belong in the versioned profile, *not* in compiler
     internals. Changing a base unit later (ms → µs) makes all existing
     bytecode **and** all compiled C firmware silently wrong without
     anything crashing.
  2. **Profile ID and version go in the bytecode header**, so a
     mismatch is a clean refusal rather than arithmetic on wrongly
     scaled values — *"the most dangerous class of error there
     is, because it is invisible"*.
- **The dimension table belongs to the embedding, the mechanism to the
  language.** This is what keeps the general positioning honest, and it
  is where the profile layer of ADR 0001's boundary rule comes from.
- The embedder's entity definitions declare the dimension
  (`type: temperature`, `unit: °C`), so the compiler knows that
  `sensor.wohnzimmer > 24°C` has matching sides — and can warn when a
  humidity sensor is compared with °C. *"the point where units go from a nice
  feature to real error prevention."*

Two internal contradictions were left unresolved in the conversation
and are carried into §8: the time base is given once as `int32` ms and
once as `int64` ms, and the percent base unit is left open (0–100 vs.
0–255 vs. 0–1000, *"depending on what your actuators expect"*).

### 2.7 On the table: the bytecode container and the VM

**On the table.** This is what the product owner chose to start with
(§2.2f), so it is recorded in full detail.

**Container format** (loosely ELF/WASM-shaped, minimal):

```
Header:  Magic "MCUS" | format version | flags
         profile ID + profile version | CRC32
Sections (each: type, length, data):
  CONST  constant pool (values larger than the inline size)
  CODE   instructions
  ENTRY  entry points (script id → code offset, stack requirement)
  HOST   import table (which host functions/entities the script needs)
  DEBUG  optional: line mapping, strippable
```

Unknown section types are skipped — the extension path. The ENTRY
section carries the **maximum stack requirement the compiler computed**,
so the VM allocates statically and never checks or grows at runtime;
that is possible only because of static typing *and* the absence of
recursion.

**Execution model: stack machine, untagged, typed opcodes.** Values on
the stack are bare 32-bit cells with no type tag; the type is in the
opcode (`ADD_I` vs. `ADD_F`, JVM-style), so the VM never dispatches on
"what is this?" and each opcode is 5–15 lines of C. A register machine
(Lua-style) would be faster but needs explicit operand fields — wider
instructions, more decoding, more cases per opcode, plus register
allocation in the compiler and a harder verifier. For a code-size
priority, stack wins; for formulas its code density is better anyway.

Instruction format: 1 byte opcode, 0–4 bytes of operands, variable
length. Sketched set: `PUSH_I8`, `PUSH_CONST`, `LOAD_HOST`,
`STORE_HOST`, `LOAD_L`/`STORE_L`, `ADD_I`/`SUB_I`/`MUL_I`/`DIV_I`/
`ADD_F`…, `CMP_GT_I`/`CMP_EQ_I`…, `JMP`/`JMP_IF_FALSE`, `CALL_HOST`,
`RET`. The worked `match` example above compiles to roughly **25 bytes**
for the whole logic.

Stack discipline: every opcode pops its inputs and pushes at most one
result, so the stack breathes rather than grows; every opcode has a
fixed known stack effect, which is what lets the compiler compute the
exact maximum depth (2 cells in the worked example; typical formulas
4–8, complex scripts rarely over 16–32). The invariant that gives
safety: with a correct compiler the stack is empty at `RET`, and **a
load-time verifier recomputes exactly that** — the same arithmetic as
the compiler, run as a check.

**The HOST table is the mechanism that makes scripts OTA-updatable.**
The script references entities only by index; the section carries the
symbolic names (`"fan.speed"`) plus expected type and dimension. On
load the VM resolves the names once against the host registry
("linking") and checks type and profile compatibility; after that,
accesses are array indexing. This is what decouples a script from the
concrete firmware version.

**Opcode groups** (core-int, float, control flow, host calls, later
strings) are declared in the spec, and the VM links only the groups
selected by Kconfig — the mechanism behind requirement 3. A pure
formula device without float and without loops is estimated at
**1–2 KB flash** of VM.

**The transpiler must not translate bytecode → C.** Both backends
generate from the same typed intermediate representation: frontend →
typed IR → backend A (bytecode) / backend B (C). From the IR, `match`
becomes a plain if-chain that GCC optimizes through; from bytecode it
would become spaghetti with stack simulation.

### 2.8 On the table: calls, recursion and budgets

**On the table.**

- Arguments are pushed by the caller and *become* the callee's first
  locals — no separate passing, just a shifted reference point. The VM
  needs a frame pointer and a small call stack; `LOAD_L 0` is relative
  to FP. `CALL` saves return address and old FP, points FP at the first
  argument and reserves the extra local slots; `RET_V` pops the return
  value, resets the stack pointer to FP (clearing arguments and locals
  in one step), restores FP and PC, and pushes the result. Net effect
  from the caller's view: *n* in, one out — so calls compose without
  special cases.
- `CALL_HOST` is the counterpart for C functions: pop the arguments per
  the HOST-table signature, call the registered function pointer, push
  the result. No frame, no call stack. It belongs in the **core**,
  because every `fan.set_speed()` needs it — whereas `CALL`/`RET_V` and
  the call stack simply do not exist below Level 2, so a formula device
  carries zero bytes of call machinery.
- The conversation argued for **no recursion at all**, which keeps the
  call graph acyclic and lets the compiler compute the worst-case
  value-stack and call-stack depth per entry point, and it argued hard
  against the product owner's suggestion of per-call malloc'd frames:
  those **break the two-backend invariant**, because in the C backend
  the same functions run on a fixed-size Zephyr thread stack —
  recursion that survives 500 levels in the VM would overflow after 50
  as transpiled C, at best crashing and at worst corrupting memory
  silently. Malloc per call also fragments the heap on every event
  trigger, and a half-executed script that has already written two
  entities has no rollback when an allocation fails.
- **Decided (product owner, 2026-08-16): recursion is allowed, and it
  is hard-capped.** Not "no recursion" and not unbounded frames, but
  the bounded middle: a small fixed maximum depth, on the order of
  **five self-calls**. That keeps everything the no-recursion argument
  was protecting — the worst case stays statically computable (stack
  requirement = frame size × cap), both backends can honour the same
  number, and a runaway script is a compile-time or load-time refusal
  rather than a dead device — while not forbidding a construct users
  may reasonably reach for.
- **Decided with it (product owner, 2026-08-16): a language default,
  overridable per function.** The default keeps the common case free of
  ceremony; a function that genuinely needs more says so at its own
  declaration, which also makes the cost visible where it is incurred.
  A per-function override is what keeps the worst case computable —
  the number is in the source, so the compiler can multiply it by the
  frame size without guessing.
- **Decided with it: the cap counts every cycle in the call graph, not
  just self-calls.** Two functions that call each other blow the same
  stack as one that calls itself; a self-call-only rule would let
  exactly that through. So the compiler finds strongly connected
  components in the call graph and applies the cap to the cycle, not to
  the function.
- What the decision does not yet settle, and the spec must: the actual
  default number; how the C backend enforces the cap, given that C has
  no recursion counter of its own and the transpiled functions are
  ordinary C functions on a fixed Zephyr thread stack; and what happens
  when the cap is reached at runtime — refusal before the call, or an
  aborted script with the §2.11 rollback question attached.

### 2.9 On the table: designing for non-developers, and how to validate it

**On the table**, and the direct answer to §2.2g. Language ideas that
come from how non-developers actually think:

- **Units in the language** (§2.6) — nobody thinks in bare numbers, and
  millisecond-versus-second bugs are among the most common errors
  anywhere.
- **`unavailable` as a language concept instead of `null`.** The most
  common real failure in a smart home is a sensor with no current
  value; Home Assistant templates crash on it constantly. Solve it in
  the language — `temp else 20` as a fallback, or a defined "the
  expression is skipped when a value is missing". An exposed `null`
  with crash semantics is the opposite. (This is §1.2's null coalescing,
  made concrete.)
- **Decided (product owner, 2026-08-16): `invalid` exists alongside
  `unavailable`, as a second explicit concept.** One absence is not
  like the other. *Unavailable* is "there is no value right now" — the
  sensor has not been read yet, the device is asleep, the remote node
  is unreachable; it is expected, it is temporary, and a fallback is
  usually the right answer. *Invalid* is "there is a value and it must
  not be used" — a sensor reporting a fault, a reading outside the
  physical range, the result of a division by zero; it is a defect, not
  a wait, and silently substituting a fallback would hide it. Collapsing
  both into one `null` is what makes template languages fragile: the
  user cannot write different handling for "not yet" and "broken"
  because the language does not distinguish them.
  **Direction (product owner, 2026-08-16): `invalid` behaves like
  NaN** — it propagates through arithmetic rather than stopping the
  expression, so a computation touched by a faulted reading yields
  `invalid` rather than a plausible-looking number. That is the right
  instinct and it is exactly how IEEE-754 handles the analogous case
  for floats.
  What it does not yet answer, and what the spec must: **integers have
  no NaN.** A propagating `invalid` over integer arithmetic needs a
  mechanism — a reserved sentinel value (which collides with real
  data), a validity bit shadowing every value (which widens the stack),
  or a per-evaluation flag (which loses which operand was bad). Also
  open: whether `else` catches both kinds or only `unavailable`; what
  `invalid > 5` evaluates to, given that three-valued logic has a long
  record of confusing people; and what both become when a value crosses
  into the C backend, where neither has a natural representation.
- **No silent wrong behaviour**: `=` versus `==` (forbid assignment
  where a condition is expected, with an explaining compile error);
  integer division (`3 / 2 = 1` is simply wrong to a layman — make `/`
  always float and `//` or `div` integer); no silent coercions. The
  error must **explain**, not just report.
- **Error messages budgeted as a core feature**: *"Did you mean
  `fan.speed`? There is no `fan.sped`"*, with a Levenshtein
  suggestion drawn from the known entity names, is worth more to this
  audience than any language feature. Elm and Rust are the models.

And the methods for getting the view rather than guessing it:

- **The first-guess test**: give people with no programming knowledge a
  task in prose — *"write a rule: light at 50 % when it is dark
  and somebody is home"* — **before** they have seen any syntax, and
  look at what they write. Design goal: the first guess should be valid
  syntax as often as possible. Called the single most productive
  method; 3–4 people already expose the coarse patterns.
- **Home Assistant and ESPHome forums as a corpus** of real
  misunderstandings — read what beginners got wrong about Jinja and
  lambdas, not just the answers.
- **Existing research**: the *Natural Programming* studies by Pane &
  Myers (CMU) examined exactly this. Reported core findings: laypeople
  think in **event-condition-action**, use "and" for *enumerations of
  actions* rather than boolean conjunction, and think in **sets rather
  than loops**. The language *Quorum* came out of that line of work.
- **Copy-paste is the real learning path**: non-developers do not read
  a language reference, they copy an example and change the numbers. A
  gallery of ~30 typical snippets shapes the perception of the language
  more than the documentation does — and doubles as the test corpus for
  both backends.
- Priority given: **units, unavailable-handling and error messages**
  are the three to plan before the first line of compiler code,
  because all three are hard to add later.

### 2.10 Prior art as surveyed in the conversation

**On the table.** These are the conversation's characterizations. They
were spot-checked against the projects on 2026-08-16 and mostly hold;
where the check disagreed or added something, it is noted in the table
and below it.

| Project | As characterized |
|---|---|
| **Toit** | Closest on overall goal: an MCU-designed VM in the Java tradition, compiler + VM + standard libraries, live reload over WiFi in under two seconds. But garbage-collected, practically ESP32/FreeRTOS-bound rather than Zephyr, **no C transpile path**, and a full OO language aimed at developers. Its VM and container design called required reading |
| **Nelua** | The other half: statically typed, Lua-like, compiles to plain C — requirement 2 exactly, but **no VM backend** |
| **Pawn** | The proof for the VM side: curly-brace language, small-footprint VM, data as 4/8-byte cells, static, decades in embedded products — but no transpilation and dated syntax |
| **Umka**, **Tiny** | Statically typed, GC-light embeddable VMs |
| **q3vm** | C itself as the scripting language, compiled to bytecode for a tiny sandboxed VM. A thought model; C-writing end users are the thing being avoided |
| **Berry**, **MicroPython** | The only ones from the smart-home world; both dynamic, both without a transpile option |
| **ESPHome** | Has nothing beyond C++ lambdas |
| **Nim**, **Cython**, **Mojo** | Existence proofs that Python-like syntax over static semantics compiles to C fine |

The conclusion drawn: the exact combination — simple language for
non-developers + always a bytecode VM + optional C transpilation from
the same source + a modular expression subset — **does not exist as one
project**, and the pragmatic path is not to start from zero but to
borrow deliberately: Toit's VM and OTA architecture, Nelua's C codegen
approach, Pawn's proof of how small a static VM can be, Berry's binding
model from the Tasmota deployment.

**What the spot-check found (2026-08-16).** Toit's garbage collection,
its ESP-IDF coupling and the sub-two-second live reload hold; Berry's
MIT license, dynamic typing and *"interpreter-core's code size is less
than 40KiB […] on less than 4KiB heap"* hold; Nelua is confirmed
statically typed, compiling to C, no VM, and **alpha**; Pawn's 4/8-byte
cells hold and it still has an IA-32 JIT; Wren's last release is 0.4.0,
April 2021; Pane & Myers and Quorum are real, and the
event-condition-action finding is theirs.

Three near-misses the conversation did not name, and they matter
because they narrow the claimed gap:

| Project | Why it is closer than anything in the table above |
|---|---|
| **Cyber** | The closest existing combination found: a bytecode VM *and* a C output path. Fails on audience and on being designed for embedding at this size, not on the two-backend idea |
| **WAMR + wasm2c** | Technically *does* have both backends from one artifact — but the artifact is WebAssembly, which is a compilation target, not something a non-developer writes |
| **PikaPython** | A Python-like VM running on 64 KB flash / 8 KB RAM, so the footprint end of the claim is less exotic than it sounds. No transpile path |

And the honest status of the central claim: the survey **could not find**
a project combining all four properties, which is not the same as
proving none exists. Recorded as *unverifiable*, not as *confirmed*.

### 2.11 Gaps already visible in the sketch

Not from the conversation — this is what a review of §2.7 and §2.8
against real binary formats (WebAssembly, the JVM class file, ELF, eBPF)
turned up on 2026-08-16. It is recorded here because the product owner
chose the container as the starting point (§2.2f), and these are the
things that would otherwise be discovered by writing them wrong first.

1. **No endianness declaration.** ELF puts byte order in
   `e_ident[EI_DATA]`; the JVM fixes big-endian by fiat. The sketch does
   neither, and its whole point is that bytecode compiled on a
   workstation runs on an ARM device.
2. **No alignment rule.** Variable-length instructions leave multi-byte
   operands at arbitrary offsets. Unaligned access is undefined
   behaviour in C and a fault on some targets — for untrusted input,
   that is a denial of service.
3. **No total length in the header.** Every section states its own
   length and nothing states the file's, so a truncated container is
   only detectable by arithmetic that a hostile file controls.
4. **CRC32 is integrity, not authenticity — and authenticity is not
   this project's to provide.** How bytecode reaches a device and what
   vouches for it is the embedder's business (ADR 0001): it may arrive
   over an authenticated channel, be signed, or sit on an SD card as a
   plain file. What the *format* owes is (a) a checksum that says
   plainly it detects corruption and nothing else, so nobody mistakes
   it for a security mechanism, and (b) an extension slot an embedder
   can put a signature in without the language deciding anything —
   which the optional-section mechanism of gap 5 already provides. The
   obligation lands on the embedder and is listed in §4.
5. **"Unknown sections are skipped" has no must-understand flag.**
   WebAssembly separates custom sections (skippable) from defined ones;
   ELF is built for it. Without that split, a v1.1 compiler emitting a
   section a v1.0 VM does not know produces a *silently partial* run
   rather than a refusal — the failure mode the extension path was
   supposed to prevent.
6. **Verification is described as optional, and the VM trusts the
   ENTRY section's stack depth.** Untrusted bytecode plus trusted
   metadata is the classic verifier bypass: a container claiming depth
   2 while needing 20 overflows a statically allocated stack into
   whatever is next to it. The JVM makes verification mandatory for
   exactly this reason. If the VM allocates from a number in the file,
   recomputing that number cannot be a build option.
7. **The time base is `int64` milliseconds — and it does not fit a
   32-bit cell.** The conversation gave the base as `int32` ms in one
   place and `int64` in another; the product owner settled it on
   2026-08-16: **milliseconds as `int64`**. Millisecond resolution is
   kept, and the ~24.9-day overflow of `int32` ms is gone.
   The consequence is now the spec's problem rather than an open
   choice: §2.7 says stack cells are 32 bits and every opcode pushes at
   most one result, and a 64-bit value satisfies neither. Either
   64-bit values occupy **two cells** — which changes the stack-effect
   arithmetic that the compiler's depth computation and the verifier
   both rest on, and needs its own opcode set (`ADD_I64`, …) and a rule
   for how a two-cell value is addressed as a local — or the cell
   widens, which costs RAM on every script. The C backend has neither
   problem, which makes this a place where the two backends could
   diverge if the VM's rules are left implicit.
8. **The HOST table's failure modes are unnamed.** Name not in the
   registry, type mismatch, dimension mismatch, duplicate name, a write
   to a read-only entity, an opcode from a group this build did not
   link — the JVM and WebAssembly both enumerate their linking errors
   exhaustively, and diagnostics for non-developers (§2.9) are
   impossible without that list.
9. **Nothing records which opcode groups a container needs.** With
   groups selected per Kconfig (§2.7), a device that linked no float
   support must reject float bytecode at load time. It can only do that
   if the requirement is written in the header.
10. **Termination is this project's problem; atomicity is the
    embedder's.** The two were conflated. A script that stops early —
    because a budget fired, or because it faulted — may have already
    written two entities and cannot undo them, which is the same
    objection §2.8 raises against heap frames. But writes go through
    the host, so whether they take effect immediately or buffer to a
    commit point is a *host* policy, not a VM one, and both backends
    inherit whichever the embedder implements. What the language owes
    is narrower and still real: proving that a script terminates, and
    **specifying whether a script may observe its own write** — because
    that is observable behaviour, and a language that leaves it
    genuinely undefined makes scripts non-portable between
    embedders.

### 2.12 Proposed answers to §2.11 — researched, not yet signed off

A research round on 2026-08-16 worked through the gaps above against
WebAssembly, the JVM, ELF, PNG, eBPF, MCUboot/SUIT and IEC 61131-3, and
each recommendation was then attacked by a separate reviewer. What
follows is **the proposal, not the decision** — it moves to *decided*
only when the product owner signs it off, and three items are questions
for him rather than engineering calls.

**The value model — uniform 8-byte stack slots.** The forcing argument
is not the one the research found. Scripts are event-driven and run to
completion without re-entrancy, so the device needs **one** interpreter
stack, sized to the static maximum over all scripts — not one per
script. The difference between 4-byte and 8-byte slots is therefore
something like 64 bytes on the whole device, not per script, and it buys
away the JVM's entire category-2 apparatus: no two-slot values, no
`dup2`/`pop2` family, no "is this slot the high half of something"
bookkeeping in the verifier, and the "pops n, pushes at most one"
invariant survives literally. eBPF makes the same choice for the same
reason. int64 milliseconds (§2.6) then fits a slot with nothing special
about it.

**Typing is validated at load, not tagged at runtime.** Slots carry no
type tag; the verifier walks the code with a type stack and rejects
bytecode that would add an i32 to an f32 — WebAssembly's model. This is
not extra work: R5 (untrusted bytecode) and R6 (static typing) require a
type-checking verifier anyway, and once it exists the runtime needs no
tags at all.

**Opcodes stay per-type, against the research's recommendation.** It
proposed one opcode family plus a type byte. Rejected on two counts:
a type immediate costs a byte on every instruction, which is exactly
where a formula's density lives; and it defeats §2.4's droppable
groups, because float handling would then sit inside every arithmetic
handler's switch instead of in an opcode range the linker can remove
whole. With a deliberately small type set the count stays modest —
roughly seventy opcodes, in JVM/WebAssembly territory at a fraction of
their type sets.

**Byte-granular slots and an overflow flag: both rejected.** Cell
granularity and opcode count are independent — an addition is one
opcode whether the stack is an array of cells or an array of bytes, so
byte granularity buys nothing and costs unaligned access, which faults
outright on Cortex-M0+. A carry/overflow flag is worse: it is VM state
that portable C cannot reproduce, so it would break R2 by construction.
Overflow, if it needs to be observable, is a checked *operation*
yielding `invalid`, which both backends can implement identically.

**Narrow targets are not a constituency.** Zephyr 4.4.0's `arch/`
directory contains arc, arm, arm64, mips, openrisc, posix, riscv, rx,
sparc, x86 and xtensa — verified in the pinned checkout. There is no
8-bit or 16-bit target, so nothing in the first embedder's world would
benefit from narrowing, and parameterising the slot width per target
would make the same bytecode behave differently on two devices, which
defeats R1 and R2 at once.

**The container**, gap by gap: little-endian fixed with no header field
for it (WebAssembly's choice; every plausible target is little-endian);
sections 4-byte aligned with explicitly byte-wise header reads, so
Cortex-M0+ never faults; a total-length field in the header, so
truncation is detectable without trusting section lengths; PNG's
critical-bit convention on the section identifier, so a section a reader
does not know is either safely skippable or a hard refusal and never
silently ignored — and so an embedder can attach a signature section
without the format needing to know what a signature is; a CRC that the
spec labels explicitly as corruption detection and **not** a security
mechanism; **verification mandatory and never a build option**,
recomputing the stack depth rather than trusting the ENTRY section;
required opcode groups declared as a bitmask in the header so a build
without float refuses at load instead of misbehaving; and the eight
HOST linking failures named individually as load-time errors, modelled
on the JVM's linking-error hierarchy.

**Termination is proved, not metered.** With loops bounded (§2.4) and
recursion capped (§2.8), a script's termination is provable at load
time the way eBPF proves it — so there is no per-opcode counter, the
runtime counts nothing, and the C backend has nothing awkward to
imitate. This is the half of gap 10 that belongs to the language.

The other half does not. Whether a partly-run script's writes are
undone, and whether a script can observe its own write, are **host
policies**: writes leave through the host interface, so an embedder
that buffers them to a commit point gets atomicity, and one that
applies them immediately does not, and both backends inherit whichever
it chose. The industrial answer is worth citing to embedders — IEC
61131-3's scan cycle reads inputs into an image, computes, and writes
outputs at the end, which is why a PLC cut mid-scan leaves a plant
consistent — but citing it is the most this project should do. What it
*must* do is say in the specification which behaviour a script may rely
on, rather than leave it genuinely undefined and make scripts
non-portable between embedders (§4).

**Float ships from the first version (product owner, 2026-08-16).**
Integer semantics pin down without difficulty — wrapping defined
explicitly, division and modulo by zero yielding `invalid`, shift counts
and negative shifts specified rather than left to C. Float is harder:
bit-identity depends on `-ffp-contract`, `-ffast-math` and denormal
handling. Measured locally on GCC 16.1.1, `a*b+c` contracts to a single
FMA under `-std=gnu11` and does not under `-std=c11` — the same
compiler, the same source, two results, decided by a flag nobody thinks
about.

The decision is to include it, single-precision IEEE-754, and to make
the language state its requirement rather than assume it: the generated
C carries `#pragma STDC FP_CONTRACT OFF` itself, the specification names
the flags that must not be set, and the differential harness runs on
host and device with the host forced to single precision. That is what
Java and WebAssembly do, and it puts this in the same place as
everything else on this boundary — the language specifies the
semantics, the embedder's build must honour them, and a build that does
not is the embedder's defect. Which is consistent rather than
convenient: the same reasoning that hands transport and storage to the
embedder hands it responsibility for its own compiler flags.

---

## 3. Reading the two sources together

### 3.1 Tiers and levels are different axes

The two sources both count to three, and they are not counting the
same thing. Conflating them would be the first serious mistake this
project could make.

| | component-model.md §10 — **tiers** | the conversation — **levels** |
|---|---|---|
| What it classifies | what the **builder links** for a given configuration | what the **language** offers |
| 1 / 0 | predefined filters: registry entries, C-owned state — **not a language at all** | Level 0: expressions, no allocation, no control flow |
| 2 / 1 | expressions: no state, no heap, no GC | Level 1: statements — variables, if/else, loops with an iteration limit |
| 3 / 2 | scripting engine: state, `on_boot` hooks, timers, actions | Level 2: functions, possibly arrays/strings |

The mapping that actually holds:

- **Tier 1 has no counterpart.** Predefined filters stay a MCUHome
  registry feature and are not MCUScript, even if MCUScript is built.
- **Tier 2 ≈ Level 0.**
- **Tier 3 ≈ Level 1 + Level 2 + the host side.** Hooks, timers and
  actions are not language levels at all — in the conversation's design
  they are `CALL_HOST`, entry points in the ENTRY section, and the
  embedder deciding when to run a script. They are an *embedding*
  concern in the sense of ADR 0001's boundary rule.
- **"Cheapest tier wins" and "Kconfig-selected opcode groups" are the
  same idea** in two vocabularies. §10 says the builder picks the
  cheapest tier that covers the configuration; the conversation says
  the VM links only the opcode groups the scripts on this device
  actually use. The second is the implementation of the first.

### 3.2 Where they disagree

A review of the two sources against each other on 2026-08-16 found
**two** real disagreements. Two more that look like disagreements
dissolve on inspection, and they are recorded as such so nobody
re-opens them.

Real:

1. **The ternary operator.** §1.2 names *"the ternary conditional"* as
   in-scope for tier 2 and its worked example uses `? :`. §2.5 argues
   explicitly against a separate `? :` — an if-expression is the same
   thing, and two spellings confuse the audience. Both cannot survive.
   The functionality is not in question, only the spelling.
2. **Sequencing.** §1.4 says the tier-2 expression engine is built
   inside MCUHome first *"so it can be promoted into the standalone
   project rather than rewritten"*. §2.2d/f start the standalone
   project first, with the spec. The conversation's order won by
   default; it should be said out loud rather than left as a
   contradiction between two documents.

Apparent, and resolved:

3. **Where variables live.** §1.2 says an expression has *"no state"*
   and that *everything stateful* lives in tier 1 with C-owned state;
   §2.4 puts variables in Level 1. Different meanings of "state": tier
   1 owns state that **survives between invocations** (the window of a
   moving average), Level 1's variables are **scratch within one run**,
   discarded at `RET`. Both statements hold. What the documents do not
   yet say is whether a script may have persistent state of its own —
   and the answer implied by §1.2 is no.
4. **Generated C control flow.** §1.8 says automations compile to a
   static table read by a small interpreter, *"no generated C control
   flow"*; §2.7's C backend generates exactly that. Two different
   mechanisms under tier 3: the declarative `automations:` table, and
   the script transpiler. Neither forbids the other. What remains open
   is not a conflict but an allocation — which of the two owns a given
   piece of user logic, and whether a device may carry both.

One near-disagreement that turns out to be a **precision**: §1.6 says
*"scripts work in user units"* with conversion in the C binding; §2.6
says base units per dimension are part of the ABI. These agree, and
§2.6 says what "user unit" means. The consequence for MCUHome is real
and is §4's first item.

### 3.3 The build-versus-adopt question belongs to the embedder

§1.3 says an engine decision belongs to a MCUHome automation-phase ADR
backed by a **measured prototype**. It is easy to read that as a
question about whether MCUScript exists. It is not, and separating the
two is what makes this project's position coherent:

| Question | Whose | Status |
|---|---|---|
| Is MCUScript built? | **This project's** | Yes. It has a name, an organization, a domain and a starting point, and it is developed independently of any embedder's schedule (ADR 0003) |
| Does MCUHome embed MCUScript, or Berry, or a hybrid? | **MCUHome's** | Open. That is the automation-phase ADR §1.3 calls for, and it is written in MCUHome's repository, not here |

Nothing below changes the first row. It is about the second, and it is
recorded here only because the argument was made in the conversation
that seeded this project — and because an argument that would decide
against this project's first embedder is one this project should state
accurately rather than quietly.

- **The direction of MCUHome's choice is evident; the justification is
  not yet written.** The product owner has committed enough to name the
  project and found an organization for it. Pretending MCUHome's choice
  is wide open would be dishonest.
- **The reason has moved, and it is weaker than it looks.** §10
  expected a footprint comparison — can Berry fit? The conversation
  supplies a different argument, not about footprint at all:
  requirement 2 (transpile to C) is said to be incompatible with a
  dynamically typed engine, and Berry, Lua and MicroPython are all
  dynamically typed. If that held absolutely, no measurement of Berry's
  flash usage could change the outcome, because Berry would fail on a
  requirement rather than on a number.

  **It does not hold absolutely.** An adversarial check of the argument
  on 2026-08-16 found it overstated in three places, and the honest
  version is narrower:

  - What makes generated C efficient is **type inference**, not a
    typed-by-default surface language. Cython is the demonstration in
    both directions: the same source compiles to slow C when the types
    are unknown and to fast C when they are known, and the knowing can
    come from inference. RPython's toolchain infers static types out of
    unannotated code. So "dynamic language" does not imply "bad C" —
    *unanalyzable* code implies bad C, and a dynamic language can be
    restricted until it is analyzable.
  - **Bit-identical results across two backends are hard regardless of
    typing.** Float behaviour depends on compiler flags, intermediate
    precision and hardware, not on whether the source language had
    types. Static typing does not deliver §2.3's invariant; disciplined
    backend design does.
  - **The recursion cap** (§2.8) is a sound constraint, but it is not
    an argument for a new language — MISRA C forbids recursion
    outright, and Berry or Lua could be restricted the same way.

  What survives is real but smaller: a statically typed language makes
  the analyzable subset the *default* rather than something the user
  must stay inside, and it is what allows the compiler to compute stack
  depth, reject cycles and check units at compile time. That is a good
  argument. It is not a proof that adoption is impossible.
- **The hybrid was never actually rejected.** §1.2 already says the
  expression tier is small enough for MCUHome to own. Adopt Berry for
  the script tier, own a statically typed expression tier, transpile
  only that — most of §2.1's requirement 3 (formulas are the common
  case) says this covers most scripts. The conversation moved past this
  without costing it, and nobody has costed it since. Note the
  conversation's own estimate cuts both ways: if compiler and VM are
  only 20 % of the work and the other 80 % is bindings, tooling,
  diagnostics and documentation, then adoption saves 20 % and both
  paths owe the rest.
- **So what is owed is a proof of the architecture, not a benchmark of
  Berry.** One source, a VM and generated C, bit-identical results on a
  real corpus. That is exactly the MVP proposed in §2.3 and not taken
  in §2.2f. The automation-phase ADR that §1.3 calls for still has to
  be written, and it should record this reasoning — including the
  hybrid it rejects and why — rather than a flash-size table.
- **Berry remains the recorded fallback** (§1.3), and after this check
  it is a more serious one than it looked an hour earlier.

---

## 4. What this requires of an embedder

Nothing in this section is decided anywhere. These are the obligations
the design places on **whoever embeds MCUScript** — the reason the C
API of §8 #7 is not just a header file but a contract. They are written
against MCUHome because it is the only embedder there is and its
documents are readable; each one generalizes, and the generalization is
the part that belongs to this project.

They are listed here for two reasons: a second embedder would need the
same list, and MCUHome cannot see most of it from inside — nothing in
its documents says any of this yet.

1. **The channel binding must deliver values in the profile's base
   unit.** Today `channel.h` converts Zephyr's unit straight to the
   Matter raw unit in one integer step (§1.9). With a script in
   between, that conversion splits in two: sensor → profile base unit,
   where the script operates, then → Matter raw unit. That is a change
   to the channel contract, i.e. a contract-version bump under
   mcuhome-sdk ADR 0014.
2. **The entity registry must expose type and dimension per entity**,
   because the HOST table is resolved against it at load time and the
   check is what makes a wrong-profile script a refusal rather than a
   wrong number.
3. **The YAML configuration must declare dimensions**
   (`type: temperature`, `unit: °C`). `yaml-schema.md` has no such
   concept today.
4. **MCUHome must publish and version a home profile as an artifact.**
   A profile is part of the bytecode ABI (§2.6); it cannot be an
   implementation detail of the builder. Nothing in MCUHome owns this
   yet.
5. **The script transport must carry the profile ID and version**, and
   a mismatch must be a typed refusal. The transport is the CoAP
   maintenance channel that mcuhome-sdk ADR 0010 deferred (§1.10).
6. **Someone must sign pushed bytecode.** ADR 0015 records that
   MCUboot's signature is the only payload trust anchor in the existing
   path — and a script push deliberately does not go through MCUboot.
   A CRC32 in the container header is an integrity check, not an
   authenticity one, and §1.6 requires an authenticated channel. Whether
   authenticity comes from the channel or from a signature in the
   container is undecided, and it is MCUHome's decision because it owns
   the transport.
7. **The attachment point in the YAML schema must be decided.**
   `yaml-schema.md` §8 reserves an `expression:` key; the conversation
   assumes `.mcs` files with inline one-liners. Those are different
   surfaces and both need a home.
8. **The reserved script region gets a real format.** ADR 0015 reserved
   it with size zero and said the format is decided in the scripting
   phase (§1.10); §2.7 is the first sketch, §2.11 lists what it is
   still missing, and the two documents will have to agree on framing,
   alignment and whether the region holds one container or several.
9. **The embedder decides, documents and applies uniformly whether a
   script's writes are buffered.** Writes leave through the host
   interface, so atomicity is the embedder's policy, not the VM's — but
   both backends must inherit the same one, and users need to know
   which they have. IEC 61131-3's scan cycle (buffer, commit at the
   end) is the model worth copying: a script cut short then leaves the
   device unchanged rather than half-updated.
10. **MCUScript becomes a pinned dependency.** §1.4's charter says
   MCUHome pins an engine release the way it pins Zephyr and the Matter
   SDK — which in practice means an entry in the west manifest and in
   the build container, plus the compiler reaching the builder. Neither
   `west.yml` nor the container definition knows this project exists.

---

## 5. What this repository's existence does not mean

1. **That the language is specified.** Everything in §2.3 through §2.9
   is a proposal that the product owner has not answered.
2. **That "DEV mode" means what it means elsewhere.** mcuhome ADR 0019
   uses `clean`/`incremental` build modes and notes that *"the script
   'DEV mode' this originally anticipated was overtaken by ADR 0020's
   build methods"*. That is about warm build workspaces, not about
   §1.5's DEV/LIVE device modes. The names collide; the concepts do not
   touch.
3. **That tier-1 filters are scripting.** Predefined filters with
   C-owned state stay a MCUHome registry feature even if MCUScript
   never exists (§3.1).
4. **That MCUHome is committed to embedding it.** That is MCUHome's
   decision, made in MCUHome's repository (§3.3). This project proceeds
   either way.
5. **That MCUHome governs it.** The requirements came from there, the
   process was adopted from there, and the first embedder is there.
   None of that is ownership: the organization, the ADR sequence, the
   release cadence, the copyright line and the domain are this
   project's own (ADR 0003).

---

## 6. How much of this exists as code

**None of it.** Not here, and not on the embedder's side either:
MCUHome parses an `automations:` block only in order to refuse it —
*`"automations:" is not implemented yet`*, a refusal pinned by its own
tests — and it contains no filter, expression or script code at all.
The word "expression" appears in its C sources exclusively as a
prohibition (§1.9).

That deserves one paragraph rather than a survey, and it is worth
saying because it means nothing in this record is load-bearing for
running software yet. Every constraint above is a promise about code
that does not exist, on both sides of the boundary.

---

## 7. Vocabulary the first embedder already fixed

`GLOSSAR.md` (German, MCUHome workspace, untracked) carries the terms,
and its definitions are the product owner's mental model: **VM** as "the
interpreter core of a scripting language […] that runs script code on the
chip"; **GC** as "on MCUs the main reason why script engines need more
RAM than their baseline suggests"; **Berry** as "core < 40 KB flash […]
the most important practical precedent in our field"; **WASM** as
evaluated and rejected for this purpose because "users would need a
compiler toolchain". Entries for
MCUScript, profiles, the two-backend invariant and the stack machine
were added on 2026-08-16.

---

## 8. Open questions

Fourteen of the earlier entries were answered by the specification
(`spec/`, all five chapters in draft since 2026-08-16) and are gone
from this list rather than marked: the container and its ten gaps, the
verifier's duties, how a 64-bit value lives in the machine, the
mechanism behind `invalid`, how the recursion cap is enforced in the C
backend, the execution budget, read-back of a script's own writes,
whether a script may hold state between invocations, and the
spec-versus-prototype sequencing.

One more went the same way once there was something to measure: the
float build flags. `-ffp-contract=off`, never `-ffast-math`, and the
harness pins host precision by compiling one program both ways and
asserting the results come apart (ADR 0004 §4.5, spec §1.5).

The **C API toward embedders**, which this list called its largest open
item, is gone too — not decided in the abstract but settled by having
been written (ADR 0004, `runtime/include/mcuscript.h`). An embedder
declares imports and three callbacks, loads, and invokes. Designing it
before writing the VM would have been guessing. What is left:

| # | Question | From |
|---|---|---|
| 1 | No flash/RAM budget has ever been measured for the engine on any target. The 1–2 KB figure for an expression-only VM is an estimate and always was | §1.3, §2.7 |
| 3 | The grammar. The specification deliberately does not cover syntax, and the ternary conflict of §3.2 is still unresolved | §2.5, §3.2 |
| 4 | The recursion cap's **default** is provisionally **5** (product owner, 2026-08-16), and provisionally is the whole answer: the mechanism is specified and enforced (spec §5.4, ADR 0004 §4.7), but which number annoys the fewest authors is a thing real use decides. Nothing depends on it yet — a container declares its cap and the assembler requires one, so the default exists only for a compiler that does not | §2.8 |
| 5 | The counted-loop construct, reserved as a group but undesigned — and it must keep termination provable | spec §3.8 |
| 6 | The percent base unit (0–100 / 0–255 / 0–1000). A profile question, but the first profile must answer it; Matter uses 0–254 for level and 0–10000 for percent100ths | §2.6 |
| 8 | The host compiler's implementation language. A compiler only Python embedders can run is a different product from one anybody can | §1.4 |
| 9 | How the non-developer validation actually gets done, given that the product owner has said he cannot judge it himself | §2.2g, §2.9 |
| 10 | "Static inference is more pleasant for non-developers" is unevidenced, and sits oddly beside Pane & Myers, who found laypeople think in events and sets rather than in types | §2.3, §2.9 |
| 11 | The "90 % of scripts are formulas" figure has no source. It decides how much of the language most users ever meet | §2.4 |

## Consequences

- A reader starting here needs no MCUHome document and no chat log to
  know what exists — but every claim names its source, so the
  authoritative text is one link away and this record can be audited
  against it.
- The bucket marking is the load-bearing part. A future contributor who
  implements something from §2.5 or §2.7 as though it were decided has
  misread this document, and the buckets are what make that a
  misreading rather than an honest mistake.
- This is a **living draft** in the strongest sense: it is correct only
  as long as its sources say what it says they say, and one of its
  sources is a chat export that exists in no repository. As real
  MCUScript ADRs get written, the corresponding sections here shrink to
  citations.
- §4 is a bill MCUHome has not seen. It should be read there, not only
  here.
