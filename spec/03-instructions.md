<!--
SPDX-FileCopyrightText: 2026 The MCUScript Contributors
SPDX-License-Identifier: Apache-2.0
-->

# 3. Instructions

## 3.1 Encoding

An instruction is **one opcode byte followed by zero to four operand
bytes**, and its length follows from the opcode alone. Operands are
little-endian and are **not aligned** — the instruction stream is
byte-granular, and a reader must load multi-byte operands bytewise or
by an unaligned-safe means. This is the one place in the container
where alignment is deliberately absent: padding every instruction to a
word would cost more in flash than the unaligned loads cost in cycles,
on a machine that spends most of its time in dispatch anyway.

Opcode `0x00` is not assigned, so a run of zeroed flash decodes as an
undefined opcode — which a verifier refuses, and which no conforming
container contains.

Notation used below: `imm8`/`imm16` are signed immediates, `idx8` an
unsigned index, `off16` a signed byte offset **relative to the first
byte after the instruction**. The stack effect column reads
`consumed → produced`.

## 3.2 Groups and opcode ranges

Groups are declared in the container header (§2.5) and occupy disjoint
opcode ranges, so an implementation that omits a group can omit a
contiguous span of its dispatch table and the linker can drop the
handlers whole. This is the reason the type is in the opcode rather
than in an immediate: with a type byte, float handling would sit inside
every arithmetic handler and could not be removed at all.

| Bit | Group | Range | Contents |
|---|---|---|---|
| 0 | `core` | `0x01`–`0x3F` | constants, locals, host access, `i32`, `bool`, branches, validity |
| 1 | `i64` | `0x40`–`0x5F` | 64-bit arithmetic, comparison, conversion |
| 2 | `float` | `0x60`–`0x7F` | `f32` arithmetic, comparison, conversion |
| 3 | `call` | `0x80`–`0x8F` | user-defined function calls |
| 4 | `bits` | `0x90`–`0x9F` | bitwise operations and shifts on `i32` |
| 5 | `loop` | `0xA0`–`0xAF` | the bound on a backward branch; see §3.8 |
| 6 | `i64div` | `0xB0`–`0xBF` | `DIV` and `REM` on `i64`; see §3.4 |
| 7–31 | | | reserved, must be zero |

`core` is mandatory. Every other group is optional in an
implementation and required by a container only if it uses it.

`i64div` is the one group that depends on another: its operands can
only be produced by `i64`, so an implementation claiming `i64div`
without `i64` accepts containers that cannot exist, and a container
requiring `i64div` requires `i64` too. Groups are otherwise
independent, and this one is a split rather than a new capability —
see §3.4 for why it is worth the exception.

## 3.3 The `core` group

### Constants

| Opcode | Instruction | Size | Effect | |
|---|---|---|---|---|
| `0x01` | `CONST.i32.s8 imm8` | 2 | `→ i32` | the sign-extended immediate |
| `0x02` | `CONST.i32.s16 imm16` | 3 | `→ i32` | the sign-extended immediate |
| `0x03` | `CONST.i32 idx8` | 2 | `→ i32` | constant pool entry `idx8` |
| `0x04` | `CONST.true` | 1 | `→ bool` | |
| `0x05` | `CONST.false` | 1 | `→ bool` | |

Constants produced by these instructions are always `valid`.

The two immediate forms exist because they cover what scripts actually
contain. A threshold in tenths of a degree — `280` for 28 °C — fits
`imm16`, and most other literals fit `imm8`; the pool is for the rest.

### Locals

| Opcode | Instruction | Size | Effect | |
|---|---|---|---|---|
| `0x06` | `LOAD.L idx8` | 2 | `→ T` | pushes local `idx8`, value and state |
| `0x07` | `STORE.L idx8` | 2 | `T →` | writes the top of the stack into local `idx8` |

These carry no type in the opcode, and that is not an exception to
§3.2: a local's type is *declared*, in the entry point's local table
(§4.3), so the verifier knows what `LOAD.L 3` pushes without being
told twice. WebAssembly makes the same choice for the same reason.

Locals are slots (§1.2) and carry a validity state like any value. A
local that has not been written is `unavailable` on first read — never
uninitialized memory.

### Host access

| Opcode | Instruction | Size | Effect | |
|---|---|---|---|---|
| `0x08` | `LOAD.H idx8` | 2 | `→ T` | reads host entity `idx8` |
| `0x09` | `STORE.H idx8` | 2 | `T →` | writes host entity `idx8` |
| `0x0A` | `CALL.H idx8` | 2 | `T… → T?` | calls host function `idx8` |

Types come from the `HOST` table (§4.4), resolved at load. A host read
may deliver any validity state — `unavailable` for an entity with no
current reading is the ordinary case, not an error. A host write
carries the value's state through to the host, which is how an embedder
can distinguish "the script decided nothing was known" from "the script
computed zero".

`CALL.H` consumes as many slots as the declared signature has
parameters, leftmost pushed first, and pushes the return value if there
is one.

### Stack

| Opcode | Instruction | Size | Effect |
|---|---|---|---|
| `0x0B` | `DROP` | 1 | `T →` |
| `0x0C` | `DUP` | 1 | `T → T T` |

`DUP` is the one instruction that pushes more than it pops, and it is
therefore the one exception to the sentence in §1.2 — stated here
rather than hidden, because the verifier's arithmetic has to know. Its
effect is `+1` and statically known, which is all the depth computation
requires.

There is no `SWAP`. Code generated from an expression tree does not
need one, and its absence keeps the verifier's job smaller.

### `i32` arithmetic

| Opcode | Instruction | Effect | Notes |
|---|---|---|---|
| `0x10` | `ADD.i32` | `i32 i32 → i32` | wraps |
| `0x11` | `SUB.i32` | `i32 i32 → i32` | wraps |
| `0x12` | `MUL.i32` | `i32 i32 → i32` | wraps |
| `0x13` | `DIV.i32` | `i32 i32 → i32` | `invalid` on zero divisor and on `INT32_MIN / -1` (§1.5) |
| `0x14` | `REM.i32` | `i32 i32 → i32` | `invalid` on zero divisor; `INT32_MIN % -1` is `0` |
| `0x15` | `NEG.i32` | `i32 → i32` | wraps; `-INT32_MIN` is `INT32_MIN` |

All of them propagate validity as the maximum of their operands
(§1.3), and the cases above produce `invalid` regardless of that.

Operand order is the order of the pushes: for `a - b` the compiler
pushes `a` then `b`, and `SUB.i32` computes second-from-top minus top.

### `i32` comparison

| Opcode | Instruction | Effect |
|---|---|---|
| `0x18` | `EQ.i32` | `i32 i32 → bool` |
| `0x19` | `NE.i32` | `i32 i32 → bool` |
| `0x1A` | `LT.i32` | `i32 i32 → bool` |
| `0x1B` | `LE.i32` | `i32 i32 → bool` |
| `0x1C` | `GT.i32` | `i32 i32 → bool` |
| `0x1D` | `GE.i32` | `i32 i32 → bool` |

All six exist rather than two plus operand swapping, because there is
no `SWAP` and because a jump table entry is cheaper than the code that
would avoid it.

A comparison propagates validity like any other operation: comparing
against an `unavailable` reading yields an `unavailable` `bool`, which
is a value that cannot reach a branch (§1.3.1). This is the mechanism
behind "an absent value may travel through arithmetic but may not
reach a decision".

### `bool`

| Opcode | Instruction | Effect |
|---|---|---|
| `0x1E` | `NOT` | `bool → bool` |

There is no `AND` or `OR` instruction. The language's `and` and `or`
short-circuit, which makes them control flow, and the compiler lowers
them to branches. That is not merely an encoding convenience: it means
`sensor_a.ok and temp > 25` does not evaluate the comparison when the
first operand is false, so an absent `temp` cannot poison an expression
whose answer was already determined.

### Branches and return

| Opcode | Instruction | Size | Effect | |
|---|---|---|---|---|
| `0x20` | `JMP off16` | 3 | `→` | unconditional |
| `0x21` | `JMP_IF_FALSE off16` | 3 | `bool →` | branches when the popped value is false |
| `0x22` | `JMP_IF_TRUE off16` | 3 | `bool →` | branches when it is true |
| `0x23` | `RET` | 1 | `→` | ends the current function or entry point |
| `0x24` | `RET_V` | 1 | `T →` | ends it, yielding the popped value |

**Both conditional branches require their `bool` to be `valid`
(§1.3.1).** A non-valid condition is a fault, not a branch taken by
default.

**A backward jump is allowed only under the bound of §3.8**, and needs
the `loop` group even though the jump itself is a `core` instruction:
what the group declares is that the container contains cycles, which is
the one thing a build without it must be able to refuse at load.

`off16` is measured from the byte after the operand, so `JMP 0` is a
no-op and the encoder never needs a bias.

Short one-byte-offset forms of the three branches are a deliberate
omission. They would save about four bytes on a typical formula and
would double the branch surface the verifier must reason about; the
trade is not worth it in a first version, and the opcode range has room
if measurement later says otherwise.

### Validity

| Opcode | Instruction | Size | Effect | |
|---|---|---|---|---|
| `0x28` | `ELSE` | 1 | `T T → T` | yields the first operand if it is `valid`, otherwise the second |
| `0x29` | `IS_VALID` | 1 | `T → bool` | |
| `0x2A` | `IS_UNAVAILABLE` | 1 | `T → bool` | |
| `0x2B` | `IS_INVALID` | 1 | `T → bool` | |

`ELSE` takes the value first and the fallback second, and both must
have the same type. It catches **both** non-valid states (§1.3.1); the
result carries the state of whichever operand it yielded, so a fallback
that is itself absent does not silently become valid.

The three predicates accept any type, always produce a `valid` `bool`,
and are the only way a script can inspect a state rather than
propagate it. They are what makes §1.3.1's fault avoidable: a script
that wants to handle an absent sensor explicitly can.

## 3.4 The `i64` and `i64div` groups

| Opcode | Instruction | Effect |
|---|---|---|
| `0x40` | `CONST.i64 idx8` | `→ i64`, from the pool |
| `0x41`–`0x43` | `ADD` `SUB` `MUL` `.i64` | as `i32`, 64-bit |
| `0x46` | `NEG.i64` | as `i32`, 64-bit |
| `0x48`–`0x4D` | `EQ` `NE` `LT` `LE` `GT` `GE` `.i64` | `i64 i64 → bool` |
| `0x50` | `EXTEND.i32_i64` | `i32 → i64`, sign-extending |
| `0x51` | `WRAP.i64_i32` | `i64 → i32`, keeping the low 32 bits |

There is no small-immediate form for `i64`: a 64-bit literal small
enough to inline is better written as an `i32` and extended, which the
compiler does.

`WRAP` truncates silently rather than producing `invalid` on overflow.
It is the explicit "I want the low half" operation; a script that wants
a range check writes one.

`0x44` and `0x45` are unassigned. Division moved out of this range when
it became its own group, and the gap is left where it was rather than
closed, so that a reader of an older document lands on nothing instead
of on something else.

### The `i64div` group

| Opcode | Instruction | Effect |
|---|---|---|
| `0xB0` | `DIV.i64` | as `DIV.i32`, 64-bit; `invalid` on zero divisor and on `INT64_MIN / -1` |
| `0xB1` | `REM.i64` | as `REM.i32`, 64-bit; `invalid` on zero divisor, `0` for `INT64_MIN % -1` |

Two instructions in a group of their own, which needs a reason.

64-bit division is the only arithmetic in this instruction set that a
32-bit processor cannot do in registers. Every other operation here
lowers to a handful of instructions; this one lowers to a call into the
compiler's support library, and that routine is **larger than the rest
of the `i64` group put together**. Measured on Cortex-M33, dropping
`i64div` from a complete build removes 1,108 bytes — 698 of them the
support routine — while the other thirteen `i64` instructions cost 376
between them.

Keeping the division in `i64` would therefore mean that any device
wanting 64-bit *comparison* — a timestamp, an energy counter, a
millisecond duration — pays three times over for an operation it is
unlikely to perform. Splitting it is what makes `i64` affordable, and
that is a stronger reason than the two opcodes suggest.

A container requiring `i64div` requires `i64` as well (§3.2).

## 3.5 The `float` group

| Opcode | Instruction | Effect |
|---|---|---|
| `0x60` | `CONST.f32 idx8` | `→ f32`, from the pool |
| `0x61`–`0x65` | `ADD` `SUB` `MUL` `DIV` `NEG` `.f32` | IEEE-754 binary32 (§1.5) |
| `0x68`–`0x6D` | `EQ` `NE` `LT` `LE` `GT` `GE` `.f32` | `f32 f32 → bool` |
| `0x70` | `CONVERT.i32_f32` | `i32 → f32`, round-to-nearest-even |
| `0x71` | `TRUNC.f32_i32` | `f32 → i32`, toward zero; `invalid` if NaN or out of range |

There is no `REM.f32`: it would pull `fmodf` and its libm dependency
onto a device that may have neither, for an operation formulas do not
use.

Float division by zero follows IEEE-754 and produces an infinity, not
`invalid` — this differs from integer division on purpose, because
IEEE-754 has a defined answer and integers do not. NaN is likewise a
`valid` NaN value and not the `invalid` state (§1.5).

`TRUNC.f32_i32` producing `invalid` rather than an implementation-
defined value is the single most important line in this group: C leaves
an out-of-range float-to-integer conversion undefined, so a C backend
that emitted a bare cast would diverge from the VM on exactly the input
a faulty sensor produces.

## 3.6 The `call` group

| Opcode | Instruction | Size | Effect |
|---|---|---|---|
| `0x80` | `CALL idx8` | 2 | `T… → T?` — calls function `idx8` |

Arguments are pushed leftmost-first and **become the callee's first
locals**; there is no separate transfer. How many there are is the
callee's declared `param_count` (§4.3), and the remaining locals are
`unavailable` on entry (§3.3). `RET_V` yields one value to the caller;
`RET` yields none. From the caller's side a call has the stack effect of
a single instruction, which is why calls compose without special cases.

`RET` and `RET_V` are in `core`, not here: an entry point needs to
return, and an expression-only device that has no functions still has
to end its script and yield its value. Only `CALL` and the frame
machinery behind it belong to this group, so a formula device carries
no call apparatus at all.

Recursion is permitted within a declared cap, and how the cap is
enforced in both backends is §5.4.

## 3.7 The `bits` group

| Opcode | Instruction | Effect |
|---|---|---|
| `0x90`–`0x93` | `AND` `OR` `XOR` `BITNOT` `.i32` | bitwise |
| `0x94` | `SHL.i32` | `i32 i32 → i32`; `invalid` if the count is negative or ≥ 32 |
| `0x95` | `SHR.i32` | arithmetic — the sign bit replicates (§1.5) |

Separated from `core` because the audience this language is for does
not write bit manipulation, and a formula device should not carry
instructions for it. There are no `i64` bitwise operations in this
version.

## 3.8 The `loop` group

| Code | Mnemonic | Size | Stack | Effect |
|---|---|---|---|---|
| `0xA0` | `LOOP.GUARD` | 2 | `→` | decrements the `i32` local named by `idx8`; a result below zero is the `iteration_limit` fault (§5.5) |

**The group contains one instruction, and repetition is not it.**
`JMP` already carries a signed offset, so a backward branch needs no
encoding this specification does not have. What a build without `loop`
lacks is not the ability to jump backwards but the *bound* — and since
running a cycle unbounded is exactly the outcome the bound exists to
prevent, such a build must refuse the container rather than do its
best. That is why a container with a cycle requires the group.

`LOOP.GUARD` touches the operand stack not at all. Its counter is an
ordinary local, set by ordinary instructions, and that is a deliberate
choice over runtime-owned machinery: a local costs the frame nothing it
was not already paying, nests correctly because the producer zeroes it
on entry, and lowers to a plain countdown in generated C. A counter
never given a value is zero (§5.3), so it faults on the first turn —
the safe direction for the default to fail in.

### 3.8.1 What makes a cycle conforming

Two properties, and a conforming container has both for every backward
branch:

1. **The branch lands on a `LOOP.GUARD`.** Not merely somewhere inside
   the body — *on* it. A guard reached only on some paths through the
   body would not run on every turn, and then it would bound nothing.
2. **Nothing in the loop assigns the guard's counter.** The body may
   read it; a `STORE.L` to it inside the loop restarts the countdown
   and the bound never arrives.

Together they are a termination proof, and the shape of that proof is
worth stating because it explains what is *not* required. Each turn of
the cycle runs the guard exactly once; the guard strictly decreases an
`i32` that the cycle does not otherwise change; an `i32` is finite.
Termination therefore follows without anyone evaluating the bound.
Nothing reads the number to decide whether it is reasonable, no
implementation carries a maximum, and a data-dependent iteration count
is perfectly conforming — the count decides how many turns happen, the
counter decides how many turns *can*.

This is the same arrangement as the recursion cap (§5.4), for the same
reason: a bound is a statement about the worst case, and whether a
particular run reaches it is data. Both are therefore enforced while
running, in both backends, and both keep the property that a runtime
counts only what a specific instruction tells it to — never
instructions in general.

### 3.8.2 What this does not add

There is still **no execution budget**: no per-instruction counter, no
per-opcode cost, nothing in the dispatch loop (§5.6). That was the
expensive reading of "bound the program", and it is the one this
specification continues to refuse. A guard is paid for by the loop that
asked for it, and a container without cycles pays nothing.

## 3.9 A worked example

`fan.speed = match temp { > 28°C -> 3, > 25°C -> 2, else -> 0 }`, with
the home profile normalizing temperature to tenths of a degree, so
`28°C` compiles to `280`:

```
        LOAD.H 0            ; temp                     [i32]
        CONST.i32.s16 280                              [i32 i32]
        GT.i32                                         [bool]
        JMP_IF_FALSE +5 → L1                           []
        CONST.i32.s8 3                                 [i32]
        JMP +16 → end                                  [i32]
L1:     LOAD.H 0                                       [i32]
        CONST.i32.s16 250                              [i32 i32]
        GT.i32                                         [bool]
        JMP_IF_FALSE +5 → L2                           []
        CONST.i32.s8 2                                 [i32]
        JMP +2 → end                                   [i32]
L2:     CONST.i32.s8 0                                 [i32]
end:    STORE.H 1           ; fan.speed                []
        RET
```

33 bytes, maximum stack depth 2. The depth is what goes in the entry
point's record (§4.3), and what a verifier recomputes rather than
believes (§2.6 point 5).

The `JMP +2 → end` before `L2` is not removable, even though `end`
follows: without it, execution would fall into `L2` and push a second
value, leaving `STORE.H` to write the `0`. Only the last arm of a
ladder can fall through. A peephole pass that removes jumps to the
immediately following instruction is worth having; it does not apply
here.

If `temp` is `unavailable`, `GT.i32` yields an `unavailable` `bool` and
`JMP_IF_FALSE` faults (§1.3.1) rather than quietly selecting `0` — the
fan does not get switched off because a sensor had not reported yet.
A script that wants a defined answer in that case writes it:

```
fan.speed = match temp else 20°C { > 28°C -> 3, > 25°C -> 2, else -> 0 }
```

which inserts `CONST.i32.s16 200` and `ELSE` after each `LOAD.H 0`.
