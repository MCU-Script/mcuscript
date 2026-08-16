<!--
SPDX-FileCopyrightText: 2026 The MCUScript Contributors
SPDX-License-Identifier: Apache-2.0
-->

# 0005 — The conformance corpus

- Status: draft — written, populated and running against both loaders.
- Date: 2026-08-16

## Context

This project deliberately has two of almost everything: two verifiers,
two lowerings, two ways of condensing a call graph. ADR 0004 explains
why, and the differential test holds the two *backends* to one
behaviour. Nothing held the two **loaders** to one verdict.

They were tested separately, and separately is the problem. The host
verifier had its expectations in `test_verify.py`, the runtime had its
own in `test_runtime.py`, and each was written by whoever was writing
that side at the time. A container the one accepts and the other refuses
was not a test failure anywhere — which is precisely the divergence the
two-implementation strategy exists to catch, and precisely what it was
not catching.

## Decision

A corpus of containers with an expected verdict each, in
[`spec/corpus/`](../../../spec/corpus/), run against both.

### 5.1 It is bytes, and the bytes are committed

Not a list of programs each implementation assembles for itself. An
implementation that agrees with itself about what it wrote has
demonstrated nothing; what is needed is that both see the *same* bytes,
and the cheapest way to guarantee that is for the bytes to be a file.

It also buys the third-party case, which is the point of writing a
specification at all: someone implementing a loader from the document
can clone one directory and find out where they disagree, without
running any of this project's code.

The cost is that a container-format change invalidates the corpus. That
is paid deliberately: the definitions live in
`tools/src/mcuscript/corpus.py`, a test fails when the committed bytes
are no longer what they produce, and regenerating is one command. So a
format change shows up as a diff in `spec/corpus/` — which is where a
reviewer would want to see it, rather than absorbed silently by a
fixture that rebuilds itself.

### 5.2 It lives in the specification, not in the toolchain

`spec/` is kept separable — one cut and it is its own repository — and
the corpus goes with it. Putting it under `tools/` would make it read as
a test fixture of the Python implementation, which is the one thing it
must not be: it is the arbiter *between* the implementations, and it
answers to the document rather than to either of them.

### 5.3 A case says which part of a loader owes the verdict

Each entry carries a `stage`, and the stages are §4.6's own headings:
`container`, `compatibility`, `verification`, `linking`, plus `ok`.

This is not decoration. A host toolchain has no registry — resolving
names against one is the embedder's, at load — so on a `linking` case
the host verifier must **accept** and only a full loader refuses. Any
scheme that did not say so would either exempt the linking cases from
the host side (untested) or expect the host side to produce a verdict it
cannot (wrong).

The stage is checked against the specification's own sectioning, so the
corpus cannot drift from the document about whose job a verdict is.

### 5.4 Every named refusal has a container, and that is enforced

A test asserts the two sets are equal: every refusal §4.6 names appears
in the corpus, and the corpus produces no name the document does not
have.

The forward direction is the valuable one. A refusal that has never been
produced by a real container is not a tested refusal — it is a name in a
table — and this rule found one before the corpus even ran.

## Consequences

- **`import_limit` was deleted from the specification.** It was in §4.6
  and neither implementation had ever raised it. Its two possible
  readings are "the registry does not have the name", which is
  `unknown_import`, and "this build is too small" — and the second
  cannot be in a conformance taxonomy at all, because it refuses a
  container the document calls well-formed, which is the one thing a
  conforming implementation may not do. §4.6 now says that in words, and
  the runtime keeps its own `build_limit` outside the taxonomy where it
  belongs.
- **`kind_mismatch` and `access_denied` are listed twice, on purpose.**
  The corpus's stage rule surfaced it immediately: both were filed under
  linking, and both implementations also produce them during
  verification, from the container's own table, with no registry in
  sight. A container can contradict itself about an import as well as
  contradict the registry. Same mistake, same name, two occasions — and
  the document now states both, because only one of them a host tool can
  see.
- **`duplicate_import` was never a linking error** and has moved to the
  container's own defects, where it can be found by reading one table.
- The two loaders agreed on all thirty-nine cases the first time they
  were asked, which is a pleasant result and not evidence that the
  corpus was unnecessary. It is a regression net now, and the three
  findings above came from *writing* it rather than from running it.

## Open

- **Faults are not covered.** The corpus is about verdicts at load. What
  a container computes once accepted is the differential test's
  business, and whether the three faults of §5.5 deserve the same
  treatment — a corpus of programs with an expected fault — is not
  decided.
- **No implementation outside this repository has run it.** That is the
  test of whether the manifest is really implementation-neutral, and it
  cannot be self-administered.
