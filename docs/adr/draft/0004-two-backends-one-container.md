# 4. Two backends, one container

- Status: **draft** — the shape is settled and implemented for every
  instruction group the specification defines; the parts marked *open*
  below are not yet decided.
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

### 4.5 Floating point is bit-identical, not approximate

Asked whether the two backends could be allowed to differ in the last
digits, the answer is no, and it is cheaper than it sounds.

IEEE-754 defines `+`, `-`, `*` and `/` as the *correctly rounded* result
of the exact mathematical operation, so for given operands there is one
right answer and both backends compute it on the same hardware.
Bit-identity is the normal case; the deviations are nameable and all of
them are the compiler's doing, not the arithmetic's.

A tolerance would also not buy what it appears to. A comparison feeds a
branch: one ULP of disagreement in `temp > 25.0` is not one ULP of
disagreement in the output, it is a different arm of the ladder. And the
values that matter here — NaN, the two zeroes, the infinities a faulty
sensor produces — are precisely the ones no tolerance can express.

Two things make it hold in practice. A slot holds the 32-bit pattern, so
both backends narrow at the same points and an FPU with wider
intermediates cannot separate them. And the build passes
`-ffp-contract=off` and never `-ffast-math` — measured, not assumed
(§1.5, and the one test in this repository that asserts a
*disagreement*).

### 4.6 The differential test compares, it does not expect

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

### 4.7 A call is a C call, and the cap is a static counter

The question 4.6 left open. MCUScript functions become ordinary `static`
C functions; an entry point is one of those plus a thin wrapper carrying
the `mcuscript_value` the embedder expects, so there is one body
generator and not two.

Parameters are passed as C parameters — as the slot pair, value and
state — and that is exact rather than convenient: §3.6 says arguments
*are* the callee's first locals, and C parameters are assignable
lvalues, so the callee's local 0 is the C parameter and `store.l 0`
writes it. The VM reaches the same place from the other side: the
arguments are already on top of the caller's stack in order, so its
frame begins there and nothing is copied either.

The recursion cap becomes `static unsigned` per call-graph cycle. Two
things about it are decisions rather than mechanics:

- **The decrement is on every path out, including the fault path.** A
  counter that leaked when an invocation faulted would refuse the *next*
  invocation for what this one did — the failure would appear one run
  later, in a program that is fine. Every generated function therefore
  has a single `done:` epilogue and every exit is a `goto` to it.
- **It is static, not per invocation.** Scripts never nest (§5.1), so
  there is nothing for a per-invocation counter to distinguish, and a
  static one costs no argument passing. The VM's are locals of
  `mcuscript_invoke` for the opposite reason: it has a frame to put them
  in, and locals cannot leak at all.

That asymmetry is the one place in this project where the two backends
are told to do different things, so it gets its own test — the compiled
program is invoked twice in one process and the second invocation must
behave exactly like the first. The comparison cannot see this: the VM
has no such state to get wrong.

### 4.8 The call graph is computed twice, by different algorithms

The host verifier condenses the graph with Tarjan's algorithm; the
runtime uses a reachability matrix and Warshall. Not a duplication that
happened — a duplication that is the point, and the reason is the same
one behind the two verifiers: Tarjan needs an explicit stack whose depth
is the graph's, and a device runtime may not have one that grows.
`MCUSCRIPT_MAX_FUNCTIONS` is small by design, so one bit per pair of
functions fits in a handful of bytes and cubic time over eight nodes is
free.

Everything else falls out of that matrix: `i` and `j` share a component
when each reaches the other, a component is a cycle when a member
reaches itself, and a function is dead when no entry point reaches it.

## Consequences

- **Floating point needs the build, not only the source**, and the
  requirement is measured. GCC does not implement
  `#pragma STDC FP_CONTRACT` — it warns that the pragma is ignored and
  contracts anyway — so a conforming build passes `-ffp-contract=off`.
  With `-mfma` and GCC's `-std=gnu*` default, `a*b + c` for `1e20`,
  `1e20`, `-inf` gives NaN through the VM and -inf through the compiled
  C. Generated units also `#error` on `__FAST_MATH__`, the one of the
  two a compiler will admit to. The test suite contains the only
  assertion in this repository that the backends **disagree**, so the
  requirement cannot quietly stop mattering.
- **The C API toward embedders is settled by having been written.** An
  embedder declares an array of imports and three callbacks, calls
  `mcuscript_load`, and is either refused by name or handed a program.
  ADR 0002 §8 can drop the question.
- Generated C needs no runtime library at all — not the loader, not the
  VM, only a header of inline functions. A device that compiles its
  scripts in carries neither.

## Open

- **Several containers in one translation unit.** The entry wrappers
  have external linkage and a second program would collide. A
  per-program prefix is the likely answer; nothing needs it yet. The
  function bodies are `static` and already safe, which is also why a
  container carrying a function nothing calls is refused rather than
  compiled — a C compiler rejects an unused static, and refusing at load
  keeps that from being a difference between the backends.
- **A build that drops a group is untested against a real program.**
  Both backends now implement everything, so the refusal of §2.5 can
  only be provoked through a container's header. The mechanism is
  right — the check reads the header, not the code — but nobody has
  compiled a runtime with `MCUSCRIPT_GROUPS_IMPLEMENTED` narrowed and
  measured what it saves, which is the number the modularity claim in
  ADR 0002 rests on.
