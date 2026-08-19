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

8. **There is one division, spelled `/`, and no `div`.** The first draft
   had both, and the argument that killed the second is the language's
   own: `+` has one spelling and lowers to `ADD.i32` or `ADD.f32`
   according to its operands, and `/` lowers to `DIV.i32` or `DIV.f32`
   in exactly the same way. The instruction set always had that
   symmetry — only the surface language broke it, and no other
   operation in the language has two spellings.
9. **The data type follows the dimension.** A dimensioned result carries
   the data type its profile declared; a result with no dimension
   carries its operands' type, except that a division produces `f32`.
   So `27.9°C / 2` is `13.9°C` in a profile that declares tenths, and
   `7 / 2` is `3.5`.

   This is the decision that makes 8 survivable, and its reasoning is
   not about arithmetic. **A profile's data type and base unit are one
   statement of how fine the quantity is**, made by the one person in
   the chain who can judge it. Truncating to it is not the language
   losing precision; it is the language declining to invent precision
   the profile said does not exist. A profile author who wants the
   half-step declares hundredths instead — once, visibly, where it can
   be reviewed. A bare number carries no such declaration, so there the
   language must choose, and it chooses the answer everyone outside a
   programming language expects.

   Three things fall out and all three are improvements. `round(…)`
   almost disappears, because a dimensioned expression stays in its
   dimension's type all the way to the entity it is written to.
   Dimensioned arithmetic no longer needs the `float` group at all.
   And `current / baseline` on two temperatures is a decimal, because
   the dimensions cancel and nothing is left to declare a resolution —
   which is the one case an earlier operand-typed proposal got wrong.
10. **A dimension is a type, not a decoration on one.** `let x: i32 =
    20°C` is a type error even though the profile stores that
    temperature in an `i32`. A temperature is no more an `i32` than it
    is a kilometre, and the storage a profile chose is not a second name
    for the quantity. Without this rule a dimension would be something
    any assignment could rub off, and the guarantee behind
    `if temp > 5min` would hold for comparison and not for storage.
11. **Type annotations are built, spelled with a colon**, and they
    **pin** a type rather than steering a computation: `let x: i32 =
    27.9°C / 2` is an error, not a quiet truncation. They are almost
    never needed — inference sees the whole program — and the case that
    makes them necessary is a local whose type nothing determines:

    ```
    let total: i64 = 0
    ```

    Without it, `0` is an `i32` and the only way to say otherwise would
    be to assign a fictitious enormous number and overwrite it. This
    answers what this ADR previously listed as open — that `i64` had no
    spelling of its own — and it does so without a literal suffix. The
    colon rather than a prefixed `(i64)`: it is the form this audience
    already meets in YAML, it does not read as a call, and it composes
    onto parameters.
12. **A profile may declare a dimension to be a scale factor**, whose
    units are spellings for a multiplier — `%`, `‰`, `ppm`, whatever
    that profile needs. The language declares none of them and defines
    what one *does*: `x * 5%` scales, and **`x + 5%` and `x - 5%` are
    relative change**, the same as `x * 105%` and `x * 95%`. Writing the
    multiplier out by hand is precisely the arithmetic-in-your-head this
    language exists to remove, and `+5%` is how people write it.

    Three rules keep it unambiguous, and each replaces a guess. **Same
    dimension wins**: `50% + 5%` is `55%`, never `52.5%`. **A bare
    number is not a scale factor**: `x * 1.05` stays legal and
    `x + 0.05` stays an error, because the suffix is what says
    *relative*. **`+` is not commutative here**: `5% + x` is refused,
    since it is not the same expression in the other order but a
    question with no answer.

    This is also the one exception to the rule against multiplying two
    dimensioned values, and it is not really one: a ratio has no
    dimension in the physical sense, so `50% * 50%` is `25%` and
    `27°C * 105%` leaves the temperature a temperature.
13. **Four built-ins cross between a dimension and a number, and the
    second argument is a unit — never a type.** `to_f32(temp, °C)`,
    `to_i32`, `to_i64`, and the inverse `to_unit(n, °C)`. The unit is
    absent whenever the value has no dimension, because the target type
    is already in the name: `to_i64(count)`, and `to_i64(count, i32)`
    says the same thing twice and is refused for it.

    **A third argument divides the unit**, and it is how a script asks
    for a resolution a profile does not spell: `to_i32(temp, °C, 100)`
    counts in hundredths of a degree, `to_i32(power, W, 0.001)` in
    kilowatts. A number literal, whole or decimal, because the compiler
    has to know it.

    Those two arguments together are the decision. A script names a unit
    and a resolution **of its own choosing**, and therefore depends on
    nothing about the profile's internals: a profile that moves from
    tenths to hundredths answers the same expression with the same
    numbers, and one that stores whole degrees answers with `3200` —
    two digits that are there and are zero, which is honest rather than
    rounded. The alternative, an unnamed conversion meaning *the
    base-unit number*, is what §1.4 exists to prevent: such a script
    would silently reinterpret its own numbers the day a base unit
    changed.

    An earlier draft of this decision instead obliged a profile to spell
    its base unit, so that `to_i32(temp, c°C)` could reach it. That
    works and is worse: it makes a script fail loudly on a profile
    change that need not affect it at all, where the factor makes the
    script immune. Immune beats loud.

    **`to_i32` and `to_i64` round by themselves**, to the nearest and
    away from zero on a tie. An earlier draft refused an inexact
    conversion and told the script to write `round(to_f32(…))`; that is
    the language demanding to be told twice, since `to_i32` has already
    said a whole number is wanted. Where the conversion is exact nothing
    is rounded, and the compiler knows which case it is because a base
    unit and a written factor are both constants. `round` and `trunc`
    remain for decimals that were computed rather than converted, and
    for truncation where nearest is not what was meant.

    They need nothing new from the container: a unit factor is a
    compile-time multiply, and the four numeric conversion instructions
    already exist.
14. **`and` and `or` do not short-circuit.** Short-circuiting means
    branching on the left operand, and §1.3.1 makes a branch on a
    non-valid value a fault — so the short-circuiting version *dies*
    where the propagating one produces `unavailable` and lets the script
    write `… else false`. This requires **two new `core` instructions**,
    boolean `AND` and `OR`: the set has `NOT` and the `bits` group's
    `AND.i32`, and nothing that takes two `bool`s, so the only lowering
    available today is exactly the branch being refused.
15. **Bitwise operators bind tighter than comparison** — Python's order,
    not C's — and **comparison is non-associative**, so `a < b < c` is a
    syntax error offering `a < b and b < c` rather than a silent
    `(a < b) < c`.
16. **`else` keeps the precedence §1.3.1's example already implied**,
    between the arithmetic levels and comparison, so `if temp else 20 >
    25` applies the fallback to the reading and compares a number.

### Bounds

17. **`limit`, not `max`, is the word for a bound.** `while c limit 600`,
    `fn f(…) limit 5`. One word may not be two things, and of the two
    candidates `max` is the one already in everybody's fingers as a
    function — so `min(a, b)` and `max(a, b)` stay ordinary built-ins
    and the bound gets the noun that means exactly what it does.
18. **`limit` appears exactly where the compiler cannot see how often
    something repeats.** It is required on a recursive function's cycle
    and on `while`, and refused elsewhere. The recursion cap and the
    loop bound are different mechanisms underneath — a declared cap the
    runtime counts, versus an ordinary local the producer decrements —
    and one idea to a reader, which answers ADR 0007's observation that
    they are the same concept with two spellings.
19. **Every loop carries a guard, including `for` over a literal
    range.** This **corrects ADR 0007's Open item**, which proposed
    emitting no guard where the compiler can see the count. That
    proposal contradicts §3.8.1, which requires every backward branch to
    land on a `LOOP.GUARD` — and §3.8.1 is right: the alternative is a
    verifier that proves termination structurally, which is the
    dominator computation §3.8.1 was designed to avoid. For a range the
    bound is the range, the compiler initialises the counter to
    `b - a + 1`, and the cost is one decrement per turn.
20. **`a..b` is inclusive at both ends, everywhere** — `match` arms,
    `for`, and slices. `0..23` is the hours of a day. The half-open
    reading is a programmer's convention and this audience does not hold
    it; collections are iterated directly (`for x in window`) rather
    than through an index, which is also what Pane & Myers found people
    reach for.

### Validity in the surface

21. **`match` carries validity**, with `unavailable` and `invalid` arms
    beside the value arms, and it may **produce** a non-valid value —
    `invalid -> invalid` — which is how a script refuses to turn a
    faulted reading into a number somebody will later mistake for a
    measurement. Without a validity arm, a non-valid subject yields that
    same state without any arm being evaluated.
22. Both halves of 21 need **two more `core` instructions**,
    `CONST.unavailable <type>` and `CONST.invalid <type>`. No
    instruction today produces a *chosen* state: states arise as a side
    effect of an operand, of a host read, or of an undefined arithmetic
    case such as division by zero — none of which is a way to say *this
    one is invalid, deliberately*.
23. **`a is valid` / `is unavailable` / `is invalid`, with `is not`.**
    The result is a `bool` that is itself always valid whatever the
    operand is, which is what makes it safe to branch on — and it is
    the frame a compiler wraps around any lowering that would otherwise
    branch on a value.
24. **`try` / `catch` is planned, and its gate placement is already
    fixed**: control leaves for the `catch` at the **first** operation
    whose result is not valid. That has to be pinned rather than
    optimised, because where an `unavailable` and an `invalid` arise in
    one block, which the `catch` sees depends on which operation
    stopped it. It is planned rather than built because it is the only
    construct that costs a test after every operation in a value model
    built to propagate validity without branching, and `else` and
    `match` cover the cases scripts have.

### Names, state and the closed world

25. **`let` introduces a local, and assigning to an undeclared name is
    an error** carrying the nearest declared name. Without a
    declaration form a mistyped name silently becomes a second variable
    and the script reads correctly while doing nothing.
26. **Assignment is a statement and never an expression**, so `if x = 5`
    is a syntax error that explains `=` and `==`.
27. **A dotted name is one import name**, looked up whole; the dot is a
    character and not an operation. `sensor` alone is not a value, and
    saying so is a diagnostic, because the reader who tried it was
    thinking of objects.
28. **A script keeps nothing between invocations.** No globals, no
    persistent variables. State that survives must be sized,
    initialised, migrated when a script is replaced and preserved across
    a reboot, and the component that already does all four is the host,
    through an entity.
29. **Dynamic dispatch, function pointers and closures are excluded
    permanently**, not deferred. The recursion cap and the loop bound
    are computed from a call graph the compiler sees whole; an indirect
    call destroys that graph and with it the property this language
    sells. Inheritance is planned only as a closed world.
30. **Built-ins are closed by a rule**, not by a list: a built-in is
    admissible only if it lowers to instructions and reads nothing
    outside its own operands. `round`, `trunc`, `abs`, `min`, `max` and
    the four conversions of decision 13 qualify; anything touching the
    world is a host import (ADR 0008).
    A built-in propagates validity like an operator, which puts the
    obligation on the compiler to find a lowering that does not branch
    on a non-valid value — and is why `round`, `trunc` and `abs` are
    built while `min` and `max` are planned: with one operand the
    fallback arm is the operand itself, and with two it has to
    construct a state.

### Diagnostics

31. **Three obligations on a conforming compiler** (§6.7): name the
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
  its proposal corrected — see decision 19.
- **`while` costs a reserved word and no code.** So do `try`, `catch`
  and `[`. That is the whole price of planning the surface whole,
  and it is paid up front on purpose: a word that is free today and
  needed tomorrow is a word somebody will have used as an entity name
  in between.
- **The four `f32`-adjacent papercuts are gone.** With decision 9,
  dimensioned arithmetic never leaves its dimension's data type, so
  `round(…)` is not needed to store a computed temperature, the `float`
  group is not pulled in by a dimensioned division, and the 24-bit
  mantissa's precision cliff — which would have cost a millisecond
  duration its exactness after about 4.7 hours — does not arise.
- **The first-guess test now has something to test.** ADR 0002 §2.9
  names it as the most productive method available and it needs a
  concrete syntax to run against; this is that syntax, before a line of
  compiler code makes it expensive to change.

## Open

- **The percent base unit and the scale-factor table** are the profile
  format's, and the first profile must answer them (ADR 0002 §8
  question 6). What decision 12 fixes is only what the language does
  with a dimension so marked.
- **A binding declares a dimension, and need not deliver a declared
  unit.** §1.4 says a host delivers an entity's value in the profile's
  base unit for its dimension, and a real sensor does not: it delivers
  whatever scaling its wire format has, which may match no unit the
  profile declares. So the binding format must be able to state its own
  scaling and have the glue convert at the boundary — never the script,
  which would put the profile's internals back into user code. This is
  M4's, and it is the counterpart of decision 13: the script names a
  unit because it must not know the base unit, and the binding states a
  factor because it does not have a unit at all.
- **How a script names an entry point for the host to run later.**
  "Turn the light off in five minutes" needs the script to say *which*
  entry point, and there is no way to write one down. A name as text is
  planned and not built; a function pointer is excluded permanently. A
  **static reference to an entry point** would be safe — the host
  re-enters later, so the call graph the recursion cap rests on is
  untouched — and it does not exist. Probably the embedder's to solve
  with one import per timer, but it came up independently in three of
  five ecosystems when the design was checked against real automation
  code, which is enough to write down.
- **Multi-file compilation** is the producer's command line and not a
  module system (§6.12). Nothing here says how names from two files
  meet, because nothing yet needs two files.
- **§8 questions 10 and 11 remain unevidenced** — that static inference
  suits non-developers, and that 90 % of scripts are formulas. Decision
  2 is deliberately shaped so that the second being wrong costs nothing:
  the formula is not a special mode, it is a program.
