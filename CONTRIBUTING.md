# Contributing to MCUScript

Thank you for considering a contribution! Please read this short section
first, because it changes what a useful contribution looks like here.

## The state of this project

**Nothing is implemented, and the project may not be built at all.**
MCUScript is a scripting language for microcontrollers that
[MCUHome](https://github.com/mcu-home/mcuhome) has designed the
requirements for but not yet decided to build: adopting
[Berry](https://github.com/berry-lang/berry) instead is a live option,
to be settled by a measured prototype. The reasoning, with citations, is
in [docs/adr/draft/0002-inherited-context.md](docs/adr/draft/0002-inherited-context.md).

So the most valuable contributions right now are **not code**:

- review and discussion of the
  [architecture decision records](docs/adr/), especially the ten open
  questions in ADR 0002 §10;
- experience reports from embedding Berry, Lua, MicroPython or a
  hand-rolled VM on a microcontroller — measured numbers most of all;
- prior art we have missed.

A pull request implementing a parser is likely to be closed, not
because it is bad but because the language it parses has not been
decided.

## Development environment

There is nothing to build. The only gate is
[pre-commit](https://pre-commit.com/):

```sh
git clone https://github.com/mcu-home/mcuscript
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

Use the [issue forms](https://github.com/mcu-home/mcuscript/issues/new/choose).
Security vulnerabilities go through [SECURITY.md](SECURITY.md), never public
issues.

## Code of Conduct

This project follows the [Contributor Covenant 3.0](CODE_OF_CONDUCT.md).
