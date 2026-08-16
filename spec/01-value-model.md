<!--
SPDX-FileCopyrightText: 2026 The MCUScript Contributors
SPDX-License-Identifier: Apache-2.0
-->

# 1. The value model

## 1.1 Types

The bytecode has four types and no others:

| Type | Meaning |
|---|---|
| `i32` | signed 32-bit integer, two's complement, wrapping |
| `i64` | signed 64-bit integer, two's complement, wrapping |
| `f32` | IEEE-754 binary32 |
| `bool` | `true` or `false` |

Types are a property of the *instruction*, not of the value: `ADD.i32`
and `ADD.i64` are different instructions, and a value on the stack
carries no type tag at runtime. The type of every stack position is
instead known statically, and the load-time verifier proves it (§2.6).
This is WebAssembly's arrangement, and it is what lets the runtime be
untagged without being unsafe.

**Deliberately absent, with reasons:**

- **Unsigned integers.** They double the comparison, division and shift
  instructions to serve a need the audience does not have. A user
  writing a threshold does not think in unsigned.
- **`f64`.** The target class has single-precision hardware
  (Cortex-M4 and M33 FPUs are 32-bit); a double would be software-
  emulated, would double the constant pool for every literal, and
  buys precision nobody writing a sensor calibration is short of. Wren
  was passed over partly for making the opposite choice.
- **Narrow integers (`i8`, `i16`).** Storage width is the *host's*
  business — an entity may well be a byte on the wire. Inside the VM
  everything widens to `i32`, which is what the arithmetic would do
  anyway.
- **Strings, arrays, any aggregate.** Nothing here allocates (§1.2).
  These arrive, if they arrive, with a heap, and a heap arrives with
  decisions this document is not ready to make.

`bool` is a separate type rather than an integer that happens to be 0
or 1. It costs nothing at runtime — a `bool` occupies a slot like
anything else — and it buys two things: the verifier can prove that a
conditional branch is fed a condition, and a diagnostic can say *"this
is a temperature, and `if` needs a yes-or-no"* instead of complaining
about integers.

## 1.2 Slots

The operand stack and the local variables of a frame are arrays of
**slots**. A slot is **8 bytes, 8-byte aligned, and holds exactly one
value of any type.** An `i32` occupies a full slot; so does a `bool`.

The obvious alternative was a 4-byte slot with `i64` spanning two, as
the JVM does. It was rejected, and the reason is worth recording
because the usual argument (RAM) turns out not to apply here.

Scripts are event-driven and run to completion without re-entrancy, so
a device needs **one** operand stack, sized to the static maximum over
every script it carries — not one per script. The difference between
4-byte and 8-byte slots is therefore tens of bytes on the whole device.
For that price the two-slot model would have brought: values that
occupy two slots and must not be split across a frame boundary, a
`dup2`/`pop2`/`swap2` family shadowing the single-slot one, a verifier
that tracks not just "how deep" but "is this position the second half
of something", and the loss of the plainest invariant in the machine —
that an instruction consumes some slots and produces at most one.

The rule survives literally instead:

> Every instruction pops a statically known number of slots and pushes
> at most one.

`DUP` is the single exception, pushing two where it popped one, and it
is written down as one (§3.3) rather than quietly widening the rule.
Its effect is still statically known, which is all the arithmetic below
actually needs.

That sentence is what makes the compiler's stack-depth computation, the
verifier's recomputation of it, and the static allocation of the stack
all straightforward. It is worth more than the
bytes. eBPF makes the same trade for the same reason, on hosts that are
frequently 32-bit.

**The slot width is fixed by this specification and is not a build
option.** Parameterising it would make the same container behave
differently on two devices, which defeats the point of having a
container at all.

## 1.3 Validity: `valid`, `unavailable`, `invalid`

Every value carries, alongside it and not inside it, a **validity
state**:

| State | Ordinal | Means |
|---|---|---|
| `valid` | 0 | an ordinary value |
| `unavailable` | 1 | there is no value yet — the sensor has not been read, the device is asleep, the remote node is unreachable |
| `invalid` | 2 | there is a value and it must not be used — the sensor reports a fault, the reading is outside the physically possible, a computation was undefined |

The distinction is not decoration. *Unavailable* is expected and
temporary and a substitute is usually the right response; *invalid* is
a defect, and quietly substituting for it hides the defect. Languages
that collapse both into one `null` are why smart-home templates are
fragile.

**Propagation is the maximum of the operands' ordinals.** An operation
on `valid` operands produces `valid`; touch one `unavailable` operand
and the result is `unavailable`; touch an `invalid` one and the result
is `invalid`, whatever else was involved. A defect outranks a wait,
because a defect is the more informative thing to report.

This is deliberately branchless. In the VM it is one `max` over two
small integers; in generated C it is the same over two `uint8_t`
companions, which the compiler removes wherever it can prove the value
is valid. Neither backend pays for a branch, and neither can drift from
the other, because there is nothing to get subtly wrong.

Certain operations produce a state regardless of their operands:
integer division or modulo by zero produces `invalid` (§1.5), and a
host read of an entity that has no current reading produces
`unavailable` (§1.4).

**The representation is a companion, not a payload.** The alternative —
reserving sentinel values such as `INT32_MIN` — was rejected because a
sentinel collides with real data in principle and every arithmetic
instruction would have to test for it; and because `f32` would then use
NaN payloads while integers used something else, so the two would need
different rules. A companion is uniform, is two bits wide, and costs
one `max` per operation.

A VM keeps the states in a parallel array over the stack and locals; a
C backend keeps a companion variable per value. Both are the same
lattice and the same propagation rule, which is what the specification
actually requires — the storage is an implementation matter.

### 1.3.1 Where a state must be resolved

A validity state may travel through arithmetic indefinitely, but it may
not reach a decision:

> **An instruction that consumes a `bool` to choose control flow
> requires that `bool` to be `valid`.** If it is not, the script faults
> (§5.5).

`if temp > 25 { … }` with an unread sensor does not silently take the
false branch. Silently taking a branch is how an absent reading becomes
a wrong action, and a wrong action on a heating system is worse than no
action. The script is expected to resolve the absence first, and the
language makes that cheap:

```
fan.speed = if temp else 20 > 25 { 3 } else { 0 }
```

`else` yields its right operand when the left is not `valid` — for
**both** states. That is deliberate: a user reaching for `else` wants a
usable number, and forcing them to write two different fallbacks for
two kinds of absence would be pedantry at exactly the wrong moment.
Scripts that genuinely need to tell them apart have explicit
predicates for it, and the *diagnostics* keep the distinction whether
or not the script does — a device can report "sensor faulted" rather
than "sensor not ready" because the state survived the arithmetic.

## 1.4 Units are compile-time only

A literal may carry a unit suffix (`5min`, `24.5°C`, `75%`), and the
compiler normalizes it to its dimension's base unit. **After
compilation no unit exists.** The container holds bare integers, the
instruction set has no notion of dimension, and the VM never converts
anything. This is what makes units free at runtime, which is what makes
them acceptable on a battery device.

Which dimensions exist, how their suffixes are spelled and what each
normalizes to is a **profile**, not part of this specification. What
this specification fixes is that the profile is part of the ABI:

> The value a host delivers for an entity is in the profile's base unit
> for that entity's dimension, and the compiler assumed exactly that
> when it emitted the code.

Change a base unit — milliseconds to microseconds, say — and every
container compiled against the old one is silently wrong: nothing
crashes, nothing warns, the numbers are just a thousand times off. The
container therefore pins the profile's identity and version in its
header, and a mismatch is a refusal at load (§2.4), not a best effort.

The one base unit this specification does fix, because the language
itself uses it, is time: **`i64` milliseconds**. Millisecond resolution
with a 32-bit base would overflow after about 24.9 days, which is not a
lifetime for a device that is expected to run for years.

## 1.5 Numeric semantics

Both backends must agree bit for bit, so every case C would leave to
the implementation is decided here instead.

**Integers.** All arithmetic is two's complement and **wraps** on
overflow. Signed overflow is undefined behaviour in C, so a conforming
C backend must not simply emit `a + b` on signed types; it computes in
the unsigned type of the same width and converts back, which is
well-defined and compiles to the same instruction.

| Case | Result |
|---|---|
| overflow in `+`, `-`, `*` | wraps, two's complement |
| `a / 0`, `a % 0` | `invalid` |
| `INT_MIN / -1` | `invalid` (the mathematical result is not representable) |
| `INT_MIN % -1` | `0` |
| `a / b` otherwise | truncated toward zero |
| `a % b` otherwise | sign of the dividend, so that `(a/b)*b + a%b == a` |
| shift count `>=` the width, or negative | `invalid` |
| right shift of a negative value | arithmetic — the sign bit is replicated |

Division by zero yields `invalid` rather than faulting because it is
overwhelmingly the consequence of a sensor reading that happened to be
zero, and a value the user can handle with `else` is better than a dead
script.

**Floating point.** `f32` is IEEE-754 binary32 with round-to-nearest,
ties-to-even, and no other rounding mode. Denormals behave as IEEE-754
requires; flush-to-zero is not permitted. NaN is produced where
IEEE-754 produces it and is a `valid` NaN value, *not* the `invalid`
state — the two are different things and conflating them would lose the
distinction the state model exists for.

Bit-identity across the two backends does not follow from the above
alone, because it depends on how the embedder's toolchain compiles the
generated C. Two requirements therefore fall on a conforming C backend
and on the build around it:

1. **No contraction.** `a*b + c` must be two roundings, never a fused
   multiply-add. The generated source carries
   `#pragma STDC FP_CONTRACT OFF` for compilers that implement it, and
   **a conforming build passes `-ffp-contract=off`**, because GCC does
   not implement the pragma — it warns that the pragma is ignored and
   contracts anyway.

   This was measured rather than argued. On x86-64 with `-mfma`, the
   program `a*b + c` for `1e20`, `1e20`, `-inf` produces **NaN**
   interpreted and **-inf** compiled: the product overflows to infinity
   and `inf + -inf` is NaN, while a fused operation never forms the
   intermediate that overflows. That is not a difference in the last
   digit; it is a different kind of number. GCC's default is
   `-ffp-contract=fast` under `-std=gnu*` and `on` under `-std=c*`, so
   the same source diverges or does not depending on a flag nobody
   thinks about.

   It is worth being precise about why storing every intermediate is
   not enough by itself: `fast` contracts across a store as readily as
   within an expression. The lowering helps against *excess precision*;
   only the flag helps against contraction.
2. **No `-ffast-math`.** It implies contraction and it flushes
   subnormals to zero — measured: the smallest normal times 0.5 is
   `0x00400000` interpreted and `0x00000000` under `-ffast-math`. Any
   flag enabling flush-to-zero is likewise incompatible. Generated
   translation units `#error` on `__FAST_MATH__`, which is the one of
   the two a compiler will admit to.

Both requirements land on the **build**, not only on the generated
file, and a conforming C backend is one that ships with the flags it
needs rather than one that hopes for them.

### 1.5.1 Why bit-identity and not a tolerance

The obvious softening — "equal to so many significant digits" — is
worse than it looks, and not because of precision.

**A comparison feeds a branch.** One ULP of disagreement in
`temp > 25.0` is not one ULP of disagreement in the output; it is a
different arm of the ladder and a fan at a different speed. A tolerance
on values gives no bound at all on behaviour, because there is no
tolerance on a `bool`.

**It is also unnecessary.** IEEE-754 defines `+`, `-`, `*` and `/` as
the correctly rounded result of the exact mathematical operation: for
given operands and rounding mode there is exactly one right answer, and
every conforming implementation produces it. Bit-identity is the
*normal* case and the deviations are nameable — contraction, excess
precision, flush-to-zero, and library functions that are not correctly
rounded. This language has no library functions, by the same logic that
kept `REM.f32` out (§3.5).

**And a tolerance cannot express the cases that matter.** NaN is not
within any tolerance of NaN, `+0` and `-0` are bit-different and
numerically equal, and an infinity is not near anything. Those are
exactly the values a faulty sensor produces.

The differential test suite runs every case through both backends, on
the host and on real hardware, with the host forced to single precision
so that a host FPU's wider intermediates cannot mask a divergence.

## 1.6 Reading back what was written

A script always observes the effect of its own writes. If it writes an
entity and then reads it, it reads the value it wrote.

This is independent of *when* the write becomes visible outside the
script. An embedder is free to buffer writes and commit them together
when the script returns — which is the industrial arrangement, and the
reason a controller cut off mid-run leaves a plant consistent rather
than half-updated. It only has to consult its own buffer when the
script reads, which costs it nothing it was not already doing.

The two are separated on purpose. Commit timing is a policy an embedder
should be free to choose; read-back is observable to the script, and a
language that left it open would make the same script behave
differently on two embedders.
