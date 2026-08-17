# The MCUScript runtime

The loader, the verifier and the VM, in C99. This is what goes on the
device.

> **The verifier is on its way out.** ADR 0006 (2026-08-17) decided that
> deciding whether arbitrary bytes are a conforming container is not this
> project's job: the language has two backends, transpiled C carries no
> such guarantee and could not, and a guarantee that holds on one path
> invites the reading that the language protects a device against code it
> did not produce. What this runtime will promise is narrower and
> honest — it executes **conforming** containers as the specification
> says, and is undefined on anything else. The text below still describes
> what is built today; the code has not changed yet.

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

**Load a container.** `mcuscript_load` parses it, verifies it and
resolves every name against that array. It returns false with a named
refusal, or true, and after that no name is looked at again.

**Invoke an entry point.** `mcuscript_find_entry` by name,
`mcuscript_invoke` with a slot buffer. One buffer serves the whole
device: scripts run to completion and never nest, and the loader has
already checked that the container's deepest call chain fits in it. An
entry point takes no arguments — a script reads what triggered it from
an entity, which is also where it can read it twice.

[`tests/mcuscript_run.c`](tests/mcuscript_run.c) is a complete embedder
in about 300 lines, and it is short enough to read as documentation.

## What it does not do

- **It does not skip verification** — today. There is no flag for it,
  and the VM sizes its frame from numbers the container supplied, which
  is where those numbers are recomputed. Under ADR 0006 this becomes an
  obligation on whoever produced the container instead, and the entry
  above the heading says what that changes.
- **It does not have to implement every instruction group.** By default
  it does — `core`, `i64`, `float`, `call`, `bits` — and
  `-DMCUSCRIPT_GROUPS_IMPLEMENTED=MCUSCRIPT_GROUP_CORE|...` drops the
  rest: their dispatch cases, their type rules and their entries in the
  instruction-length table are not compiled, and a container needing one
  is refused at load, by name, before anything runs. The groups occupy
  disjoint opcode ranges precisely so a build can drop a contiguous span
  of the dispatch table. Only `core` is mandatory, and `loop` is a
  compile error because it is reserved and has no instructions yet.
- **It does not survive `-ffast-math`.** The header refuses to compile
  under it, and a build must pass `-ffp-contract=off`. Both are measured
  requirements, not superstition — see spec §1.5.
- **It does not count instructions.** Termination is proved at load —
  no backward jumps, capped call-graph cycles — so the dispatch loop
  carries no budget, and the C backend has nothing artificial to
  reproduce.

## Two verifiers, on purpose

The host toolchain has one too, and everywhere the two do the same job
they use a different method.

For the type stack: a worklist that can say which path produced a
conflict, against this one's single forward pass in address order. The
forward pass is possible only because backward jumps are rejected, and
it is what keeps the device's memory bounded — it remembers a stack
shape per outstanding forward branch, not per instruction.

For the call graph: Tarjan's algorithm, against this one's reachability
matrix. Same reason. Tarjan needs a stack as deep as the graph; a matrix
over at most `MCUSCRIPT_MAX_FUNCTIONS` functions is a handful of bytes
and a triple loop.

Two methods over one specification is worth more than two copies of one
method. What binds them is [the corpus](../spec/corpus/) — containers
with the verdict each must get, run against both. It has already paid:
the runtime used to accept a container whose header under-declared its
instruction groups, and the host verifier refused it.

This is the section ADR 0006 costs the most. When the device-side
verifier goes, one of the two methods goes with it and the host one is
left alone — a real loss, and the reason the decision was argued on
grounds strong enough to be worth it. The corpus survives as the
material a conforming verifier is checked against, wherever one is
built.

## What it costs

Measured on a **linked image**, cortex-m33 at `-Os`, and reproducible
with `python ../tools/measure_footprint.py`:

| | flash | of which loader + verifier |
|---|---:|---:|
| every group | 10,525 B | 6,542 B |
| `core` + `float` | 8,349 B | 6,290 B |
| `core` only | 7,375 B | 5,912 B |

Linked rather than compiled, because the compiler's own support library
is part of what a device pays: 64-bit division alone pulls in 698 bytes
of it, which is why `i64div` is a group of its own. On a Cortex-M0+,
with neither a divide instruction nor an FPU, the full build is 14,043 B
rather than 10,525.

No static RAM at all. An embedder declares an `mcuscript_program` (436
bytes with the default limits) and an `mcuscript_slots` (576), and the
runtime borrows at most 732 bytes of stack while loading and 348 while
running — never both, since loading has finished before anything runs.

Two things that table says out loud. **Verification is roughly two
thirds of the whole**, and dropping every optional group saves about a
fifth — trim rather than a lever. And an expression-only interpreter
really is about 1.5 KB, which is what the project's original estimate
was about; it just left out everything around it.

Verification is what the second column costs, and ADR 0006 removes it —
so these figures describe what is built today, not what is intended. The
estimate for the runtime that decision leaves is ~2.1 KB for an
expression-only build and ~4 KB complete; it will be measured rather
than estimated once the code follows the text.

Also verified on hardware rather than argued: an nRF5340 running a
container that uses all five groups returns the same value, bit for bit,
as the host runner given the same world (ADR 0004 §4.10).
