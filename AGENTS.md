# AGENTS.md — MCUScript

Guide for AI coding agents (and new human contributors) working in this
repository.

## What this project is

MCUScript is intended to be a small scripting language for
microcontrollers: expressions and automation logic, compiled on a host,
executed by a tiny VM on the device. Its first embedder is
[MCUHome](https://github.com/mcu-home/mcuhome), which turns YAML device
descriptions into Zephyr firmware; being useful to projects that have
never heard of MCUHome is a design goal.

**Nothing is implemented.** There is no language, no compiler, no VM,
no C API — and, most importantly, no decision that MCUScript will be
built at all: adopting [Berry](https://github.com/berry-lang/berry)
instead is a live option with a recorded product-owner rationale. If
you are here to write code, first read
[docs/adr/draft/0002-inherited-context.md](docs/adr/draft/0002-inherited-context.md);
it is short and it will change what you build.

## Repository map

| Path | Role |
|---|---|
| `docs/adr/` | Architecture decision records — living drafts in `draft/`, immutable finals at the top level once something real exists |
| `.github/` | CI, issue templates, CODEOWNERS |

That is the whole repository. Source directories are deliberately
absent: the implementation language is an open question (ADR 0002 §10),
and an empty `src/` would answer it by accident.

## Where the decisions live

- **This repository** owns the language, the compiler, the bytecode and
  its verifier, the VM and its feature modules, the C API toward
  embedders, diagnostics, and this project's versioning
  (ADR 0001 boundary rule).
- **MCUHome** owns everything about *using* an engine: which YAML
  constructs lower to script, how a script reaches a device, which
  flash region holds it, when a device rebuilds instead of pushing.
  Those decisions are cited in ADR 0002, never copied.
- ADRs are draft-first
  ([mcuhome ADR 0021](https://github.com/mcu-home/mcuhome/blob/main/docs/adr/0021-draft-first-adr-lifecycle.md)):
  a draft is a **living document** — improve the text, never append
  amendment or erratum sections; git history is the changelog.
- Foreign ADR numbers are always prefixed (`mcuhome ADR 0014`,
  `mcuhome-sdk ADR 0015`, `cli ADR 0003`) because this repository has
  its own sequence.

## Non-obvious constraints inherited from MCUHome

All of these come from
[component-model.md §10](https://github.com/mcu-home/mcuhome-sdk/blob/main/docs/design/component-model.md)
and are recorded with citations in ADR 0002. They are constraints on
the language, not implementation preferences:

- **The expression tier needs no heap and no GC.** An expression is a
  single side-effect-free value: no statements, no loops, no
  user-defined functions, no state. That is what makes it linkable into
  a battery device.
- **Compilation happens on the host.** The MCUHome builder is always in
  the loop, so a device-side parser buys nothing — the MCU carries a
  bytecode VM, not a compiler.
- **A pushed script must never crash a node.** Staged apply, fallback
  to the last good script, and a bytecode verifier are requirements,
  not features.
- **The language stays statically analyzable enough to transpile to
  C.** MCUHome's LIVE mode bakes scripts into C and links no VM at all;
  a construct that defeats that analysis costs a product feature.
- **Scripts work in user units.** Unit conversion into Matter raw units
  stays in MCUHome's C binding.

## Coding standards

The implementation language is undecided, so there are no
language-specific rules yet — add them here in the same commit that
introduces the first source file, together with the matching
`.pre-commit-config.yaml` hook and CI gate.

Until then:

- `.editorconfig` holds the whitespace rules.
- `pre-commit run --all-files` is the whole gate (whitespace, YAML,
  codespell, REUSE, Conventional Commits). CI runs the same thing.
- Everything in this repository is English, including documents that
  started as a German conversation with the product owner.

## Licensing rules (strict)

- Everything is **Apache-2.0** (product owner, 2026-08-16 — the
  Apache-2.0-vs-MIT question component-model.md §10 left open for
  project creation). Every new file gets SPDX headers (a
  `SPDX-FileCopyrightText` line naming The MCUHome Contributors and an
  `Apache-2.0` identifier); Markdown files are covered by `REUSE.toml`'s
  fallback annotation and need no inline header. The repository is
  REUSE-compliant (`reuse lint` runs in pre-commit).
- **Never copy code from GPL projects.** This is sharper here than
  elsewhere in MCUHome: a scripting engine is exactly the kind of
  component where reading another implementation is tempting. Berry,
  Lua, Wren and MicroPython are MIT, so their code is *license*-
  compatible with Apache-2.0 — but copied code still needs its own
  license file, its own `REUSE.toml` annotation and a recorded decision.
  Do not do it silently.

## Commit and PR conventions

- Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`, …).
- Every commit is DCO-signed-off: `git commit -s`.
- Default branch is `main`; short-lived `feat/…`, `fix/…` branches.
- Non-trivial design decisions require an ADR **draft** in
  `docs/adr/draft/` (numbered, MADR-style: Context / Decision /
  Consequences). Given the state of this project, that is nearly every
  change.
