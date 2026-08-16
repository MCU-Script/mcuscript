# Contributing to MCUScript

Thank you for considering a contribution! Please read this short section
first, because it changes what a useful contribution looks like here.

## The state of this project

**Nothing is implemented, and most of what is written down is a
proposal rather than a decision.** The requirements are settled — always
compiled to bytecode, always transpilable to C as the alternative,
modular — and so are
the name, the organization and the license. The language is not: there
is no grammar, no bytecode specification and no C API, and
[ADR 0002](docs/adr/draft/0002-inherited-context.md) marks every item as
**decided**, **recorded direction** or **on the table** precisely so
that nobody implements the third kind by accident.

So the most valuable contributions right now are **not code**:

- review and discussion of the
  [architecture decision records](docs/adr/), especially the open
  questions in [ADR 0002 §8](docs/adr/draft/0002-inherited-context.md);
- experience reports from embedding a small VM on a microcontroller —
  Berry, Lua, MicroPython, Pawn, wasm3, or something hand-rolled — and
  **measured** flash/RAM numbers most of all, because this project has
  none;
- prior art we have missed. The claim that nothing combines "one
  source, both a bytecode VM *and* a C backend, statically typed,
  MCU-sized" survived a search but was not proved, and a counterexample
  would be genuinely valuable. The closest found so far are Cyber
  (both backends, wrong audience) and WAMR with wasm2c (both backends,
  but the source is WebAssembly).

A pull request implementing a parser is likely to be closed — not
because it is bad, but because the language it parses has not been
decided.

## Development environment

There is nothing to build. The only gate is
[pre-commit](https://pre-commit.com/):

```sh
git clone https://github.com/mcu-script/mcuscript
cd mcuscript
python3 -m venv .venv && . .venv/bin/activate
pip install pre-commit
pre-commit install --install-hooks
pre-commit install --hook-type commit-msg
pre-commit run --all-files
```

The venv holds the lint tooling only — it says nothing about the
implementation language, which is an open question.

## Coding standards

- **Licensing:** every new file needs SPDX headers (a
  `SPDX-FileCopyrightText` line and an `Apache-2.0` license identifier —
  copy them from any existing file; Markdown files are covered by
  `REUSE.toml`'s fallback annotation and need no inline header).
- **Never copy code from GPL-licensed projects.** Sharper here than in
  most projects: reading another scripting engine's implementation is
  tempting. Even MIT-licensed code (Berry, Lua, MicroPython) may not be
  copied in silently — it needs its own license file, its own
  `REUSE.toml` annotation and a recorded decision.
- Language-specific rules arrive with the first source file.

## Commit and PR rules

- **Conventional Commits:** `feat: …`, `fix: …`, `docs: …`, `chore: …` etc.
- **DCO sign-off:** every commit must be signed off (`git commit -s`),
  certifying the [Developer Certificate of Origin](https://developercertificate.org/).
  We use DCO instead of a CLA.
- Keep PRs focused; one logical change per PR.
- Non-trivial design decisions need an ADR draft in
  [docs/adr/draft/](docs/adr/draft/) — propose it in the PR. Drafts are
  living documents; the final ADR is written from the real result once
  the component is done ([docs/adr/README.md](docs/adr/README.md)).
  Decisions about how MCUHome *uses* an engine belong in the MCUHome
  repositories instead (ADR 0001's boundary rule).

## Reporting issues

Use the [issue forms](https://github.com/mcu-script/mcuscript/issues/new/choose).
Security vulnerabilities go through [SECURITY.md](SECURITY.md), never public
issues.

## Code of Conduct

This project follows the [Contributor Covenant 3.0](CODE_OF_CONDUCT.md).
