<!--
SPDX-FileCopyrightText: 2026 The MCUHome Contributors
SPDX-License-Identifier: Apache-2.0
-->

# 0002 — Inherited context: what is already decided, and where it is written down

- Status: draft
- Date: 2026-08-16

## Context

MCUScript is a new repository for an old idea. Between 2026-08-03 and
2026-08-16, while MCUHome was designed and built, decisions about
scripting were taken and written down — never in one place, because
there was no such place. They sit in one design document, five ADRs, a
validation gate, a C header, a glossary and a roadmap entry, spread
over two repositories.

Anyone starting work here needs to know all of them, because several
are load-bearing constraints on the language itself (no heap in the
expression tier, static analyzability, a bytecode a device must not be
crashable by) and several are *not* constraints at all but merely
MCUHome's current guesses. Rediscovering that distinction from scratch
is how a project accidentally re-decides something the product owner
already settled — or, worse, treats a guess as settled.

## Decision

This ADR is a **reference record**. It decides nothing new: it collects
what is already decided, cites the document that owns each item, and
separates what binds MCUScript from what only describes MCUHome's
intent. Every claim below is traceable to a source; where a source is a
living draft, it may move, and this record is then wrong and gets
rewritten.

Sources are cited by repository and path:

| Short form | Document |
|---|---|
| `component-model.md` | [mcuhome-sdk `docs/design/component-model.md`](https://github.com/mcu-home/mcuhome-sdk/blob/main/docs/design/component-model.md) |
| `yaml-schema.md` | [mcuhome-sdk `docs/design/yaml-schema.md`](https://github.com/mcu-home/mcuhome-sdk/blob/main/docs/design/yaml-schema.md) |
| `builder-pipeline.md` | [mcuhome-sdk `docs/design/builder-pipeline.md`](https://github.com/mcu-home/mcuhome-sdk/blob/main/docs/design/builder-pipeline.md) |
| `channel.h` | [mcuhome-sdk `include/mcuhome/channel.h`](https://github.com/mcu-home/mcuhome-sdk/blob/main/include/mcuhome/channel.h) |
| mcuhome-sdk ADR 0009/0010/0014 | Matter-explicit YAML schema / Matter-only, CoAP deferred / generated-tables contract |
| mcuhome-sdk draft ADR 0015 | Update and partition architecture |
| mcuhome ADR 0019, 0020 | Session build protocol / package layout |
| `ROADMAP.md`, `GLOSSAR.md` | MCUHome workspace documents, untracked, product-owner-facing |

---

## 1. The one real design source: `component-model.md` §10

§10 ("Future direction: filters, scripting, and the DEV/LIVE split") is
product-owner direction of **2026-08-07** and is the origin of this
project. Its own framing: *"Not v0.x scope — recorded here so nothing
built before the automation phase closes a door on it. The formal
decision is an ADR at the start of that phase, backed by a measured
prototype."*

### 1.1 The principle: a script is never the data path

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

### 1.2 Three tiers, cheapest one wins

The builder picks the cheapest tier that covers the configuration:

1. **Predefined filters** (`offset`, `range`, later moving average,
   deadband, …) — declarative registry entries. *Everything stateful
   lives here*, with its state owned by the C framework.
2. **Expressions** — deliberately more than arithmetic (product-owner
   scope call, 2026-08-07: *"end users should normally not need
   tier 3"*). Named as in scope: variables, the ternary conditional,
   null coalescing (which *"pairs naturally with the nullable 'sensor
   not ready yet' semantics of the attribute stores"*), and read-only
   value access to other channels through a fixed method surface. The
   worked example given:

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
   For genuinely complex processing (the example given: an AMG8833 8×8
   thermal grid) the engine's footprint is *"a fair price"* — though
   known-complex sensors can also land as C components, shrinking how
   often tier 3 is needed at all.

### 1.3 The two candidate tracks (this is the open question)

Decided by *"the automation-phase ADR"*, backed by a measured
prototype:

**Track A — adopt an existing engine.**

| Candidate | Verdict as recorded |
|---|---|
| **Berry** | First choice. MIT, MCU-native, Tasmota precedent |
| **Lua** | Second choice |
| Toit | Evaluated and behind: LGPL VM, ESP-IDF-bound |
| Wren | Evaluated and behind: dormant since 0.4.0, double-precision-only numbers on single-precision-FPU targets |

**Track B — grow our own** from the tier-2 core. A product-owner wish,
*"to be evaluated honestly"*. Five elements, all named:

- **one language** whose grammar's expression subset *is* tier 2;
- **host-side compilation** to a compact bytecode — *"the builder is
  always in the loop, unlike Tasmota's on-device console — a
  device-side parser buys us nothing"* — so the MCU carries only a
  bytecode VM;
- the **VM assembled from feature modules** (arithmetic, functions,
  classes, …) so an expression-only device links an expression-only VM;
- the language kept **statically analyzable enough that LIVE mode can
  transpile scripts to C** instead of shipping the VM;
- each element is *individually proven prior art* — Lua `luac`,
  MicroPython `.mpy`, Berry solidification; trimmed-library builds;
  DSL-to-C transpilers.

The risk is stated precisely, and it is not a technical one:
*"the risk is not buildability but a decade of ownership: first-class
diagnostics, documentation, a bytecode verifier (pushed bytecode must
never crash a node), and format stability across firmware versions."*
**Berry remains the safety net if this track stalls.**

### 1.4 The decisions that created this repository

Product-owner decision, 2026-08-07, quoted in full because it is this
repository's charter:

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

Two consequences of that paragraph are already resolved and one is not:

- **The repository exists** (2026-08-16) — this one.
- **The license is Apache-2.0** (product owner, 2026-08-16), closing
  the "deliberately left open" question at the moment the design
  intended: project creation. Consistency with mcuhome ADR 0003 and the
  explicit patent grant beat the MIT adoption argument (Berry, Lua,
  Wren and MicroPython are all MIT; Apache-2.0 is not GPLv2-compatible,
  which is the price paid).
- **Whether the engine is built at all** is *not* resolved. This
  repository existing is not the choice of track B — see §7.

### 1.5 The DEV/LIVE split

Not MCUScript's mechanism, but the reason several language constraints
exist, so it is recorded here in full:

- A freshly set-up device runs in **DEV** mode: YAML filters are
  lowered to *script* and pushed **without recompiling** — *"config
  iteration lands in seconds"*.
- Once tuned, the user switches to **LIVE**: one full rebuild bakes the
  YAML-defined filters back into **C**, and the engine is linked only
  for what genuinely needs it (hand-written hooks/automations) —
  *"possibly not at all, which is the steady state for battery
  devices"*.
- Both lowerings of a filter primitive come from **one registry
  definition** and are held equivalent by **golden tests** (same input
  series, identical output).
- The builder classifies every config diff as firmware-affecting
  (wiring, drivers, endpoint structure → rebuild + OTA) or script-only
  (filters, automations → push), and the device's mode is part of the
  canonical model *"so a filter is never applied twice (baked **and**
  scripted)"*.

### 1.6 Fixed constraints for the automation phase

Verbatim scope, all of it binding on whatever engine is chosen:

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

---

## 2. Where this sits in the plan

`ROADMAP.md` ("Parallele / spätere Stränge"):

> **Automations-/Scripting-Phase** (nach Phase 4/5): drei Filter-Stufen,
> DEV/LIVE-Split, Engine-Entscheid (Berry vs. eigene Standalone-Engine)
> — Rahmen fixiert in component-model.md §10, ADR mit vermessenem
> Prototyp zu Phasenbeginn.

Phase 4 is the dashboard MVP, phase 5 the component breadth strand;
MCUHome is currently in its CLI phase (2026-08-14 onwards). So the
scripting phase has **not** started, and the "ADR with a measured
prototype" it calls for has not been written. `ROADMAP.md` also points
at §10 from its header as the canonical home of scripting design.

---

## 3. What the YAML schema already reserves

`yaml-schema.md` is product-owner-approved (2026-08-03) and describes a
*"full declarative automation engine"* as a product anchor. Relevant
decisions:

- **§1.3 No embedded code.** *"Configs never contain C/C++ snippets
  (ESPHome lambdas are explicitly rejected). Automations are fully
  declarative YAML (§8); if a device needs real code, that is a custom
  component."* mcuhome-sdk ADR 0009 gives the reason: ESPHome's lambdas
  are C++ against ESPHome's runtime API and are *"unrunnable on
  Zephyr"*, and they are named as *"what cannot be translated"* when
  importing an ESPHome configuration.
- **§8 `automations:`** — the declarative model is fully specified:
  triggers (attribute thresholds with `above`/`below`/`equals` and an
  optional `for:`, `changed:`, `interval:`, `boot:`, a received
  Matter/CoAP command, later button events), conditions (all must hold;
  `any:`/`not:` combinators), actions run sequentially (`command:`,
  `set:`, `delay:`, `log:`, later `scene:`), and references as
  `alias.cluster.attribute` (node view) or `peripheral.channel`
  (hardware view), *"both resolve to the same value plumbing"*.
- **§8, deliberately absent:** *"free-form expressions/templates. v1
  offers comparisons, thresholds and durations only. An expression
  language is the single biggest complexity driver in this space —
  reserved as an explicit extension point (`expression:` key) so adding
  it later is non-breaking."*
- **§8:** automations run on-device and keep working without network —
  with `network:` absent entirely a config *"degrades to a standalone
  automation controller"*. mcuhome-sdk ADR 0010 says the same from the
  other side.
- **§11 open points** lists *"Expression language in automations —
  Reserved extension point"* and *"Cross-device automations
  (bindings) — Reserved schema extension"*.

The single worked example is
[`docs/design/examples/03-co2-alarm-automation.yaml`](https://github.com/mcu-home/mcuhome-sdk/blob/main/docs/design/examples/03-co2-alarm-automation.yaml)
— a CO₂ guard with `above: 1200` `for: 2min` → LED, `above: 2000` →
LED + buzzer + `delay: 5s` + buzzer off, `below: 900` `for: 5min` →
clear. It is the most concrete statement of what tier 3 must be able to
express, and it is *declarative YAML*, not script.

---

## 4. What the builder pipeline already says

`builder-pipeline.md` §3: stage 4 emits `mcuhome_config.c/.h`
described as *"endpoint/cluster/automation tables"*, and:

> Automations compile to a compact static table (triggers, conditions,
> actions as data) interpreted by a small runtime engine — **no
> generated C control flow**.

This predates §10 and describes the *declarative* engine, not a
scripting VM. It matters here as a data point about intended shape: the
project's instinct has consistently been *data plus a small
interpreter*, never emitted control flow — with LIVE-mode
transpile-to-C (§1.5) as the deliberate exception.

---

## 5. What the firmware contracts already fix

**mcuhome-sdk ADR 0014 (generated tables contract, final).** *"Future
automation tables (out of scope for contract v1, see Consequences)
follow the same pattern: one generated file per device, one symbol set
per contract domain."* And in Consequences: *"Automation tables and
actuator write-path semantics are explicitly out of scope for contract
v1 — both remain open points in component-model.md §9 and get their own
tables/version bump later."* So a scripting engine's generated data
gets **its own symbol set and its own contract version**, and does not
extend the Matter tables.

**`channel.h` (contract v1, hardware-verified).** The channel layer's
scope is *"deliberately narrow"* and names its exclusions:

> Periodic sampling, report-on-delta. **No triggers, no filters, no
> averaging.**

and, about the generated binding structs:

> THIS HEADER IS DUMB DATA ON PURPOSE. […] Every field must therefore
> be something a YAML-driven generator can compute without embedding
> logic: constants, IDs, and integer scale factors — **never
> expressions, never code.** Keep it that way.

Also fixed there: scale/offset conversion into Matter raw units happens
in the sensor binding (`raw = round(micro * scale_num / (scale_den *
1e6)) + offset`), which is the mechanism behind §1.6's *"scripts work
in user units"*. Runtime state lives in the poller's Kconfig-sized
static pool, not in the generated arrays, so those stay `const` and
stay in flash — the same discipline a VM's generated data will be held
to.

---

## 6. What flash and transport already reserve

**mcuhome-sdk draft ADR 0015 (update and partition architecture).**
A **script/data area is already reserved** in every layout table,
citing component-model.md §10:

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
  — that format is MCUScript's bytecode container, and it is an open
  question this project inherits.

Same ADR, on transport: a transfer protocol of MCUHome's own (CoAP over
Thread, which OpenThread already provides) is deferred to the
maintenance channel mcuhome-sdk ADR 0010 reserved, *"where it belongs
together with script push and diagnostics — one channel, designed
once"*. Note recorded for that design: MCUboot's signature is the only
payload trust anchor in the existing path.

The Matter settings partition (fabric credentials, Thread dataset) is
preserved across updates in every layout — *"which is what makes an
update not a re-commissioning"*. A script push must not disturb it.

Also relevant, from the phase-3 idea list in `ROADMAP.md` (explicitly
non-binding product-owner thinking, 2026-08-07): *"Skripte ggf. als
eigene (vierte) Partition mit eigenem Image"* — an idea that draft ADR
0015 has since answered in the other direction (not image-framed).

---

## 7. What this repository's existence does *not* mean

Three disambiguations, each of which would otherwise be a plausible
misreading:

1. **The engine decision is open.** Track A (adopt Berry) versus
   track B (grow our own) is decided by the automation-phase ADR
   *backed by a measured prototype*, and that ADR does not exist. This
   repository is where track B would live if it is chosen, and where
   the measurement that decides it can be done without polluting
   MCUHome. Berry remains the recorded safety net.
2. **"DEV mode" in the build protocol is a different thing.** mcuhome
   ADR 0019 uses `clean`/`incremental` build modes and notes: *"the
   script 'DEV mode' this originally anticipated was overtaken by
   ADR 0020's build methods"*. That is about warm build workspaces, not
   about §1.5's DEV/LIVE device modes. The names collide; the concepts
   do not touch.
3. **Tier 1 filters are not scripting.** Predefined filters with
   C-owned state are a component-registry feature of MCUHome and stay
   there even if MCUScript never exists.

---

## 8. The state of the code today

`automations:` is parsed and refused, on purpose:

- [`mcuhome/workbench/schema.py`](https://github.com/mcu-home/mcuhome/blob/main/mcuhome/workbench/schema.py)
  has a `RawAutomation` that reads exactly one field (`id`), and
  `automations` is one of the five allowed top-level keys;
- [`mcuhome/workbench/validate.py`](https://github.com/mcu-home/mcuhome/blob/main/mcuhome/workbench/validate.py)
  gates it in `_check_scope_gates`: *`"automations:" is not implemented
  yet.`* with the hint *"the automation engine is designed but not
  built yet — remove the automations: section for now"*;
- [`mcuhome/workbench/configschema.py`](https://github.com/mcu-home/mcuhome/blob/main/mcuhome/workbench/configschema.py)
  publishes it in the JSON schema as *"Automations. Not implemented in
  v0.1."*;
- `tests_py/test_validate.py` and `tests_py/test_examples.py` pin that
  refusal, the latter against the CO₂ example of §3.

There is **no** filter, expression or script code anywhere in any
MCUHome repository. The word "expression" appears in the C sources only
as a prohibition (§5).

---

## 9. Vocabulary already fixed for the product owner

`GLOSSAR.md` (German, workspace-level, untracked) already carries the
terms this project will use, and its definitions are the product
owner's mental model:

- **VM** — *"der Interpreter-Kern einer Skriptsprache (MicroPython,
  Lua, Berry), der Skript-Code auf dem Chip ausführt"*;
- **GC** — *"Kostet RAM-Reserve und kurze Pausen; auf MCUs der
  Hauptgrund, warum Skript-Engines mehr RAM brauchen als ihr Grundbedarf
  vermuten lässt"*;
- **Berry** — *"Kleine Skriptsprache speziell für MCUs (Kern < 40 KB
  Flash). Tasmota nutzt sie als Automations-Sprache auf ESP32 — der
  wichtigste Praxis-Präzedenzfall in unserem Umfeld"*;
- **WASM** — evaluated and rejected for this purpose: *"Nutzer bräuchten
  aber eine Compiler-Toolchain — für Endanwender-Automationen daher
  unpraktisch"*.

New MCUScript terminology gets added there when it is introduced.

---

## 10. Open questions this project inherits

None of these is answered anywhere, and each one is a real fork in the
road:

| # | Question | Where it came from |
|---|---|---|
| 1 | Adopt Berry, or build MCUScript? Decided by a *measured* prototype | §1.3 |
| 2 | What is measured, and against what budget? No flash/RAM number has ever been stated for the engine on any target | §1.3, `ROADMAP.md` |
| 3 | Syntax. §10 names semantics (ternary, null coalescing, method calls) but no grammar, and Symfony's ExpressionLanguage is a scope marker, not a syntax decision | §1.2 |
| 4 | The bytecode container format — the thing draft ADR 0015 reserved a flash region for without a format | §6 |
| 5 | The bytecode verifier: *"pushed bytecode must never crash a node"* — verify on device, sign on host, or both? | §1.3, §1.6 |
| 6 | Bytecode/binding-API version handshake, mirroring `tables_version` | §1.6 |
| 7 | The C API toward embedders — the thing that makes this standalone rather than a subdirectory | §1.4 |
| 8 | Numeric model. Wren was rejected partly for double-only numbers on single-precision-FPU targets, which implies integers and/or 32-bit floats matter, but nothing is decided | §1.3 |
| 9 | Host-side compiler implementation language. MCUHome's builder is Python; a compiler usable by non-Python embedders may not be | §1.4 |
| 10 | Whether tier 2 ships first inside MCUHome (as §1.4's *"built with this API discipline from day one"* allows) or immediately here | §1.4 |

## 11. Not yet incorporated

An earlier conversation about this project exists as a claude.ai share
link (product owner, 2026-08-16). Its content could not be read — the
share page renders client-side and its API refuses unauthenticated
reads — so **nothing from it is in this record**. When the content is
available, whatever it decided belongs in §1 or §10 of this document,
or in its own ADR.

## Consequences

- A reader starting here needs to read no MCUHome document to know what
  is already settled — but every claim names the document that owns it,
  so the authoritative text is one link away and this record can be
  audited against it.
- This document is a **living draft** in the strongest sense: it is
  correct only as long as its sources say what it says they say. When
  the automation-phase ADR is written, most of §1 stops being inherited
  context and becomes a real MCUScript decision — at which point those
  sections shrink to citations.
- The distinction that matters most is §7: nothing here commits MCUHome
  to building its own engine.
