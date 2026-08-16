# The MCUScript runtime

The loader, the verifier and the VM, in C99. This is what goes on the
device.

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

- **It does not skip verification.** There is no flag for it. The VM
  sizes its frame from numbers the container supplied, and this is where
  those numbers are recomputed.
- **It does not have to implement every instruction group.** This build
  does — `core`, `i64`, `float`, `call`, `bits` — but a build that drops
  one refuses a container needing it at load, by name, before anything
  runs. The groups occupy disjoint opcode ranges precisely so a build
  can drop a contiguous span of the dispatch table, and only `core` is
  mandatory.
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
method. What binds them is a corpus of containers with expected
verdicts, run against both.
