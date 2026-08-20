<!--
SPDX-FileCopyrightText: 2026 The MCUScript Contributors
SPDX-License-Identifier: Apache-2.0
-->

# 0008 — The language owns no dimensions, and therefore no clock

- Status: draft — decision taken, specification edited to it (2026-08-18).
- Date: 2026-08-18

## Context

Specification §1.4 has said since it was written that units are a
compile-time feature whose table belongs to a profile, and then made one
exception:

> The one base unit this specification does fix, because the language
> itself uses it, is time: **`i64` milliseconds**.

That sentence came from a product-owner decision of 2026-08-16
(ADR 0002 §2.11 gap 7), taken while the sketch still assumed the
language would offer a clock of its own. Designing M3 pulled the thread
and it came apart in four places.

**Nothing in the language uses time.** The loop guard counts turns
(ADR 0007); the recursion cap counts entries into a call-graph component
(§5.4); no instruction, no type and no fault mentions a duration. The
stated reason — *because the language itself uses it* — was true of an
earlier design and had become circular.

**A clock is a host import in every design.** The runtime is freestanding
C99 with no time source of its own, so whatever `now()` would have been,
it was always going to be a call out to the embedder. Reserving the name
in the language does not change where the value comes from.

**Reserving a name does not prevent the errors it was supposed to
prevent.** The real failure modes of an embedder's clock are nameable —
a wall clock instead of a monotonic one, so it jumps when NTP lands;
second resolution; a counter that resets on deep sleep. None of the
three is prevented by the name being fixed in a grammar. All three are
caught by a conformance test, which works exactly as well for a
profile-declared import.

**The portability that was wanted comes from a profile, not from the
language.** The argument for reserving `now()` was that a snippet posted
in a forum should work for the person who copies it. That holds — but it
holds because one profile dominates its ecosystem and names the clock,
not because the language does. A container pins its profile anyway
(§2.4), so cross-profile portability of compiled code does not exist to
begin with.

A fifth finding is smaller and sharper. Where a dimension wraps — a
32-bit millisecond clock does, after about 24.8 days in each direction if
comparisons are done as differences — **widening it is unsound**. A wrap
that is invisible in 32-bit arithmetic becomes a jump of −2³² in 64-bit,
silently and with no operation to blame. So a cyclic quantity is not a
number that happens to be narrow; it is a different thing, and a design
that mixes the two by promotion is wrong rather than imprecise.

## Decision

**The language defines no dimension, no unit and no base unit. Not one,
not for time.**

1. **§1.4's exception is deleted.** The specification fixes the
   *mechanism* — a literal may carry a suffix, a suffix belongs to a
   dimension, a dimension normalizes to a base unit, and the base units
   are part of the ABI — and the *table* is a profile's, without
   remainder. What §1.4 still says, and must, is that a profile mismatch
   is a refusal at load.
2. **No built-in that touches the world, so no `now()`.** The admissible
   test is mechanical: a built-in is allowed only if it lowers to
   instructions and reads nothing outside its own operands. `round(x)`
   passes; `now()` does not. This is the same boundary ADR 0001 draws
   everywhere else, applied without an exception for the one case that
   felt convenient.
3. **A profile owns each dimension whole**: its data type, an explicitly
   named base unit, its units with a factor and an optional offset, and
   optionally a mark that the dimension is **cyclic**. Nothing about that
   list is time-specific, which is the point.
4. **The notation is the language's, the meaning is the profile's.** Unit
   suffixes (`5min`, `24.5°C`, `75%`), duration literals (`3h 45min`) and
   date-and-time literals (`@"2026-08-18 13:25"`) are lexical forms the
   grammar defines and assigns no meaning to. A profile that declares no
   matching dimension makes them a compile error naming what is missing —
   not a silently dimensionless number.
5. **A clock ships as a recommended profile fragment**, not as a language
   feature: a dimension definition, an import declaration, a reference C
   implementation over the platform tick, and the conformance test that
   catches the three failure modes above. A profile author copies it.
   That is the artifact the reservation was actually reaching for, and it
   lands where it belongs.
6. **No exception for imports in the unit rules.** A dimensioned value
   and a bare number do not mix, whoever produced the dimensioned one.
   `now() - 500` is refused, and the refusal suggests `now() - 500ms`.
   This was argued the other way — that snippets should stay loose — and
   the argument does not survive contact with §2.6's own example: a bare
   `500` beside a clock is exactly the millisecond-versus-second
   ambiguity units exist to kill, so requiring the suffix makes the
   snippet better rather than more pedantic.
7. **A cyclic quantity never widens.** No implicit promotion to a wider
   type, and no explicit one either. A profile that needs a wider clock
   declares a second, non-cyclic dimension and a second import; it does
   not convert the first.
8. **`i64` keeps its group and loses its privilege.** It is now a data
   type a profile may choose, priced where the embedder can see it:
   measured on a linked image, plain `i64` costs 624 bytes on
   cortex-m33 and 528 on cortex-m0+, and the expensive part is
   `i64div` at 1,080. A profile that picks a 64-bit time base is making
   a paid choice, not collecting a language tax.

## Consequences

- **The whole 32-versus-64-bit tangle leaves the language.** It was never
  a question about slots or instructions; it was a question about which
  data type one dimension should have, and that question now sits in the
  document that owns the dimension. The year-2038 shape of it goes with
  it — a profile states its base unit and its data type together, which
  is the only place the trade-off is visible.
- **A dimensionless mode exists by construction.** A profile that
  declares no dimensions is legal, and then every number in a script is a
  bare number and every suffix is an error. Nothing special had to be
  built for that.
- **The first embedder inherits an obligation.** `profile-home` must
  declare a time dimension, name its base unit, and decide whether its
  clock is cyclic — with §8 question 6 (the percent base unit) now joined
  by the time base as a profile question rather than a specification one.
  Both are answered in its own repository now that there is a form to
  answer them in (ADR 0013).
- **ADR 0002 §2.11 gap 7 is answered rather than carried.** Its problem
  was that a 64-bit time base does not fit the sketch's 32-bit cells;
  §1.2 answered the mechanical half by fixing 8-byte slots, and this
  answers the rest by removing the premise.
- **`spec/README.md`'s "which units exist" bullet is now exactly true**
  rather than true-with-a-footnote.

## Open

- **Whether `profile-home` names its clock `now`** — likely, and its own
  to decide. If it does, every example in this project's documentation
  reads as it always did; what changed is who promises it.
- **Where the recommended fragment lives**, this repository or the
  profile's. It is a toolkit for profile authors, which argues for here;
  it is also the first content of `profile-home`, which argues for
  there. The format exists (ADR 0013), so this is now a question about
  where a file goes rather than about whether it can be written.
