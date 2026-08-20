<!--
SPDX-FileCopyrightText: 2026 The MCUScript Contributors
SPDX-License-Identifier: Apache-2.0
-->

# 0011 — The code generator, and what writing it settled

- Status: draft — decision taken, implemented and differentially tested
  (2026-08-19).
- Date: 2026-08-19

## Context

M3's last step. The parser reads a script (ADR 0009), `sema` types and
dimensions it, and this turns that into the bytes of chapters 2 to 4 —
so that for the first time a **script** can be checked against the
project's promise, rather than a container somebody wrote by hand.

Writing it did what writing the parser and the analyser did before it:
it found things in the chapter and in the stage below that were wrong,
and each of those is a decision here rather than a patch there.

## Decision

### 1. The generator reads the analysis and re-derives nothing

A literal's value in base units, which import a dotted name turned out
to be, every node's type and dimension: all of it comes from `Analysis`.
Where the generator needed something the analyser had not recorded, the
recording was added there. Two stages that both work out what an
expression means is exactly the drift this project cannot afford, and
the temptation is strongest in the small cases — a unit factor is two
lines to recompute.

### 2. `return` is part of a function's type

`sema` inferred a function's type from its last expression alone, so

```
fn f(x) {
  if x > 0 { return 1 }
  return 2
}
```

was a function that yields **nothing** — and the generator would have
emitted `ret_v` into a `void` record, which the verifier refuses. The
fix is in the analyser: every way out of a body is collected and they
must agree, where "falling off the end" is a way out exactly when
control can reach it. That last part is `falls_through`, and it is
shared with the generator, which asks the same question to decide
whether to emit a trailing `ret`.

### 3. Recursion is inferred in two passes, not one

`return down(n - 1) + n` is the ordinary shape of a recursive function
and the old single pass could not type it: the call has no type yet and
it stands inside arithmetic that needs one. The pass now unwinds when it
meets its own function's type, keeps the way out it had already found —
the arm that does **not** recurse — and reads the whole body again with
that in place. So the recursive arm is checked rather than assumed.

**The way out is as often an arm as a `return`**, and it may be written
*after* the arm that recurses:

```
fn f(n) limit 5 { if n > 0 { f(n - 1) + 1 } else { 0 } }
```

Here the pass unwinds before the base case has been read at all, so `if`
and `match` read the arms they had not reached yet and hand whatever
those yield to the second pass. An arm that unwinds in turn is simply
not the way out. A function where no arm is one — `fn f(n) { f(n - 1) +
1 }` — is refused, naming it.

Mutual recursion needs the same trick one level out: a function whose
only value comes from a call into the cycle stays *pending* rather than
being called `void`, and is worked out again once the cycle has an
answer. A function that never resolves is an error naming it — "calls in
a circle with no way out" — and not a guess.

### 4. A unit written at one end of a range covers both

`24..28°C` is the form §6.3.5 prints, and it was a type error: a bare
numeral cannot become a temperature on its own, because a dimension is a
type and adopting one silently is what §1.4 exists to prevent. The rule
is now written down (§6.3.8): the suffix is *lent* to the other end.
`0..9` stays two plain numbers, and two units at both ends must agree,
which is the ordinary rule.

### 5. What is written out rather than added to the instruction set

Three lowerings could have been opcodes and are not.

| Construct | Lowering |
|---|---|
| `a == b` on two `bool`s | `(a and b) or (not a and not b)` |
| `abs(x)` | a comparison and a `neg` |
| rounding to nearest, away from zero | half the divisor added in the operand's own direction, then the truncating divide |

Each is a handful of instructions a compiler can write, and an opcode
for it would be one per type in a set that pays for every entry in
dispatch-table bytes (ADR 0004 §4.9). The `bool` case is the
interesting one: the equality is exact including validity, because
propagation is a maximum and a maximum does not care that each operand
is read twice.

**The other two need a guard, and the first version of this did not have
one.** Both branch on the sign of their operand, and a branch on a
non-valid `bool` is a fault (§1.3.1) — so `abs(temp)` with an unread
sensor *died* where §6.3.9 says it must answer `unavailable`. The
chapter had already written down the remedy, in the sentence the
lowering ignored: *"a lowering that branches on the operand is wrong
even where it is obvious. The available pattern is to branch on a
predicate instead."* Every branchy built-in now sits inside `is_valid`,
whose answer is valid whatever it is given, and the arm for an absent
operand carries the value through unrounded — right type, right state,
and a payload nothing may look at.

This is a rule rather than three fixes: **a lowering may branch on a
condition the script wrote, or on a predicate, and on nothing else.**
`if` and `match` branch on what the script wrote, and faulting there is
§1.3.1 working as designed.

### 6. A conversion is one exact rational, and where it is computed matters

`to_i32(temp, °C, 100)` and its three siblings are `(v − offset) ×
scale` with both halves exact, and they lower to `(v × N + M) / D` with
three integer constants. Writing it as one rational is what lets a unit
with an **offset** work at all: `°F` shifts by −16000/9 base units,
which is not a number an integer machine can subtract, and folding it
into the constants is exact.

Where the arithmetic happens is the other half, and getting it wrong was
a real defect in the first version. A conversion **to `f32` converts
first** and scales in decimals; scaling in whole numbers divided 2650 by
100 and handed back `26.0` where §6.3.10 promises `26.5` and says
`to_f32` rounds nothing at all. A conversion to a whole number scales in
whole numbers and rounds once, at the divide.

### 7. The loop variable is not assignable

§6.4.4 says the variable is bound afresh each turn; the analyser now
enforces it. Assigning to it would say something the loop does not do —
the guard still counts down, so it is a language rule and not a
container one.

### 8. `limit` reaches every function of its cycle

§6.2.4 lets the declaration stand on any one function of a cycle; §4.3
records a cap per function and a verifier compares them. The generator
condenses the call graph, requires a `limit` exactly where there is a
cycle, refuses one where there is not, refuses two different ones in the
same cycle naming both, and writes the declared number onto **every**
member.

### 9. What the generator refuses, and why each is honest

| Refused | Because |
|---|---|
| `@"2026-08-19 13:25"` | what its fields count from is an epoch, and no profile could state one |
| 64-bit bitwise and shifts | §3.7 says there are none in this version |
| a 64-bit loop range | the guard counts in `i32` (§3.8) |

The first was temporary and is **gone**: ADR 0013 gave a profile a form
to declare its epoch in, and a date literal now compiles. The other two
are the instruction set's shape. None of them is a silently wrong
lowering, which is the property that matters: each is a diagnostic with
a span, from the same machinery a type error uses.

A fourth stood here — `i64` to `f32` in either direction — and it was
wrong. **ADR 0012 replaced it with two instructions**, because a
dimension's data type is the profile's to choose and a refusal would
have made some of those choices second-class.

### 10. The profile is the integrator's, and the command takes a path

Settled by the product owner while this was being written, and it
settles more than the command: **the profile and the registry are
supplied by whoever integrates the language.** For the first embedder
that is MCUHome's job, and how any of them produces one is theirs. What
MCUScript owes is the way in — *"we create, for the mcuscript call,
only the possibility of passing the path to the profile as an argument
or an environment variable."*

So the interface is a path, not a discovery rule, not a search order and
not a default location. The **format** of what sits at that path was
left to the next milestone, and with no path given the command compiles
against an empty profile and an empty registry — which §6.5.4 explicitly
allows — and a unit suffix or a host name is refused by name. That is
still what happens when neither is named; what changed is that they can
be (ADR 0013).

Inventing a format here to make the command more useful would have been
the failure mode this repository is set up to prevent: a format decided
in passing, by the stage that happened to need it first.

## Consequences

- **A script is now covered by the project's central promise.** The
  differential tests compile one and run it on the VM and as generated
  C, over four worlds each — a reading, a cold sensor, a faulted one and
  a value that is not round — and compare the output byte for byte. That
  used to say two backends agree about a container; it now says they
  agree about a **script**.
- Chapter 6's built list is implemented end to end, with the four
  exceptions in point 9.
- `sema` gained two things a compiler needed and a checker did not: what
  each entry point yields, and the type of a call that was pending when
  it was first seen.
- **An adversarial review found six defects and every one of them was a
  lowering, not a design.** Four are recorded above (the two conversion
  faults, the missing validity guard, the base case in an arm); the two
  the review confirmed and this text does not name separately are the
  same conversion defect seen from `to_unit` and from `round`. Each is
  now pinned by a test that fails without the fix. Worth recording
  because of *where* they were: the differential test cannot see any of
  them, since both backends read the same container and a mis-compiled
  script is identically wrong in each. Agreement is a property of the
  backends; a compiler needs expected values, and the table of them is
  the test that matters most in this change.
- The generator is ~900 lines and has no optimiser. A peephole pass, a
  constant folder and a smaller `match` ladder are all available later
  and none of them is needed to answer whether the language works.

## What this does not decide

What a profile file *looks like*. Point 10 fixes who owns one and how it
reaches the compiler; the format, and the same question for the
registry, are ADR 0013's.
