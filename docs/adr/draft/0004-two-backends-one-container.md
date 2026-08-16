# 4. Two backends, one container

- Status: **draft** — the shape is settled and implemented for the
  `core` group; the parts marked *open* below are not yet decided.
- Supersedes nothing. Answers ADR 0002 §8's largest open question, the
  C API toward embedders.

## Context

The project's central promise is that every program has two lowerings —
a bytecode container for the VM, and C compiled into the firmware — and
that they behave identically. Making that true is an architectural
question, not a coding one, and the choices below were made while
writing the two backends rather than before.

## Decisions

### 4.1 The C backend consumes the container

Not an earlier intermediate form. Both backends start from the same
bytes.

The alternative was to lower from a typed IR held by the compiler, which
would produce nicer C. It was rejected because it weakens exactly the
thing the second backend exists to demonstrate: with two different
inputs, a divergence can always be blamed on the step that produced
them, and the container encoder — the part most likely to have a bug —
would be tested by only one of the two paths.

Two consequences fall out and both are wanted. The C backend inherits
the verifier's work: types, depths and branch targets are already
proved, so the generator checks none of them. And a container that
arrived over the air can still be compiled in, which keeps "which
backend" a deployment decision rather than a decision taken at the
source level.

### 4.2 The lowering is the stack machine, not an expression tree

Each operand-stack position becomes a pair of C variables — the value
and its validity state — and each branch becomes a forward `goto`, which
the no-backward-jumps rule (spec §3.8) makes legal by construction.

Reconstructing `a + b * c` from the stack is possible and would produce
C a human would rather read. It is not done, because the generated C is
compiled, not read, and every optimizing compiler puts those variables
in registers and deletes the copies. What reconstruction would add is a
second place for the lowering to be wrong. If readable output is ever
wanted — for debugging, or for shipping generated C as a source
artifact — it is a pass on top, and it does not change semantics.

### 4.3 Linking is the C linker's

Each import becomes an `extern` function the embedder implements:
`mcuscript_read__temp`, `mcuscript_write__fan_speed`,
`mcuscript_call__clamp`. There is no import table in generated C and no
name resolution at run time.

This is the honest lowering of what linking *is* for a compiled-in
program: the embedder's registry is known when the firmware is built, so
a script referring to something that is not there should be a build
error — strictly earlier, and cheaper, than the load-time refusal the VM
gives.

Names are mangled by replacing every non-identifier character with an
underscore, which can collide: `fan.speed` and `fan_speed` produce one
symbol. The generator **refuses** rather than emitting two declarations
and letting the C compiler explain it.

### 4.4 The arithmetic primitives are shared, not duplicated

`runtime/include/mcuscript_ops.h` holds wrapping addition, division by
zero, the validity lattice and the slot conversions as `static inline`
functions, and both the interpreter and every generated translation unit
include it. They are not two implementations that agree; they are one
implementation used twice.

This is a deliberate trade against the differential test. A shared bug
is invisible to a test that compares the two backends, so the test is
weaker for arithmetic — and the product is stronger, because the class
of divergence the test was looking for cannot occur. What the test still
covers is where two independently written backends actually differ:
evaluation order, stack discipline, control flow, and what reaches the
host in which order.

The trade is reversible. If a toolchain ever appears that cannot take
the header, the arithmetic gets a second implementation and the test
gets its teeth back; the header says so.

### 4.5 The differential test compares, it does not expect

`tools/tests/test_differential.py` runs the same container through both
backends against the same host description and asserts the outputs are
**byte-identical**. It does not assert that each matches a written
expectation, because a written expectation tests the expectation.

Both backends print through the same code
(`runtime/tests/hostfile.c`), so a difference in output is a difference
in the program rather than in the scaffolding. The output is a
line-oriented protocol — `write`, `result`, `fault`, `refused`, `done` —
and it is a contract between the two harnesses rather than a
convenience.

## Consequences

- **Floating point needs the build, not only the source.** Writing the
  backend found that GCC does not implement `#pragma STDC FP_CONTRACT`:
  it warns that the pragma is ignored and contracts anyway. The
  generated source emits the pragma only where it is honoured, and a GCC
  build must pass `-ffp-contract=off`. Specification §1.5 was corrected
  to say so. The `float` group is not lowered yet, so this is
  forward-looking — but it is the kind of thing that would have been
  discovered far later and far more expensively.
- **The C API toward embedders is settled by having been written.** An
  embedder declares an array of imports and three callbacks, calls
  `mcuscript_load`, and is either refused by name or handed a program.
  ADR 0002 §8 can drop the question.
- Generated C needs no runtime library at all — not the loader, not the
  VM, only a header of inline functions. A device that compiles its
  scripts in carries neither.

## Open

- **Function calls.** The `call` group is not lowered. Ordinary C
  functions plus the recursion counter of spec §5.4 is the obvious
  shape, but it has not been written and so it is not decided.
- **`i64` and `float`.** The VM does not implement them either; both
  backends should gain them together, and the differential test is the
  reason to do it in that order.
- **Several containers in one translation unit.** Today the generated
  symbols are global and a second program would collide. A per-program
  prefix is the likely answer; nothing needs it yet.
