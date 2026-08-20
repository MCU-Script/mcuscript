# AGENTS.md — MCUScript

Guide for AI coding agents (and new human contributors) working in this
repository.

## What this project is

MCUScript is a small scripting language for microcontrollers:
statically typed, compiled on a host to a compact bytecode for a tiny
on-device VM, and transpilable to plain C to be built into the firmware
instead — one source, two backends, identical behaviour, and **every
program expressible both ways**. It is a **standalone project** in its
own organization,
[`mcu-script`](https://github.com/mcu-script), with its own ADR
sequence, release cadence, copyright line and domain
(`mcuscript.org`), developed independently of any embedder's schedule.
[MCUHome](https://github.com/mcu-home/mcuhome) is its first and
reference embedder, not its owner — do not let its requirements read as
governance.

**The back end exists; the front end has begun.** The container
format, the verifier, the VM and the C backend are written and tested,
and every instruction the specification defines works in both backends —
including the four the surface syntax needed, added on 2026-08-19
(ADR 0010): boolean `and`/`or`, which do not short-circuit, and
`const.unavailable`/`const.invalid`, the only way a program states a
validity state rather than causing one.

**There is a compiler.** The surface syntax is `spec/06-syntax.md`
(ADR 0009) and the whole front end exists: `lexer.py`, `parser.py`,
`sema.py` and `codegen.py`, so `mcuscript build <file>` turns a script
into a container and the differential tests run *scripts* through both
backends and compare the bytes. The assembler stays — it is how a test
writes a container the compiler would never emit.

**A compiler can be given a world.** `spec/07-profiles.md` (ADR 0013)
fixes the form of the two documents an integrator supplies — a
**profile**, which declares the dimensions, and a **registry**, which
declares what a script may reach — and `world.py` reads them. Both
arrive as a path and nothing else: `--profile` / `MCUSCRIPT_PROFILE`,
`--registry` / `MCUSCRIPT_REGISTRY`, no search order and no default
location. With neither, a compilation runs against a world that declares
nothing, which is legal (§6.5.4) and makes every suffix and every host
name an error naming itself. The content of both documents belongs to
the integrator; the specification fixes not one dimension of it.

Chapter 6 marks every construct **built**, **planned** or **excluded**.
"Built" there means *this is what M3 implements*; today that means the
parser accepts it, not that anything runs it.

There used to be **two** verifiers, one of them in the C runtime. It was
removed on 2026-08-18 (ADR 0006). The runtime parses, links and runs; it
does not judge. Do not add a check back to it without reading that ADR
first — "the loader should really catch this" is the exact reasoning it
argues against.

So the split to keep in mind is: everything below the container is
**decided and executed**; the surface syntax is **decided and not
executed**; the form of a profile and a registry is **decided and
read**; and the rest above the container — what a real profile says, how
an embedding works — is still a *proposal*. Before writing anything in the last
of those, read
[docs/adr/draft/0002-inherited-context.md](docs/adr/draft/0002-inherited-context.md)
— it marks every item as **decided**, **recorded direction** or **on
the table**, and implementing something from the third bucket as though
it were settled is the specific failure mode this repository is set up
to prevent.

## Repository map

| Path | Role |
|---|---|
| `spec/` | **The specification** — the contract every implementation answers to. Its own version number, and deliberately its own top-level directory so it can be split into `mcu-script/spec` in one cut if a second implementation ever justifies it. `spec/corpus/` is part of it: containers with the verdict each must get, committed as bytes and regenerated with `python tools/build_corpus.py` (ADR 0005) |
| `tools/` | The **host toolchain**, Python: container reader/writer, assembler, verifier, C backend, the compiler (`diagnostics.py`, `lexer.py`, `ast.py`, `parser.py`, `profile.py`, `registry.py`, `sema.py`, `codegen.py`) and the world it is given (`world.py`, `hostheader.py`) |
| `runtime/` | The **device runtime**, C99: loader, verifier, VM. No dependencies, never allocates |
| `docs/adr/` | Architecture decision records — living drafts in `draft/`, immutable finals at the top level once something real exists |
| `.github/` | CI, issue templates, CODEOWNERS |

The specification came first on purpose, and the implementation is
being built from it rather than beside it: the verifier is written from
chapter 2, the tables from chapter 4, and where the two disagree the
**specification is corrected**, in place, in the same commit. Writing
the first thousand lines of code already produced eight such
corrections. A specification nobody implements is a specification
nobody has checked.

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

- **Two backends, one behaviour.** Every program must be expressible
  as bytecode *and* as C, and the two must produce bit-identical
  results, held to it by differential tests. A construct only one
  backend can express is a bug, not a feature. Any construct whose two
  lowerings could diverge — integer overflow, float rounding, division
  by zero, recursion depth — is a language problem, not a backend
  detail. The semantics follow C (`int32_t` wraparound, IEEE-754), so
  the VM is the side that conforms.
- **No GC, and ideally no heap.** Value semantics, statically
  dimensioned buffers. This is what makes the language linkable into a
  battery device.
- **The compiler computes what the VM would otherwise check.** Maximum
  stack depth, worst-case call depth, exhaustiveness. That only works
  while the language stays statically analyzable — which is also why
  recursion is **capped at a small fixed depth** rather than either
  forbidden or left open: bounded recursion keeps the worst case
  computable (frame size × cap) and keeps both backends able to honour
  the same number.
- **Three contracts, not one promise** (ADR 0006). The reference
  compiler emits conforming containers; the reference runtime executes
  conforming containers as specified and is **undefined on anything
  else**; getting an artifact from one to the other unaltered is the
  embedder's concern. This replaced *"bytecode is untrusted input, a
  pushed script must never crash a node"* on 2026-08-17, and the reason
  is the bullet above: a guarantee that holds on the bytecode path and
  cannot hold on the transpiled-C path is not half a guarantee, it is an
  invitation to read the language as safe when it is not. **Do not
  reintroduce a device-side verifier**, and do not write text that
  implies one. A verifier is a defined, optional component (spec
  §2.6.0), and `spec/corpus/` is what one is checked against.
  What the loader still does is check **identity, never
  well-formedness**: magic, format version, profile pin, group mask, CRC
  — is this container meant for me, not is it any good.
- **Compilation happens on the host.** The embedder's builder is always
  in the loop, so a device-side parser buys nothing.
- **Units are compile-time only.** At runtime, in both backends, there
  are bare integers. A base unit is part of the ABI: changing one makes
  every existing artifact silently wrong, which is why the profile is
  versioned and pinned in the bytecode header.

## Coding standards

Two languages, and the boundary between them is a rule rather than a
habit: **anything that runs on a device is C; anything that runs on a
developer's machine is Python.** A host tool may allocate, may take a
second and may say a paragraph about what went wrong. A device runtime
may do none of those.

**Python (`tools/`)** — ruff for both linting and formatting, 88
columns, configured in `tools/pyproject.toml`. The distribution has
**no runtime dependencies** and that is a rule, not a coincidence: this
is the reference implementation of a specification, and a reader
reproducing it should not have to reproduce a dependency tree first.
Type annotations everywhere, `from __future__ import annotations` at the
top of every module. The floor is Python 3.11 and CI tests both ends of
the supported range.

**C (`runtime/`)** — C99, freestanding, no allocation, no libc beyond
`<string.h>`; warnings are errors.

Common to both:

- `.editorconfig` holds the whitespace rules.
- `pre-commit run --all-files` is the whole gate (whitespace, YAML,
  TOML, codespell, REUSE, ruff, Conventional Commits). CI runs the same
  thing plus the test suites.
- Run the tests from the repository's own `.venv`, never a system
  Python.
- Everything in this repository is English, including documents that
  started as a German conversation with the product owner.

**The opcode table lives in exactly one place** —
`tools/src/mcuscript/opcodes.py` — and the C runtime's header is checked
against it by a test. Adding an instruction in one and not the other is
the drift this project cannot afford, because the two backends' agreeing
is the whole promise.

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
