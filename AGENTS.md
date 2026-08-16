# AGENTS.md — MCUScript

Guide for AI coding agents (and new human contributors) working in this
repository.

## What this project is

MCUScript is a small scripting language for microcontrollers:
statically typed, compiled on a host to a compact bytecode for a tiny
on-device VM, and *optionally* transpiled to plain C and built into the
firmware instead — one source, two backends, identical behaviour. It is
a **standalone project** in its own organization
(`mcuscript-lang`); [MCUHome](https://github.com/mcu-home/mcuhome) is
its first and reference embedder, not its owner.

**Nothing is implemented.** No language, no compiler, no VM, no C API.
Most of what is written down is a *proposal*, not a decision. Before
writing anything, read
[docs/adr/draft/0002-inherited-context.md](docs/adr/draft/0002-inherited-context.md)
— it marks every item as **decided**, **recorded direction** or **on
the table**, and implementing something from the third bucket as though
it were settled is the specific failure mode this repository is set up
to prevent.

## Repository map

| Path | Role |
|---|---|
| `docs/adr/` | Architecture decision records — living drafts in `draft/`, immutable finals at the top level once something real exists |
| `.github/` | CI, issue templates, CODEOWNERS |

That is the whole repository. Source directories are deliberately
absent: the host compiler's implementation language is an open question
(ADR 0002 §8), and an empty `src/` would answer it by accident.

## Where the decisions live: three layers

ADR 0001's boundary rule. Getting this wrong is the easiest mistake to
make while MCUHome is the only embedder.

- **The language — here.** Grammar, type system, the unit *mechanism*,
  the bytecode container and its verifier, the VM and its feature
  modules, the C API toward embedders, diagnostics, this project's
  versioning.
- **A profile — its own repository.** Which dimensions exist, how units
  are spelled, which base unit each normalizes to, the value ranges an
  embedder's actuators expect. `°C` and `lux` are *not* MCUScript
  vocabulary.
- **An embedding — the embedder's repository.** Which configuration
  lowers to script, how a script reaches a device, which flash region
  holds it, when the device rebuilds instead of accepting a push, what
  the entity registry contains. Those decisions are cited in ADR 0002,
  never copied.

The test: *would this decision still have to be made if the only
embedder were somebody else's project?*

ADRs are draft-first
([mcuhome ADR 0021](https://github.com/mcu-home/mcuhome/blob/main/docs/adr/0021-draft-first-adr-lifecycle.md),
adopted, not inherited): a draft is a **living document** — improve the
text, never append amendment or erratum sections; git history is the
changelog. Foreign ADR numbers are always prefixed (`mcuhome ADR 0014`,
`mcuhome-sdk ADR 0015`) because this repository has its own sequence.

## Load-bearing constraints

These are constraints on the language, not implementation preferences.
Sources and status in ADR 0002.

- **Two backends, one behaviour.** Bytecode and generated C must
  produce bit-identical results, held to it by differential tests. Any
  construct whose two lowerings could diverge — integer overflow, float
  rounding, division by zero, recursion depth — is a language problem,
  not a backend detail. The semantics follow C (`int32_t` wraparound,
  IEEE-754), so the VM is the side that conforms.
- **No GC, and ideally no heap.** Value semantics, statically
  dimensioned buffers. This is what makes the language linkable into a
  battery device.
- **The compiler computes what the VM would otherwise check.** Maximum
  stack depth, call-graph acyclicity, exhaustiveness. That only works
  while the language stays statically analyzable — and it is also why
  recursion is excluded.
- **Bytecode is untrusted input.** A pushed script must never crash a
  node: a load-time verifier recomputes what the compiler claimed
  rather than trusting the header, and a profile mismatch is a refusal
  rather than arithmetic on wrongly scaled numbers.
- **Compilation happens on the host.** The embedder's builder is always
  in the loop, so a device-side parser buys nothing.
- **Units are compile-time only.** At runtime, in both backends, there
  are bare integers. A base unit is part of the ABI: changing one makes
  every existing artifact silently wrong, which is why the profile is
  versioned and pinned in the bytecode header.

## Coding standards

The implementation language is undecided, so there are no
language-specific rules yet — add them here in the same commit that
introduces the first source file, together with the matching
`.pre-commit-config.yaml` hook and CI gate.

Until then:

- `.editorconfig` holds the whitespace rules.
- `pre-commit run --all-files` is the whole gate (whitespace, YAML,
  TOML, codespell, REUSE, Conventional Commits). CI runs the same
  thing.
- Everything in this repository is English, including documents that
  started as a German conversation with the product owner.

## Licensing rules (strict)

- Everything is **Apache-2.0** (ADR 0003). Every new file gets SPDX
  headers (a `SPDX-FileCopyrightText` line naming **The MCUScript
  Contributors** — never "The MCUHome Contributors" — and an
  `Apache-2.0` identifier); Markdown files are covered by `REUSE.toml`'s
  fallback annotation and need no inline header. The repository is
  REUSE-compliant (`reuse lint` runs in pre-commit).
- **Never copy code from GPL projects.** Sharper here than in most
  projects: a scripting engine is exactly where reading another
  implementation is tempting. Berry, Lua, Wren and MicroPython are MIT,
  so their code is *license*-compatible with Apache-2.0 — but copied
  code still needs its own license file, its own `REUSE.toml`
  annotation and a recorded decision. Do not do it silently.

## Commit and PR conventions

- Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`, …).
- Every commit is DCO-signed-off: `git commit -s`.
- Default branch is `main`; short-lived `feat/…`, `fix/…` branches.
- Non-trivial design decisions require an ADR **draft** in
  `docs/adr/draft/` (numbered, MADR-style: Context / Decision /
  Consequences). Given the state of this project, that is nearly every
  change.
