<!--
SPDX-FileCopyrightText: 2026 The MCUScript Contributors
SPDX-License-Identifier: Apache-2.0
-->

# 0009 — The surface syntax, planned whole

- Status: draft — decisions taken and written into `spec/06-syntax.md`;
  no compiler code yet (2026-08-18).
- Date: 2026-08-18

## Context

The specification deliberately did not cover syntax, and said so: *"A
compiler reads source and emits a container; this document describes the
container. The language's grammar gets its own document."* That document
is now `spec/06-syntax.md`, and this records what was decided while
writing it.

Two constraints shaped almost every choice.

**The audience reads uniformity as simplicity.** This language is for
people who write a heating rule, not for programmers, and the thing that
makes a language feel arbitrary to them is not difficulty but
inconsistency — a character that behaved one way in a formula behaving
another in a loop. So the whole surface is planned at once, including
parts that will not be built and parts that will never be built, and
each construct is marked **built**, **planned** or **excluded**. The
product owner chose this scope explicitly over designing only what M3
implements.

**The container is finished and the language must fit it.** Chapters 1
to 5 are implemented in two backends with differential tests. Where the
grammar needed something the instruction set does not have, the honest
answer was to name it rather than to bend the surface around the gap —
and it turned out to need four instructions, all small, all in `core`.

## Decision

### The shape of the language

1. **Braces, no indentation rule, newline or `;` as separator.** A
   script embedded in a YAML field must not change meaning because an
   editor re-indented it, and the one-line and multi-line forms of a
   program must be the same program.
2. **A file that is a single expression is a complete program.** The
   formula and the script are one language: `(sensor.temp - 32) / 1.8`
   compiles to an entry point returning it. This is what makes the
   "90 % of scripts are formulas" audience and the scripting audience
   the same audience, rather than two with a cliff between them.
3. **`on <name>` declares an entry point, `fn <name>(…)` a function.**
   `on` because the shape people actually hold is *something happened,
   so do this*, and because it names the construct correctly — an entry
   point is what a host calls, and what "something" is belongs to the
   host.

### Literals and the characters they cost

4. **Date and time are written `@"2026-08-18 13:25"`.** The `@` marks
   the string as a point in time; without it the same characters are a
   string, obviously and unmistakably. Bare `2026-08-18` was rejected
   because the lexer would have to guess between a date and three
   subtractions, and `#2026-08-18#` because `#` is the comment character
   in every configuration format this audience already uses — which is
   what `#` is spent on here.
5. **The colon comes back.** Because the time is inside quotes, `:`
   never becomes an operator, and it is reserved for optional type
   annotations. This was the deciding practical consequence of 4.
6. **Duration literals are suffix sequences** — `3h 45min`,
   `20 minutes`, `1h30min` — with spaces optional, parts descending in
   magnitude, and abbreviations and spelled-out units both accepted. No
   colon form and no ISO 8601: the first collides with a time of day and
   with division, the second is a machine notation nobody writes by
   hand.
7. **Field order inside `@"…"` is big-endian and fixed.** It is the one
   order that does not depend on which convention the reader holds,
   where `08-09` is August 9th to one and the 8th of September to
   another.

### Operators

8. **`/` is division as a layman means it; `div` and `mod` are the
   integer pair.** `3 / 2` is `1.5`. Two consequences are stated rather
   than discovered: a script that divides needs the `float` group, and
   an `f32` never lands in an integer place implicitly — the refusal
   names `round(…)` and `trunc(…)`.
9. **`and` and `or` do not short-circuit.** Short-circuiting means
   branching on the left operand, and §1.3.1 makes a branch on a
   non-valid value a fault — so the short-circuiting version *dies*
   where the propagating one produces `unavailable` and lets the script
   write `… else false`. This requires **two new `core` instructions**,
   boolean `AND` and `OR`: the set has `NOT` and the `bits` group's
   `AND.i32`, and nothing that takes two `bool`s, so the only lowering
   available today is exactly the branch being refused.
10. **Bitwise operators bind tighter than comparison** — Python's order,
    not C's — and **comparison is non-associative**, so `a < b < c` is a
    syntax error offering `a < b and b < c` rather than a silent
    `(a < b) < c`.
11. **`else` keeps the precedence §1.3.1's example already implied**,
    between the arithmetic levels and comparison, so `if temp else 20 >
    25` applies the fallback to the reading and compares a number.

### Bounds

12. **`limit`, not `max`, is the word for a bound.** `while c limit 600`,
    `fn f(…) limit 5`. One word may not be two things, and of the two
    candidates `max` is the one already in everybody's fingers as a
    function — so `min(a, b)` and `max(a, b)` stay ordinary built-ins
    and the bound gets the noun that means exactly what it does.
13. **`limit` appears exactly where the compiler cannot see how often
    something repeats.** It is required on a recursive function's cycle
    and on `while`, and refused elsewhere. The recursion cap and the
    loop bound are different mechanisms underneath — a declared cap the
    runtime counts, versus an ordinary local the producer decrements —
    and one idea to a reader, which answers ADR 0007's observation that
    they are the same concept with two spellings.
14. **Every loop carries a guard, including `for` over a literal
    range.** This **corrects ADR 0007's Open item**, which proposed
    emitting no guard where the compiler can see the count. That
    proposal contradicts §3.8.1, which requires every backward branch to
    land on a `LOOP.GUARD` — and §3.8.1 is right: the alternative is a
    verifier that proves termination structurally, which is the
    dominator computation §3.8.1 was designed to avoid. For a range the
    bound is the range, the compiler initialises the counter to
    `b - a + 1`, and the cost is one decrement per turn.
15. **`a..b` is inclusive at both ends, everywhere** — `match` arms,
    `for`, and slices. `0..23` is the hours of a day. The half-open
    reading is a programmer's convention and this audience does not hold
    it; collections are iterated directly (`for x in window`) rather
    than through an index, which is also what Pane & Myers found people
    reach for.

### Validity in the surface

16. **`match` carries validity**, with `unavailable` and `invalid` arms
    beside the value arms, and it may **produce** a non-valid value —
    `invalid -> invalid` — which is how a script refuses to turn a
    faulted reading into a number somebody will later mistake for a
    measurement. Without a validity arm, a non-valid subject yields that
    same state without any arm being evaluated.
17. Both halves of 16 need **two more `core` instructions**,
    `CONST.unavailable <type>` and `CONST.invalid <type>`. No
    instruction today produces a *chosen* state: states arise as a side
    effect of an operand, of a host read, or of an undefined arithmetic
    case such as division by zero — none of which is a way to say *this
    one is invalid, deliberately*.
18. **`a is valid` / `is unavailable` / `is invalid`, with `is not`.**
    The result is a `bool` that is itself always valid whatever the
    operand is, which is what makes it safe to branch on — and it is
    the frame a compiler wraps around any lowering that would otherwise
    branch on a value.
19. **`try` / `catch` is planned, and its gate placement is already
    fixed**: control leaves for the `catch` at the **first** operation
    whose result is not valid. That has to be pinned rather than
    optimised, because where an `unavailable` and an `invalid` arise in
    one block, which the `catch` sees depends on which operation
    stopped it. It is planned rather than built because it is the only
    construct that costs a test after every operation in a value model
    built to propagate validity without branching, and `else` and
    `match` cover the cases scripts have.

### Names, state and the closed world

20. **`let` introduces a local, and assigning to an undeclared name is
    an error** carrying the nearest declared name. Without a
    declaration form a mistyped name silently becomes a second variable
    and the script reads correctly while doing nothing.
21. **Assignment is a statement and never an expression**, so `if x = 5`
    is a syntax error that explains `=` and `==`.
22. **A dotted name is one import name**, looked up whole; the dot is a
    character and not an operation. `sensor` alone is not a value, and
    saying so is a diagnostic, because the reader who tried it was
    thinking of objects.
23. **A script keeps nothing between invocations.** No globals, no
    persistent variables. State that survives must be sized,
    initialised, migrated when a script is replaced and preserved across
    a reboot, and the component that already does all four is the host,
    through an entity.
24. **Dynamic dispatch, function pointers and closures are excluded
    permanently**, not deferred. The recursion cap and the loop bound
    are computed from a call graph the compiler sees whole; an indirect
    call destroys that graph and with it the property this language
    sells. Inheritance is planned only as a closed world.
25. **Built-ins are closed by a rule**, not by a list: a built-in is
    admissible only if it lowers to instructions and reads nothing
    outside its own operands. `round`, `trunc`, `abs`, `min`, `max`
    qualify; anything touching the world is a host import (ADR 0008).
    A built-in propagates validity like an operator, which puts the
    obligation on the compiler to find a lowering that does not branch
    on a non-valid value — and is why `round`, `trunc` and `abs` are
    built while `min` and `max` are planned: with one operand the
    fallback arm is the operand itself, and with two it has to
    construct a state.

### Diagnostics

26. **Three obligations on a conforming compiler** (§6.7): name the
    thing and say what to do, with the nearest known names; never cite
    the specification in a message; say what was expected in the words
    of the language. Nothing in `spec/corpus/` can check these, and they
    are in the specification because most of the rules above exist to
    make an error possible where another language would have produced a
    plausible wrong answer — which is worth nothing if the message is
    not worth reading.

## Consequences

- **`spec/06-syntax.md` exists** and the README's "not specified"
  list loses its first entry — with the nuance kept: the grammar is
  normative for *this* language, and a conforming **compiler** is still
  defined by the containers it emits, so a second front end with a
  different syntax remains legitimate.
- **Four `core` instructions are owed before M3 can compile what this
  chapter marks built.** They are small and they are the only container
  change the built language needs. Two more additions — an arena for
  arrays, a string constant area — are named for planned constructs and
  are not owed yet.
- **ADR 0002 §8 question 3 is answered**, including the ternary
  conflict of §3.2, in favour of §2.5: there is no `? :`, and the
  if-expression is the conditional.
- **ADR 0007's Open item on who writes the loop bound is answered** and
  its proposal corrected — see decision 14.
- **`while` costs a reserved word and no code.** So do `try`, `catch`,
  `:` and `[`. That is the whole price of planning the surface whole,
  and it is paid up front on purpose: a word that is free today and
  needed tomorrow is a word somebody will have used as an entity name
  in between.
- **The first-guess test now has something to test.** ADR 0002 §2.9
  names it as the most productive method available and it needs a
  concrete syntax to run against; this is that syntax, before a line of
  compiler code makes it expensive to change.

## Open

- **`i64` literals have no spelling of their own.** A number is `i32`
  unless its profile's dimension says otherwise, which covers the case
  that motivated `i64` and leaves dimensionless 64-bit arithmetic with
  no way to ask for it. Whether that case exists is a question for a
  real script.
- **Multi-file compilation** is the producer's command line and not a
  module system (§6.12). Nothing here says how names from two files
  meet, because nothing yet needs two files.
- **The percent base unit** (ADR 0002 §8 question 6) is untouched and
  still a profile question for M4.
- **§8 questions 10 and 11 remain unevidenced** — that static inference
  suits non-developers, and that 90 % of scripts are formulas. Decision
  2 is deliberately shaped so that the second being wrong costs nothing:
  the formula is not a special mode, it is a program.
