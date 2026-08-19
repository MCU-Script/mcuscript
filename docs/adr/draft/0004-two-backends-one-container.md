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
and its validity state — and each branch becomes a `goto`. Backward
ones cost this backend nothing extra, because it reads each pc's stack
shape out of the verifier's recorded map instead of walking it forward:
a loop header already carries the depth its back edge must agree with,
and `inconsistent_join` is what makes them agree (ADR 0007).

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

### 4.9 Narrowing the group mask removes the code, and the numbers say what that is worth

The group bits were a **permission** and nothing more: `#if` read them
nowhere, so a build with `MCUSCRIPT_GROUPS_IMPLEMENTED` narrowed refused
containers it could in fact have run, and saved not one byte. The
modularity requirement of ADR 0002 §1.3 — *"the VM assembled from feature
modules so an expression-only device links an expression-only VM"* —
rested on that.

It is now real: the dispatch cases, the verifier's type rules and the
instruction-length table are each compiled per group, the group bits
moved to the installed header where a build system can reach them, and
`core` is mandatory and every other group is droppable, `loop`
included since ADR 0007 gave it an instruction.
`python tools/measure_footprint.py`
cross-compiles the whole matrix; the figures below are
arm-zephyr-eabi-gcc 14.3.0 at `-Os`.

**It measures a linked image, not object files, and that correction
matters more than it sounds.** An object file shows the code this
project writes. It does not show `__udivmoddi4`, `__aeabi_idiv` or the
soft-float helpers — the *compiler* emits calls to those and the linker
pulls them in, and on a Cortex-M0+ they outweigh several of the groups.
The first version of this table was compiled and not linked, and it
understated the m0+ figure by 28 % while overstating m33 by counting
`names.c`, which `--gc-sections` discards for any embedder that does not
report a refusal in words.

**Flash, bytes.** A linked image, support library included, unreferenced
code discarded. Measured after ADR 0006 removed the device-side
verifier; the figures the verifier was still in are two paragraphs down.

| group set | cortex-m0+ | cortex-m4f | cortex-m33 |
|---|---:|---:|---:|
| full | 8,986 | 5,812 | 5,812 |
| no i64 | 7,858 | 4,604 | 4,612 |
| no i64 division | 8,290 | 4,716 | 4,724 |
| no float | 5,450 | 5,556 | 5,556 |
| no call | 8,666 | 5,508 | 5,508 |
| no bits | 8,722 | 5,564 | 5,564 |
| no loop | 8,906 | 5,740 | 5,740 |
| expressions + float | 7,258 | 3,756 | 3,748 |
| expressions only | 3,618 | 3,228 | 3,220 |

**What each group costs on cortex-m33**, as full minus that group:
`i64` 1,200 (21 %), of which **`i64div` alone is 1,088 (19 %)**;
`float` 256 (4 %); `call` 304 (5 %); `bits` 248 (4 %); `loop` 72 (1 %).

The `expressions only` row is the one to read against `full`: a device
that evaluates formulas links 3,220 bytes, and everything above that is
something it asked for.

**A group's cost is not a property of the group**, and this table is
where that stops being a footnote. Every figure above is a difference
between two linked images, and the interpreter is one `switch`: change
which opcodes exist and GCC changes how it dispatches, so a row moves
without a line of its group being touched. ADR 0010's four `core`
instructions did exactly that — see the paragraph after next — and they
moved `i64` from 1,704 to 1,200 and `bits` from 536 to 248 while
neither group changed at all. Read a row as *what this build costs
today*, never as a price list.

**`loop` is the clearest case of it**, and ADR 0007 measured it apart
when it was 384 bytes: 48 were the instruction and 310 were the
dispatch table re-lowering itself, because `0xA0` was the only opcode
in the gap between `bits` and `i64div`. It is 72 today. Nothing about
loops changed; the opcode space around them got denser, and the
re-lowering that ADR 0007 identified as the real cost stopped
happening.

**What ADR 0010's four instructions cost**, since it is the one
measurement where an addition made the image smaller. `core` grew by
136 bytes on cortex-m33, which is the honest price of `AND`, `OR` and
the two chosen-state constants. The **full** build shrank by 168 — from
5,980 to 5,812 — and `vm.o` with it, from 3,492 to 3,324, with four
more cases in the switch than before. The cause is visible in the
disassembly: filling `0x2C`–`0x2F` made the opcode range dense enough
for GCC to cover part of the dispatch with a table branch (`tbh`) that
had been a chain of comparisons, and the table is smaller than the
chain was. The lesson is the one above rather than "adding
instructions is free": four in a hole paid for themselves, four in a
fresh range would not.

That `i64div` line is why it is a group at all (§3.4). Two instructions
cost nine times the other thirteen in their range — 1,088 against the
112 that separate `no i64` from `no i64 division` — because 64-bit
division is the one operation here that a 32-bit processor cannot do in
registers. Splitting it out is what makes 64-bit *comparison* — a
timestamp, an energy counter — affordable on a device that will never
divide one. This is the one row that has stayed put through every
re-measurement, and the reason it does is that a support routine is a
function the linker either pulls in or does not, not a shape the
dispatch loop can absorb.

**What ADR 0006 did to the numbers**, since the before-and-after is the
clearest statement of what verification was costing:

| cortex-m33 | with the verifier | without |
|---|---:|---:|
| full | 10,525 | **5,652** |
| expressions only | 7,375 | **3,132** |
| `load.c` | 5,912–6,542 | **1,617, flat** |
| `mcuscript_program` | 436 B | 380 B |
| stack while loading | 732 B | 192 B |

The flat figure is the part worth pausing on. `load.c` used to shrink
with the group mask, because a type checker has a case per opcode; it
is now **the same size in every configuration**, since nothing in it
knows what an instruction is. That is the cleanest confirmation
available that the verifier is actually gone rather than merely
disabled.

**The old estimate was low, and it was low about the right thing.** ADR
0002 §8 carried 1–2 KB for an expression-only engine. An expression-only
*interpreter* is 1,646 bytes on cortex-m33 — the estimate was close, and
it was silent about everything around it. That silence is now much
cheaper than it was:

| | load.c | vm.c | names.c | own total | linked |
|---|---:|---:|---:|---:|---:|
| full | 1,621 | 3,324 | 887 | 5,832 | 5,812 |
| expressions + float | 1,617 | 2,160 | 887 | 4,664 | 3,748 |
| expressions only | 1,621 | 1,646 | 887 | 4,154 | 3,220 |

ADR 0006 estimated ~2.1 KB expression-only and ~4 KB complete. The real
figures are 3.2 KB and 5.7 KB, so that estimate was **a kilobyte too
optimistic** — worth recording, because it was an estimate made from the
attribution table rather than from a build, which is exactly the kind of
number this document exists to stop trusting.

The reading of the modularity requirement has moved twice, and where it
has landed is worth stating plainly. When the verifier was in, feature
modules were trim — a fifth of the whole at best — and the size lever
was choosing the other backend. Without it, **the group mask is the
larger share of what is left**: 2.5 KB of 5.7 on a Cortex-M33, since
what remains is a dispatch loop and a parser, and the dispatch loop is
the part that has groups. ADR 0002 §1.3's *"an expression-only device
links an expression-only VM"* is now a fair description of what happens.

Choosing the other backend is still the bigger knob — generated C links
no loader and no VM, so the same script costs zero of these bytes — but
it is no longer the only one that matters.

**RAM, and none of it is static.** The runtime declares no writable
data at all; every byte below is the embedder's, and sized by the macros
in `mcuscript.h` rather than by the container.

| | bytes | set by |
|---|---:|---|
| `mcuscript_program` | 372 | `MAX_IMPORTS`, `MAX_FUNCTIONS`, `MAX_CONSTANTS` |
| `mcuscript_slots` | 576 | `MAX_SLOTS` (64 × 9) |
| stack, load | ≤ 176 | transient; gone before the first invocation |
| stack, invoke | ≤ 348 | transient |

The two stack figures never add: `mcuscript_load` has long returned when
`mcuscript_invoke` is called. Both are GCC's `-fstack-usage` summed over
the translation unit, which is an upper bound and a safe one, because
the runtime does not recurse.

Loading used to be the deeper of the two at 732 bytes, and is now the
shallower at 176: the walker held a type stack and a table of pending
branches, and neither exists any more. `mcuscript_program` lost 56 bytes
for the same reason — `code_end`, `max_stack`, `max_call_depth` and
`local_types` were per-function fields nothing outside the verifier ever
read — and then another 8 to the import hash, which replaced a name
pointer and a length with a `uint32_t` per import. Those last two
figures were carried forward rather than re-measured when the hash
landed; 380 and 192 appear in ADR 0006's table for that reason and are
the pre-hash numbers.

### 4.10 It has been run on real hardware

Everything above is cross-compiled. On 2026-08-17 the runtime was also
loaded and invoked on an **nRF5340 application core** (nRF7002-DK,
Zephyr 4.4.0, `-Os`), with a container using all five groups — a float
comparison, a shift and a mask, a user function call, a host function
call, a forward branch and a 64-bit round trip, arranged so every group
contributes to the answer.

- The device returns **176, valid**, and writes **176, valid** to its
  entity. The host runner, given the same container and the same world,
  returns and writes the same. Two architectures, one answer.
- `sizeof(mcuscript_program)` is 436 and `sizeof(mcuscript_slots)` 576
  on the device, matching the cross-compiled table exactly. Both
  `mcuscript_program` figures are the pre-ADR-0006 ones; the run has not
  been repeated since, and it is the *agreement* that was the point.
- Stack high-water across `mcuscript_load` is **536 bytes** measured,
  against the 732-byte bound above — the bound holds, with 27 % slack,
  which is about what summing whole frames should cost.
- Built into a real Zephyr image with Zephyr's own flags rather than
  this tool's, the three objects came to **10,539 bytes** against the
  10,491 the tool then reported for the same three objects. A 0.5 % gap,
  which is the method checking out. Both figures are object-file sums,
  and §4.9's table has since moved to linked images for the reason given
  there; the comparison stands as the like-for-like it was.

The fixture was a throwaway Zephyr application and is not in this
repository: a sample here would tie a standalone language project to one
RTOS, and it would rot. What is kept is the part that reproduces
anywhere with an ARM cross compiler — `tools/measure_footprint.py` — and
this record of what the device said.

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
  scripts in carries neither. §4.9 puts a number on what that saves:
  everything, and everything is 7 to 14 KB.
- **The container must declare every group its code uses**, and the
  runtime now checks it (§2.6.1). It did not, and the host verifier did,
  which made an under-declaring container a thing the two
  implementations disagreed about — the C loader ran it. That is the
  hole §2.5 cannot have, because the header is the whole of what lets a
  narrowed build refuse a container before meeting an instruction it
  does not implement.
- **The warning policy now survives optimisation.** `-Werror` had only
  ever been exercised at `-O0`, since that is what the CMake test build
  uses; at `-O2` the loader did not compile. A device build is always
  optimised, so the measurement matrix compiles every group set at every
  level, with two compilers.

## Open

- **Several containers in one translation unit.** The entry wrappers
  have external linkage and a second program would collide. A
  per-program prefix is the likely answer; nothing needs it yet. The
  function bodies are `static` and already safe, which is also why a
  container carrying a function nothing calls is refused rather than
  compiled — a C compiler rejects an unused static, and refusing at load
  keeps that from being a difference between the backends.
- **The loader is no longer where a small build's flash goes.** It was
  5,912 bytes of the 7,375 an expression-only device paid; it is now
  1,669 of 3,132, and flat across every group set. Most of the
  candidates listed here went with the verifier — the call-graph
  condensation is a declared field (§4.3), and the branch-merge
  machinery does not exist. **One survives, and is now the largest
  single thing left in the loader**: per-import name matching could be a
  single interface hash in the header, which would catch strictly more
  than it does today, since renaming an entity is caught and *swapping
  two* is not. That is a correctness argument before it is a size one.
- **Whether a device-side verifier belongs in this project at all** —
  **decided, and carried out.** ADR 0006 (2026-08-17) says no, on
  structural grounds rather than about size: a guarantee that holds on
  the bytecode path and cannot hold on the transpiled-C path invites the
  reading that the language is safe when it is not. The specification
  was rewritten first, and the runtime followed on 2026-08-18. What the
  loader keeps is identity, never well-formedness.
