# The MCUScript runtime

The loader and the VM, in C99. This is what goes on the device.

> **This runtime does not verify** (ADR 0006). Deciding whether
> arbitrary bytes are a conforming container is not this project's job:
> the language has two backends, transpiled C carries no such guarantee
> and could not, and a guarantee that holds on one path invites the
> reading that the language protects a device against code it did not
> produce. What it promises is narrower and honest — it executes
> **conforming** containers as the specification says, and is undefined
> on anything else. If containers reach it from somewhere untrusted,
> verify them first or authenticate the path.

Two source files, one public header, **no dependencies** beyond
`<string.h>` and the fixed-width integer types. It never allocates:
every buffer is one the embedder passed in or one sized at compile time
by a macro in [`include/mcuscript.h`](include/mcuscript.h). A runtime
with a `malloc` in it is a runtime that only works on the machine it was
tested on.

## Building

The CMake file is for the tests. The four files drop into any build
system, which is the point of having no dependencies.

```sh
cmake -S runtime -B build && cmake --build build && (cd build && ctest)
```

## Using it

An embedder does three things.

**Declare what a script may reach.** An array of `mcuscript_import`:
entities the script reads or writes, functions it calls, each with a
name, a type and a dimension. Three callbacks — `read`, `write`,
`invoke` — and a context pointer.

**Load a container.** `mcuscript_load` parses it and resolves every name
against that array. It returns false with a named refusal, or true, and
after that no name is looked at again. It does **not** verify — every
check it makes answers "is this container meant for me".

**Invoke an entry point.** `mcuscript_find_entry` by name,
`mcuscript_invoke` with a slot buffer. One buffer serves the whole
device: scripts run to completion and never nest, and a conforming
container is one whose deepest call chain fits in it. An entry point
takes no arguments — a script reads what triggered it from
an entity, which is also where it can read it twice.

[`tests/mcuscript_run.c`](tests/mcuscript_run.c) is a complete embedder
in about 300 lines, and it is short enough to read as documentation.

## What it does not do

- **It does not verify** (see the note at the top). It reads past
  `max_stack` and `max_call_depth` without looking at them, and it takes
  the call graph's condensation from the `component` field rather than
  computing it. The one declared field it still bounds-checks is that
  one, because it indexes the runtime's own arrays.
- **It does not read import names.** A `HOST` record carries an FNV-1a
  hash (§4.4.1) and the loader hashes the host's own names to match it.
  The names live in the ancillary `hnam` section, which this runtime
  walks past; `mcuscript strip` removes it, and that is the form a
  device should be given.
- **It does not have to implement every instruction group.** By default
  it does — `core`, `i64`, `i64div`, `float`, `call`, `bits`, `loop` —
  and `-DMCUSCRIPT_GROUPS_IMPLEMENTED=MCUSCRIPT_GROUP_CORE|...` drops
  the rest: their dispatch cases are not compiled, and a container whose
  header needs one is refused at load, by name, before anything runs. The groups occupy
  disjoint opcode ranges precisely so a build can drop a contiguous span
  of the dispatch table. Only `core` is mandatory. Dropping `loop`
  drops the ability to *bound* a cycle rather than to jump backwards,
  which is why a container containing one is refused rather than run.
- **It does not survive `-ffast-math`.** The header refuses to compile
  under it, and a build must pass `-ffp-contract=off`. Both are measured
  requirements, not superstition — see spec §1.5.
- **It does not count instructions.** A conforming container terminates
  because both of its ways to repeat work carry a bound — a guarded
  counter per loop, a cap per call-graph cycle — so the dispatch loop
  carries no budget, and the C backend has nothing artificial to
  reproduce. Those two counters are the opposite kind of thing: each is
  one named instruction's own arithmetic, paid for only by the
  construct that asked for it.

## There used to be two verifiers

This runtime had one, written against the host toolchain's with a
different algorithm everywhere the two did the same job: a single
forward pass against a worklist, a reachability matrix against Tarjan.
Two methods over one specification, bound together by
[the corpus](../spec/corpus/), and it paid — the runtime once accepted a
container whose header under-declared its instruction groups, and the
host verifier refused it.

That is what ADR 0006 costs, and it is worth naming as a loss rather
than smoothing over. What is left is the host verifier and the corpus:
one implementation, and a set of committed containers with the verdict
any other implementation must reach.

## What it costs

Measured on a **linked image**, cortex-m33 at `-Os`, and reproducible
with `python ../tools/measure_footprint.py`:

| | flash | of which the loader |
|---|---:|---:|
| every group | 5,812 B | 1,621 B |
| `core` + `float` | 3,748 B | 1,617 B |
| `core` only | 3,220 B | 1,621 B |

Linked rather than compiled, because the compiler's own support library
is part of what a device pays: 64-bit division alone pulls in 698 bytes
of it, which is why `i64div` is a group of its own. On a Cortex-M0+,
with neither a divide instruction nor an FPU, the full build is 8,986 B
rather than 5,812.

No static RAM at all. An embedder declares an `mcuscript_program` (372
bytes with the default limits) and an `mcuscript_slots` (576), and the
runtime borrows at most 176 bytes of stack while loading and 348 while
running — never both, since loading has finished before anything runs.

The loader column is the same figure three times, and that is the thing
to notice: it does not shrink with the group mask, because nothing in it
knows what an instruction is. Everything that did — the type rules, the
instruction-length table, the call-graph condensation — was verification,
and it is gone. What is left is a parser and a dispatch loop, so
**dropping groups is now most of what there is to drop**: 2.5 KB of the
5.7.

Also verified on hardware rather than argued: an nRF5340 running a
container that uses all five groups returns the same value, bit for bit,
as the host runner given the same world (ADR 0004 §4.10).
