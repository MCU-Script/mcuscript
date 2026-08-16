# The conformance corpus

Containers, and the verdict a conforming loader must give each of them.

This directory belongs to the specification rather than to any
implementation. If you are writing a loader from
[the document](../README.md), this is how you find out where you and it
disagree — run every container past your loader and compare.

## What is here

| File | |
|---|---|
| `corpus.toml` | the manifest: one entry per container, with its expected verdict |
| `*.mcs` | the containers |
| `*.host` | host descriptions, for the cases that need a registry |

Every container is compiled against **profile 1, version 0.0**. Present
a different one and every case is `profile_mismatch` and nothing else
gets tested.

## The manifest

```toml
[[case]]
name = "backward-branch"
file = "backward-branch.mcs"
stage = "verification"
refusal = "backward_branch"
description = "A jump to itself. …"
```

`refusal` is the name from §4.6 a loader must report, or `""` when the
container must be **accepted**. `host`, when present, names the registry
the container is to be resolved against; when absent, the registry is
empty.

`stage` says *which part of a loader owes the verdict*, and it is the
§4.6 heading the refusal is listed under:

| Stage | |
|---|---|
| `ok` | must be accepted |
| `container` | the bytes are wrong — header, sections, tables |
| `compatibility` | well-formed, but not for this implementation or this profile |
| `verification` | the code, or a table contradicting itself (§2.6) |
| `linking` | the container contradicts the **registry** (§4.5) |

The distinction that matters is the last one. A host toolchain has no
registry — resolving names against one is the embedder's job, at load —
so **a tool that only verifies must accept every `linking` case**, and
only a full loader refuses it. Two names, `kind_mismatch` and
`access_denied`, appear at both stages, because a container can
contradict itself about an import as well as contradict the registry.

## Running it

Any loader, any language. The shape is:

```
for each case in corpus.toml:
    load(read(case.file), registry_from(case.host))
    the outcome must be case.refusal, or acceptance when it is empty
```

In this repository both implementations are run against it by
`tools/tests/test_corpus.py` — the Python verifier and the C runtime,
which is the whole reason the corpus exists. They use different
algorithms on purpose (a worklist against a single forward pass,
Tarjan's algorithm against a reachability matrix), and two methods over
one specification are only worth having if something asks them the same
question.

## Why the bytes are committed

Because a corpus each implementation assembles for itself is not
evidence: an implementation that agrees with itself about what it wrote
has demonstrated nothing. These files are bytes, they are in git, and
they are the same bytes for everybody.

They are produced by `tools/src/mcuscript/corpus.py` and regenerated
with `python tools/build_corpus.py`; a test fails if what is committed
is no longer what those definitions produce. So the container format
cannot change quietly — it changes as a diff in this directory, which
is where a reviewer would want to see it.

## Completeness

**Every refusal §4.6 names has at least one container here**, and a test
enforces it in both directions. That is a stronger property than it
sounds: a name no container can produce is a name nobody has checked,
and writing this corpus found one. `import_limit` was in the
specification, and neither implementation had ever raised it — because
the two things it could have meant were `unknown_import` and "this build
is too small", and the second deliberately has no name in a conformance
taxonomy. It refuses a container the specification calls well-formed,
which is the one thing a conforming implementation may not do.

What is **not** here is coverage of accepted behaviour: four containers
must load, and what they then compute is the differential test's
business, not this one's. The corpus is about verdicts.
