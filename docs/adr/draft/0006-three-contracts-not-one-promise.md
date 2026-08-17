<!--
SPDX-FileCopyrightText: 2026 The MCUScript Contributors
SPDX-License-Identifier: Apache-2.0
-->

# 0006 — Three contracts, not one promise

- Status: draft — decision taken, specification being rewritten to it,
  runtime not yet changed.
- Date: 2026-08-17

## Context

Until now this project made a safety promise. ADR 0002 lists it among
the load-bearing constraints — *"Bytecode is untrusted input. A pushed
script must never crash a node"* — and specification §2.6 turned it into
a conformance rule: **verification is mandatory, an implementation that
runs unverified containers does not conform.**

The promise was not idle. The runtime implements it, a corpus of 47
containers holds two independent verifiers to one verdict, and that
corpus has already caught a real divergence between them. Nothing here
was aspirational.

Two things happened on 2026-08-17 that put it on the table anyway.

**Measurement.** ADR 0004 §4.9 costed the runtime for the first time.
Verification is roughly two thirds of it — about 2.5 KB against 1.5 KB
for the interpreter it protects — and the project's original 1–2 KB
estimate turns out to have been an estimate of a *trusting* runtime that
nobody then built. That made the price visible, which is all measurement
can do; it does not decide anything.

**The argument that does decide it** came from the product owner, and it
is not about size at all.

This language has **two backends**. The same source compiles to a
container for the VM or transpiles to C that the embedder's own
toolchain builds into the firmware. That equivalence is the project's
central claim, held to by differential tests that demand bit-identical
results.

Transpiled C can be tampered with exactly as a container can — and so
can the machine code the C compiler produces from it. On that path the
project offers no protection, intends to offer none, and could not offer
any: it hands over a `.c` file and its involvement ends. So a verifier
on the bytecode path does not make MCUScript safe. It makes **one of two
equivalent paths** carry a guarantee the other cannot, in a project whose
headline is that the two paths are the same.

That asymmetry is worse than an absence, because of how it will be read.
Almost nobody will reason "the bytecode loader rejects a specific class
of malformed input, which matters only if my delivery path is
untrusted". They will read "MCUScript checks the code" and skip signing
their pushes. The project would then have caused the exposure it was
trying to prevent, and would have done so through a promise it never
literally made.

Three counter-arguments were considered and none survives.

*We defend against our own compiler's bugs.* Weakly, and the defence is
a **testing** strategy wearing runtime clothing: two implementations
with deliberately different algorithms are worth having, but they belong
beside the compiler and in CI, not on a battery-powered device.

*We defend against foreign compilers.* A foreign compiler's dangerous
output is the **spec-legal** construct our own compiler never emits and
our tests never exercise — and a verifier accepts those by definition.
What it rejects is spec-illegal input, which is a narrower set than the
reassurance suggests.

*Nothing else contains the damage.* True, and it is the one real
difference from a C compiler: gcc can be indifferent to what becomes of
its output because an MMU and a supervisor stand underneath. Under this
VM there is nothing. But that argues for saying loudly whose job it is —
not for taking the job.

## Decision

**Replace one promise with three contracts.**

| | |
|---|---|
| **A — the compiler** | The reference compiler emits conforming containers. |
| **B — the runtime** | The reference runtime executes conforming containers as this specification says. On anything else its behaviour is **undefined**. |
| **C — the path between them** | Getting a container from A to B unaltered is the **embedder's** concern, and it is the same concern for either backend. |

Specific consequences of that split:

1. **There is no device-side verifier**, and none is offered — not as a
   build option, not as a module, not as a separate repository in this
   organisation. An unmaintained component that people find and trust is
   the same hazard in a different place. The code stays in git history;
   anyone who needs one can build it, and `spec/corpus/` gives them the
   verdicts to build it against.
2. **The host-side verifier in `tools/` stays**, and grows in
   importance. It is contract A's second opinion: a different algorithm
   over the same specification, run by the compiler and by CI. This is
   where two implementations were always worth having.
3. **The loader checks identity, never well-formedness.** It answers
   only "is this container meant for me": magic, format version, profile
   pin, group mask, CRC. Six comparisons, all cheap, none of them a
   judgement about whether the container is any good.
4. **The CRC stays**, and the specification says what it is not. Its job
   is a flipped bit — an editor's encoding, a truncated transfer, a bad
   flash write. Neither the toolchain nor the embedder can see those
   from where they stand, and executing obviously broken bytes is worth
   56 bytes to avoid. It is not a security control and CRC-32 is
   trivially forged; saying so in the text is part of this decision,
   because the alternative is someone relying on it.
5. **`max_stack` and `max_call_depth` stay in the container and are
   believed.** The VM sizes its frame from them. Under the old rule they
   were recomputed and compared, which made them nearly redundant; under
   this one they are load-bearing, and a container that lies about them
   is a non-conforming container whose behaviour is undefined — exactly
   like every other kind of non-conforming container.
6. **§2.6 point 1 moves from enforcement to obligation.** That an
   opcode must belong to a group the header requires becomes a rule the
   compiler satisfies rather than one the loader polices. The header's
   group mask keeps its other job, which is contract-B business: it lets
   a narrowed build refuse a container it could not run, which is an
   identity question and not a safety one.
7. **`spec/corpus/` changes what it is for.** It stops being "the
   verdict both loaders must reach" and becomes "the verdict a
   conforming *verifier* must reach". Its `ok` cases remain runtime
   tests; its refusal cases become host tests. It is also the most
   valuable thing this decision leaves behind for anyone who does want a
   device-side verifier.

The positioning paragraph, which belongs in the README and in the
specification's front matter:

> MCUScript is a language with two backends. It guarantees that the same
> source produces the same behaviour on both, that the reference
> implementation of the compiler emits conforming containers, and that
> the reference implementation of the runtime executes conforming
> containers as specified. About code the reference implementation did
> not produce, the reference runtime guarantees nothing; on
> non-conforming input its behaviour is undefined. How an artifact
> travels from the compiler to a device, and how it is protected on the
> way, is the embedder's concern — **equally for both backends**.

The wording is deliberate on one point: it says *reference
implementation*, not *MCUScript*. A third-party compiler is MCUScript
too, and the sentence would be false about it.

## Consequences

- **The specification loses a conformance rule and gains a contract.**
  §2.6 no longer says an implementation must verify. It says what a
  conforming container is, which is the same list of properties read as
  an obligation on the producer rather than as a duty of the consumer.
  A verifier is then definable — and is defined — as a component that
  decides that list, without being required.
- **What an embedder must do becomes explicit rather than implied.**
  Today the specification is silent about the path and the runtime
  quietly compensates; afterwards the specification names it. For
  MCUHome, the reference embedder, the answer is the infrastructure it
  already has: it signs firmware, and signing script pushes is the same
  mechanism applied to the other backend.
- **Nothing about the two-backend equivalence changes.** The
  differential test that guards it is untouched. What goes is the test
  that held two verifiers to one verdict, and it goes because one of the
  two verifiers goes.
- **Roughly 2.5 KB of reviewed, corpus-tested C leaves the runtime.**
  That is a real loss and worth stating as one. The estimate for
  contract B alone is ~2.1 KB for an expression-only build against 7.4 KB
  today, and ~4 KB complete against 10.5 KB — estimated, not yet
  measured, because the runtime has not been changed.
- **A future device-side verifier is a different project, not a
  regression.** If someone builds one, this specification tells them
  exactly what to decide and the corpus tells them what the answers are.

## Open

- **The order of work.** The specification text changes first and the
  runtime second, deliberately: a rewrite that arrives before its
  justification is a rewrite nobody can review.
- **Whether the loader keeps a bounded amount of structural checking
  anyway** — not for safety, but because a loader that reads past the
  end of a buffer while parsing a corrupt container is a bug in contract
  B rather than an application of it. The line is that the loader must
  not fall over on input it rejects; it need not diagnose why.
- **An interface hash in the header**, replacing per-import name
  matching. It belongs to this decision because it is the same kind of
  question — identity, not well-formedness — and it catches strictly
  more: renaming an entity is caught today, *swapping two* is not, and
  swapping two is the failure that silently produces wrong numbers.
