<!--
SPDX-FileCopyrightText: 2026 The MCUScript Contributors
SPDX-License-Identifier: Apache-2.0
-->

# 6. The surface syntax

Chapters 1 to 5 describe a container and what a runtime does with one.
This chapter describes the language a person writes. The two are joined
by a compiler and by nothing else: a container carries no syntax, and a
second front end that emits conforming containers from a different
grammar is legitimate (README, *Conformance*). What makes this document
part of the specification rather than a manual is that **the two
backends must agree**, and agreement starts at the point where a
sentence acquires a meaning.

## 6.0 How to read this chapter

The language is planned whole here, including parts that are not built
and parts that will never be built. That is deliberate. A language feels
arbitrary when a decision taken for one construct collides with a later
one — when the character that made formulas read nicely turns out to be
the character loops needed — and the audience this language is for reads
uniformity as simplicity. Planning the whole surface costs a document;
discovering the collisions costs a redesign.

Every construct carries one of three marks:

| Mark | Means |
|---|---|
| **built** | implemented, and the rest of this document holds for it |
| **planned** | designed here, not implemented; where it needs something the container does not yet have, this chapter names it |
| **excluded** | deliberately absent, with the reason, so it is not proposed again |

A **planned** construct is normative in one direction only: an
implementation must not use its spelling for something else.

## 6.1 Lexical structure

### 6.1.1 Source text — built

Source is **UTF-8**. Outside string literals, only characters this
chapter gives a meaning to are permitted; anything else is an error
naming the character, because a look-alike from another alphabet is a
diagnostic worth spending a sentence on.

A line ends with LF or CRLF, and the two are the same thing. Horizontal
space and tabs separate tokens and mean nothing else: **the language has
no indentation rule.** A script embedded in a YAML file cannot change
meaning because an editor re-indented it, and a one-liner and its
multi-line form are the same program.

### 6.1.2 Comments — built

`#` begins a comment that runs to the end of the line.

There are no block comments. `#` is what the audience already writes in
YAML, shell and INI files, and one comment form is one thing to know.
Commenting out a region is the editor's job, and every editor does it.

### 6.1.3 Identifiers and keywords — built

An identifier begins with a letter or `_` and continues with letters,
digits and `_`. Letters are ASCII only, deliberately: an identifier that
differs from another by an invisible codepoint is the kind of defect that
costs an afternoon, and the entity names it would serve are the
embedder's to choose in ASCII.

The keywords are

```
and     break   catch  continue  else    false  fn     for
if      in      invalid  is      let     limit  match  mod
not     on      or       return  true    try    unavailable
while
```

`while`, `try` and `catch` are **planned** and reserved now, for the
reason §6.0 gives: a word that is free today and needed tomorrow is a
word somebody will have used as an entity name in between.

### 6.1.4 Numbers — built

```
42        1_000_000        0xFF        0b1010
3.14      0.5              1.5e-3
```

An underscore may separate digits and is ignored. A number **without a
suffix** takes its type from its form: `f32` if it contains `.` or an
exponent, `i32` otherwise. A literal too large for its type is an error
stating both the literal and the range, never a wrap.

A number **with a suffix** takes its type from its dimension instead
(§6.1.5), and the written form says nothing about it. A profile that
holds temperature as tenths of a degree in an `i32` makes `24.5°C` the
integer 245, and `24.55°C` an error that names the step the profile
works in rather than a value silently rounded. This is the rule that
keeps dimensioned arithmetic free of accidental float: `target + 0.5°C`
is integer arithmetic in that profile, and neither literal had to be
written differently to make it so.

There is no unary-minus-in-a-literal: `-5` is negation applied to `5`,
which matters only in that `-2147483648` is written as it reads and
still fits, because the compiler folds the negation before checking the
range.

### 6.1.5 Unit suffixes — built

A number may carry a unit suffix directly, with no space:

```
5min      24.5°C      75%      250ms      1.5kWh
```

**Number and suffix are one token.** This is what keeps `%` from
colliding with an operator — there is no `%` operator, modulo is `mod`
(§6.3.2) — and it is what makes `5 min` a different thing to say than
`5min`: the first is two tokens and an error, and the error says so.

A suffix is an identifier-shaped word, or one of the non-letter forms a
profile may declare — `%`, `‰`, `°C`, `°F`. Which suffixes exist, what
dimension each belongs to and what it normalizes to is **the profile's**
(§6.5.4). The language defines that suffixes exist and how they lex.

The profile's suffix table therefore extends the set of characters
§6.1.1 permits in source, and only there: `‰` is a suffix where a
profile declares it and an error everywhere else. That is the one place
a profile reaches into the lexer, and it reaches no further.

### 6.1.6 Duration literals — built

Several unit-suffixed numbers written next to each other, with no
operator between them, are one value:

```
3h 45min          1h30min          20 minutes        3d 5h 45min 13s
```

Spaces between the parts are optional and the parts may be spelled out.
The parts must belong to one dimension and must descend in magnitude,
and the value is their sum in that dimension's base unit. Repeating a
unit, or ascending, is an error — `3h 5h` is a typo every time, and the
error says which part is out of order.

This is not time-specific: it is defined over any dimension whose
profile declares more than one unit. Time is simply the one where people
write it.

There is no colon form (`3:45` for a duration) and no ISO 8601
(`PT3H45M`). The first is ambiguous against a time of day and against
division; the second is a machine notation that no member of this
language's audience writes by hand.

### 6.1.7 Date and time literals — built

A point in time is written with a leading `@` on a quoted string:

```
@"2026-08-18"            @"13:25"            @"2026-08-18 13:25"
@"13:25:30"              @"2026-08-18T13:25:30"
```

The `@` is the whole of the mechanism. Inside the quotes is an ordinary
string as far as the lexer is concerned, so nothing in the date notation
can collide with an operator: the `-` is not subtraction, the `:` is not
punctuation the grammar needs, and both remain free for the rest of the
language. Without the `@` the same characters are a string and obviously
a string, which is the property that makes the marker worth having.

Two spellings were rejected. Bare `2026-08-18` requires the lexer to
decide between a date and three subtractions from a number, which is a
guess; and `#2026-08-18#`, the SQL/Pascal form, spends `#` — the comment
character in every configuration format this audience already uses.

The grammar of what may stand inside is **fixed by this document**, and
its meaning is **the profile's**: the compiler parses the fields, and the
profile's dimension says which dimension a date-and-time literal belongs
to, what its epoch is and how the fields normalize to its base unit. A
profile that declares no such dimension makes `@"…"` an error saying
exactly that. The language has no calendar of its own (ADR 0008).

Accepted forms, and nothing else: `YYYY-MM-DD`, `hh:mm`, `hh:mm:ss`,
and a date and a time joined by one space or by `T`. Fields are fixed
width and zero-padded. The order is big-endian throughout — year,
month, day, hour, minute, second — because it is the one order that is
unambiguous across the conventions this audience actually holds, where
`08-09` is August 9th to one reader and the 8th of September to
another.

### 6.1.8 String literals — planned

```
"a string"        "with \" and \\ and \n"
```

Escapes are `\"`, `\\`, `\n`, `\t` and `\u{…}`.

**The literal is built; the value is planned.** A compiler reads this
token today — §6.1.7 needs it, since a date literal is `@` on one — and
what is staged is a string being something a script can *hold*. The
stages are in §6.10.

### 6.1.9 Operators and punctuation — built

```
+   -   *   /   =   ==   !=   <   <=   >   >=
+=  -=  *=  /=
&   |   ^   ~   <<   >>
(   )   {   }   [   ]   ,   .   ->   ..   :   @   #
```

Word-spelled operators — `and`, `or`, `not`, `mod`, `is`, `else`,
`limit`, `in` — are keywords, not punctuation, and §6.3 says why each is a
word.

`:` and `[` are **reserved and unused** by the built language. `:` is
kept for optional type annotations (§6.5.3) and `[` for arrays (§6.9);
naming them here is what stops something else claiming them.

### 6.1.10 Statement separators — built

A newline ends a statement, and so does `;`. The two are exactly
equivalent, so a script reads the same written down a page or along a
line — which is what an inline one-liner in a YAML file needs.

A statement may be continued across a newline when the line cannot yet
be a complete statement: after an operator, after `(` `[` `{` `,` or
`->`. Nothing else continues a line, and a line that could end does.

## 6.2 The shape of a program

### 6.2.1 A file — built

A source file is a sequence of declarations: entry points and functions.
Order does not matter, and a function may be used before it is written.

```
on temperature_changed {
    fan.speed = match sensor.temp {
        unavailable -> 0
        > 28°C      -> 3
        > 25°C      -> 2
        else        -> 0
    }
}
```

### 6.2.2 A file that is only an expression — built

A file containing a single expression and nothing else is a complete
program: one entry point whose body returns that expression.

```
(sensor.temp - 32) / 1.8
```

This is not sugar, it is the point. The formula and the script are the
same language with the same meaning, so there is no cliff between the
user who writes one line in a YAML field and the user who writes a file
— and the one-line form is the notation everyone already recognises. The
entry point's name is not in the source; a producer takes it from the
compilation unit, and a compiler must let it be set.

### 6.2.3 Entry points — built

```
on <name> { … }
```

An entry point takes **no parameters** — the host has no argument
channel, and a script reads what triggered it from an entity — and it
**may return a value**, which the host takes or ignores as it chooses
(§5.1). The formula of §6.2.2 is the case where it does; a rule that
only writes entities is the case where it does not.

`on` is the vocabulary rather than `fn`, because that is the shape the
audience already thinks in — something happened, so do this — and
because it names the thing correctly: an entry point is what a host
calls when something happened, and what "something" is belongs to the
host.

Two entry points with the same name are an error. An entry point may
call functions and may not be called.

### 6.2.4 Functions — built

```
fn celsius_to_f(c) { c * 1.8 + 32 }

fn depth_of(node) limit 5 { … }
```

Parameters are named and untyped; types come from inference (§6.5). A
function's value is its last expression, or whatever `return` gives.

`limit <n>` declares the recursion cap for the call-graph component this
function belongs to (§5.4). It is required exactly when the compiler
finds the function in a cycle, and refused when it does not — a bound on
something that cannot repeat is noise, and the error says which cycle
was found. Where a cycle spans several functions, the declaration may
stand on any one of them, and two different declarations in one cycle
are an error naming both.

That `limit` is the same word the loop bound uses (§6.4.4) is
deliberate. The two mechanisms differ under the hood — one is a declared
cap the runtime counts, the other is an ordinary local the producer
decrements — but to a reader they are one idea: **`limit` appears
exactly where the compiler cannot see how often something repeats.**

## 6.3 Expressions

### 6.3.1 Precedence — built

Tightest first. Every level is left-associative except where noted.

| | Operators | |
|---|---|---|
| 1 | `f(…)`  `a.b`  `a[i]` | postfix |
| 2 | `-`  `~` | unary |
| 3 | `*`  `/`  `mod` | |
| 4 | `+`  `-` | |
| 5 | `<<`  `>>` | |
| 6 | `&` | |
| 7 | `^` | |
| 8 | `\|` | |
| 9 | `else` | |
| 10 | `<`  `<=`  `>`  `>=`  `==`  `!=`  `is` | **non-associative** |
| 11 | `not` | unary |
| 12 | `and` | |
| 13 | `or` | |

Three placements are worth their reasons.

**The bitwise operators bind tighter than comparison**, which is what C
gets wrong and Python gets right: `a & mask == 0` means
`(a & mask) == 0`, which is what it looks like it means.

**Comparison is non-associative.** `a < b < c` is a syntax error whose
message says chained comparison is not a thing here and offers
`a < b and b < c`. Silently reading it as `(a < b) < c` is exactly the
class of quiet wrongness this language refuses.

**`not` binds looser than comparison**, so `not temp > 25` is
`not (temp > 25)`. The alternative reading is one nobody means.

### 6.3.2 Arithmetic — built

`+  -  *  /  mod`, with the semantics of §1.5 — wrapping integers,
IEEE-754 single precision, division by zero yielding `invalid`.

**There is one division, and it is spelled `/`.** An earlier draft of
this chapter had a second one, `div`, for the integer case. That was a
mistake, and the argument against it is the one this language makes
everywhere else: `+` has a single spelling and lowers to `ADD.i32` or
`ADD.f32` according to its operands, and `/` lowers to `DIV.i32` or
`DIV.f32` in exactly the same way. The instruction set always had that
symmetry; only the surface language had broken it.

What `a / b` produces follows from one rule, stated in full in §6.5.5:

> **The data type follows the dimension.** A dimensioned result carries
> the data type its profile declared. A result with no dimension has no
> declared resolution either, so a division that produces one produces a
> decimal.

The two halves are the same idea from two sides. A profile declaring a
dimension states its data type and its base unit together (§6.5.4), and
that declaration **is** the statement of how fine the quantity is. A
profile holding temperature as whole tenths of a degree has said that
0.05 °C is not a temperature it represents — so `27.9°C / 2` is
`13.9°C`, truncated to the resolution the profile declared, and there is
nothing here for the language to paper over. A profile author who wants
the half-step declares hundredths as the base unit instead. That is a
decision taken once, by the one person in the chain who can judge it,
and it is visible where it is taken.

A bare number carries no such declaration, so `7 / 2` is `3.5` — the
answer everyone outside a programming language expects, and the one this
language gives. Where a whole number is wanted from it, `trunc(…)` and
`round(…)` say which.

Two consequences worth stating rather than leaving to be discovered.
**Dimensioned arithmetic never needs the `float` instruction group**; a
dimensionless division does, because its result is a decimal, and a
build without the group refuses such a container at load (§2.5). And an
`f32` still never lands in an integer place implicitly — but after this
rule that case is rare, because a dimensioned expression stays in its
dimension's type all the way to the entity it is written to.

`mod` is spelled as a word because `%` is spent on the percent suffix
(§6.1.5), and for no other reason. It is not the partner of a `div` that
does not exist.

### 6.3.3 Comparison and boolean — built

`==  !=  <  <=  >  >=` compare two values of the same type and dimension
and yield `bool`. `and`, `or` and `not` are the boolean operators, as
words.

**`and` and `or` do not short-circuit.** Both operands are always
evaluated, and validity propagates by §1.3's rule: `temp > 25 and
humidity > 60` with an unread humidity sensor is `unavailable`, not a
fault and not `false`. Short-circuiting would mean branching on the left
operand, and §1.3.1 makes a branch on a non-valid value a fault — so the
short-circuiting version of this expression *dies* where the
propagating one produces the honest answer and lets the script write
`… else false`. The price is that a side-effecting host call in the
right operand runs either way, which is a shape worth discouraging on
its own.

This is the one place the surface language needs something the container
does not have: **two `core` instructions, boolean `and` and `or`.** The
group has `not` and it has the `bits` group's `and.i32`, but nothing
that takes two `bool`s — so today the only lowering available is a
branch, which is precisely the semantics being refused. See §6.13.

### 6.3.4 `if` as an expression — built

```
fan.speed = if temp > 28 { 3 } else if temp > 25 { 2 } else { 0 }
```

`if` is an expression whose arms are blocks and whose value is the
block's value. Used as a statement it is the same construct with its
value discarded, so there is one `if` in the language and not two.

An `if` used for its value must have an `else`; one used as a statement
need not. Both arms must agree in type and dimension.

**There is no `? :`.** An if-expression is the conditional operator,
under a spelling that can be read aloud, and two spellings for one
thing is the confusion this audience can least afford. This settles the
one contradiction ADR 0002 §3.2 left open, in favour of §2.5.

The condition must be `valid` when control reaches it (§1.3.1); if it
is not, the script faults. `if temp > 25` with an unread sensor does not
quietly take the false arm, and §6.6 is how a script says what it wants
instead.

### 6.3.5 `match` — built

```
fan.speed = match sensor.temp {
    unavailable -> 0
    invalid     -> invalid
    > 28°C      -> 3
    24..28°C    -> 2
    else        -> 0
}
```

Arms are separated by a newline or a comma, and each is a pattern, `->`,
and an expression. A pattern is

- a literal — `28°C`, `true`;
- a comparison against the subject — `> 28°C`, `<= 0`;
- an inclusive range — `24..28°C` (§6.3.8);
- one of `unavailable` and `invalid`;
- `else`.

Arms are tried in order and the first match wins. The value of the match
is the value of that arm; all arms must agree in type and dimension.

**`else` is required** unless the arms provably cover every value, which
in practice means a `bool` subject with both spelled out. Exhaustiveness
is checked, and a missing `else` is an error rather than a value nobody
chose.

**Validity is part of the pattern language.** A non-valid subject is
handled by the arm for *its own* state if there is one, and otherwise
propagates: the match yields that same state and no arm is evaluated at
all. The two states are independent — a match may catch `unavailable`
and let `invalid` through, which is usually what a script wants, since a
wait has a sensible substitute and a defect does not.

An arm may also *produce* a non-valid value: `invalid -> invalid` is the
way a script says that a faulted reading stays faulted rather than
becoming a number somebody will later mistake for a measurement.

`invalid -> invalid` and the propagation rule above both need something
the container does not have: **two `core` instructions that push a
non-valid value of a given type.** No instruction today produces a
*chosen* state. States arise as a side effect — from an operand, from a
host read of an entity with no reading, or from an undefined arithmetic
case such as division by zero (§1.5) — and none of those is a way to say
*this one is invalid, deliberately*. See §6.13.

### 6.3.6 `else` — the validity fallback — built

```
temp else 20
if temp else 20 > 25 { … }
```

`a else b` is `a` when `a` is `valid`, and `b` otherwise — for **both**
non-valid states, per §1.3.1. It lowers to one instruction and never
branches.

Its precedence, between the arithmetic levels and comparison, is what
makes the second line above read the way it is written: the fallback is
applied to the reading, and the comparison sees a number.

The word is deliberately the same one `if` and `match` use. In all three
it means *otherwise*, and a reader who has met one has met them all.

### 6.3.7 Names — built

A bare identifier is a local (§6.4.1) or a parameter.

A **dotted name** — `sensor.temp`, `fan.speed`, `light.living_room` — is
one import name, looked up whole in the import table (§4.4). The dot is a
character in the name and not an operation: `sensor` alone is not a
value, and saying so is a diagnostic worth writing, because the reader
who tried it was thinking of objects, which §6.11 is about.

Reading an import compiles to a host read; assigning to one, to a host
write; calling one, to a host call. A name that is not in the registry is
an error carrying the nearest known names, which §2.9 of ADR 0002 argues
is worth more to this audience than most language features.

### 6.3.8 Ranges — built

`a..b` is a range, **inclusive at both ends.** `1..10` is ten values, and
`0..23` is the twenty-four hours of a day. The half-open reading is a
programmer's convention and this audience does not hold it; asking which
one `0..23` means is a question that answers itself only under this rule.

A range is not a value. It appears in `match` patterns (§6.3.5), in `for`
(§6.4.4) and in slices (§6.9), and nowhere else.

### 6.3.9 Built-in functions — built, and closed by a rule

The language has a small set of functions that are not imports:

```
round(x)   trunc(x)   abs(x)                     # built
to_i32(x)  to_i64(x)  to_f32(x)  to_unit(x, u)   # built — §6.3.10
min(a, b)  max(a, b)                             # planned
```

They are **compile-time expansions**: each lowers to instructions, and
none of them reads anything outside its own operands. That is the rule
that closes the set, and it is the rule rather than the list that
matters — a built-in that touched the world would be a host call wearing
a keyword, and what a script may reach belongs to the embedder. It is
why this language has no `now()` (ADR 0008).

Two obligations follow, and both fall on the compiler.

**A built-in propagates validity like an operator.** `abs(temp)` with an
unread sensor is `unavailable`, not a fault — so a lowering that
branches on the operand is wrong even where it is obvious. The available
pattern is to branch on a predicate instead: `is_valid(x)` yields a
`valid` `bool` whatever `x` is, so `if x is valid { … } else { x }` is a
safe frame around a branchy body.

That frame is also why the one-operand built-ins are **built** and the
two-operand ones are **planned**. With one operand the fallback arm
yields the operand itself, which carries exactly the right state and a
defined payload. With two it has to *construct* a value whose state is
the maximum of both — which is expressible, and is the sort of thing
that should be written once with a test beside it rather than asserted
in a specification.

**They are functions and not keywords**, so `min` and `max` are ordinary
names a profile could shadow with an import — and if one does, the
import wins and the shadowing is reported. Reserving them as keywords
would have cost the two most guessable names in the language to two
functions most scripts never call.

The bound in §6.2.4 and §6.4.4 is spelled `limit` and not `max` for
exactly this reason. One word may not be two things, and of the two,
`max` is the one that is already in everybody's fingers.

### 6.3.10 Crossing between a dimension and a number — built

A script sometimes has to leave the dimension system: to index an array
with a reading, to hand a raw number to a host function that takes one,
or to build a quantity out of a number that arrived without one. Four
built-ins do it, and they are the **only** way — no operator converts,
and nothing is implicit.

```
to_i32(x, °C)      to_i64(x, °C)      to_f32(x, °C)
to_unit(n, °C)
```

`to_i32(x, °C)` is *"give me this quantity as a number of °C"*, and
`to_unit(n, °C)` is its inverse, *"this number is that many °C"*. For a
value that has no dimension the unit is omitted and the built-in is a
plain conversion between `i32`, `i64` and `f32`.

**The unit is named, and a base unit is never assumed.** That is the
whole design of these four, and the reason is §1.4: base units are the
profile's, they may change between profile versions, and a script that
said `to_i32(temp)` would be silently reinterpreting its own numbers the
day a profile moved from tenths to hundredths of a degree. Naming the
unit makes the script say what it means, and makes it survive that
change. A profile whose scaling matches none of its declared units has
a profile-format problem, not a script one.

Two rules keep them honest:

- **A conversion that would need rounding is refused**, naming
  `round(…)` and `trunc(…)`. `to_i32(x, °C)` where the quantity is
  32.5 °C is an error, because which of 32 and 33 was wanted is not the
  compiler's to guess.
- **The unit argument is required exactly when the operand has a
  dimension.** `to_f32(count, °C)` and `to_i32(temp)` are both errors,
  and each says which half is wrong.

They need nothing new from the container: a unit factor is a compile-time
multiply or divide, and `CONVERT.i32_f32`, `TRUNC.f32_i32`,
`EXTEND.i32_i64` and `WRAP.i64_i32` already exist (§3.4, §3.5).

## 6.4 Statements

### 6.4.1 Locals — built

```
let target = 21°C
target = 22°C
```

`let` introduces a local with its initial value; plain assignment
changes one. Locals are mutable, have the type and dimension of their
initialiser, and live until the end of the enclosing block.

**Assigning to a name that was never declared is an error**, and it
carries the nearest declared name. This is the whole reason `let` exists
in a language that could have inferred it: without a declaration form, a
mistyped name silently becomes a second variable and the script reads
correctly while doing nothing, which is the failure this language spends
its diagnostics budget on.

A `let` that shadows an import is an error naming both; a `let` that
shadows an outer local is allowed and reported only if the two are never
both used.

### 6.4.2 Assignment — built

```
fan.speed = 3
total = total + reading
total += reading
```

The place on the left is a local, a parameter or a writable import.
Compound assignment exists for the infix arithmetic operators — `+=`,
`-=`, `*=`, `/=` — and not for `mod`, because `x mod= 2` is not
something anyone should have to read.

**Assignment is a statement and never an expression.** `if x = 5 { … }`
is a syntax error whose message says that `=` assigns, `==` compares,
and which one was probably meant. The construct that makes this mistake
silent in C has no equivalent here.

### 6.4.3 Expression statements — built

An expression may stand alone as a statement, and its value is
discarded. In practice this is host calls — `fan.on()` — and the two
constructs that are expressions but usually written for effect, `if` and
`match`.

### 6.4.4 Loops — `for` built, `while` planned

```
for i in 0..9 { … }
for hour in 0..23 { … }
```

`for` runs its body once per value of an inclusive range (§6.3.8), with
the loop variable bound afresh each turn and not assignable inside the
body. `break` leaves the loop; `continue` starts the next turn.

**Every loop carries a bound, including this one**, because §3.8.1 makes
that a property of a conforming container rather than a policy: each
backward branch lands on a `LOOP.GUARD` whose counter the body does not
touch. For a range the bound is not something the writer supplies — it
is the range, and the compiler initialises the counter to `b - a + 1`.
The guard therefore never fires in a program that does what it looks
like it does, and it is not a limit the user meets; it is the reason the
container is provably terminating, costing one decrement per turn.

A range whose size does not fit an `i32` makes the counter start below
zero and the loop fault on its first turn. That is the right outcome
rather than an edge case to smooth over: two billion turns on this class
of device is a hung node, and failing immediately with `iteration_limit`
is the most useful thing that can happen.

**`while` is planned**, and its form is fixed here so nothing else
claims it:

```
while pump.running limit 600 { … }
```

The `limit` is required and is the counter's initial value. It is
required because this is exactly the case where the compiler cannot see
how often the body runs (§6.2.4), and `while` without it would be the
one construct in the language that can hang a device.

`while` is planned rather than built because a script that runs to
completion in response to an event has little use for waiting on a
condition, and `for i in 0..n { if done { break } }` says the same thing
with the bound already visible. It is written down because the moment
someone needs it, the spelling must not be invented under pressure.

### 6.4.5 `return` — built

`return` leaves a function or an entry point; `return <expression>`
gives it a value. A function or entry point that falls off its end
yields its last expression, and one whose last statement is not an
expression yields nothing.

## 6.5 Types, dimensions and inference

### 6.5.1 Almost nothing is annotated — built

A script declares no types, except at the one place where inference has
nothing to work from (§6.5.3). Everything else is inferred, and the
program is closed — every function and every import is visible at
compile time — so inference is a whole-program computation with no
guessing in it.

Inference produces one of the four bytecode types (§1.1) for every
expression, and rejects a program where a position has no single type or
where two arms of an `if` disagree. It never inserts a conversion:
widening `i32` to `i64` and converting between integer and float are
written, not implied (§6.3.2, §6.5.5).

### 6.5.2 What a type comes from — built

In order: a literal's own form (§6.1.4); an import's declared type
(§4.4); a function's parameter types, which come from its call sites;
and the type the surrounding expression requires. A function used at two
incompatible types is an error naming both call sites — this language
has no generics, and a diagnostic that names the two lines is more
useful to its audience than one that would allow the program.

Every function has at least one call site, so this terminates: a
function no entry point reaches is already not expressible as a
conforming container (§2.6.1), and the error for it says so before
inference ever runs out of information.

### 6.5.3 Annotations — built

```
let total: i64 = 0
let target: temperature = 20°C
fn scaled(factor: f32) { … }
```

An annotation **pins** a type. It does not steer a computation, and that
difference is load-bearing: `let x: i32 = 27.9°C / 2` is an error rather
than a quiet truncation, and `let x: f32 = count / 2` is an error naming
the conversion rather than a silent widening of `count`. An annotation
can only agree or disagree with what the expression already means.

They are almost never needed, because inference sees the whole program.
The case that makes them necessary is the one nothing else can express:
**a local whose type nothing determines.**

```
let total: i64 = 0
```

Without the annotation `0` is an `i32`, and the only way to say
otherwise would be to assign a fictitious enormous number and overwrite
it on the next line. That is absurd, so the annotation exists. The same
argument covers a `f32` accumulator starting at zero.

**A dimension is a type.** What may stand after the colon is one of the
four dimensionless types — `i32`, `i64`, `f32`, `bool` — or the name of
a dimension the profile declares. The two are not interchangeable, and
this holds *even when the dimension's declared data type is the same
one*:

```
let x: i32 = 20°C          # error
```

A temperature is not an `i32`, for the same reason it is not a
kilometre. The storage a profile chose for it is the profile's business
and not a second name for the quantity — which is the same rule
`if temp > 5min` already enforces on comparison, applied to storage.
Without it a dimension would be a decoration that any assignment could
rub off.

Reserving `:` for this is why §6.1.7 puts date and time literals inside
quotes. Before that decision the colon was spent on `13:25` and
annotations had nowhere to go.

`i32`, `i64`, `f32` and `bool` are **not keywords** (§6.1.3). They are
recognised in a type position and are ordinary identifiers everywhere
else — the same arrangement `valid` has after `is`, and for the same
reason: a word that only means something in one position should not be
taken out of circulation everywhere.

### 6.5.4 Dimensions come from the profile — built

A dimension is a data type, a named base unit, a set of units with a
factor and an optional offset, and optionally a mark that it is
**cyclic** (§6.5.6) or a **scale factor** (§6.5.5.1). **The language
defines none of them** (ADR 0008): not temperature, not percent, and not
time. It defines the notations — suffixes (§6.1.5), duration literals
(§6.1.6) and date-and-time literals (§6.1.7) — and a profile gives them
meaning.

The data type and the base unit are one statement, not two. Together
they say how fine the quantity is, and every arithmetic result in that
dimension carries them (§6.5.5) — so a profile that declares tenths of a
degree in an `i32` has said, once and where it can be judged, that
0.05 °C does not exist in its world.

Consequences worth stating outright:

- A profile that declares no dimensions is legal. Then every number is
  dimensionless, every suffix is an error naming the profile, and the
  language behaves as though units had never been invented.
- A dimensioned value and a bare number do not mix, and there is no
  exception for values that came from an import. `sensor.uptime - 500`
  is refused where `sensor.uptime - 500ms` is not, and the refusal
  suggests the second. This is the millisecond-versus-second confusion
  that units exist to prevent, and an exception for imports would put
  it back exactly where it lives.
- After compilation no unit exists (§1.4). The container holds bare
  integers in base units, and a profile mismatch is refused at load.

### 6.5.5 What operations do to dimensions — built

Pragmatic rules, chosen over a general dimensional analysis on purpose:
this audience never needs m/s² to arise on its own, and the machinery
for it would cost every diagnostic its readability.

| | Rule |
|---|---|
| `a + b`, `a - b` | same dimension → that dimension; a **scale factor** on the right → relative change (§6.5.5.1) |
| `a * b` | at most one side dimensioned → that dimension; a scale factor on either side → the other side's dimension |
| `a / b` | dimensioned by dimensionless or by a scale factor → that dimension; two of the same dimension → **dimensionless** |
| `a mod b` | same dimension → that dimension; dimensioned by dimensionless → that dimension |
| comparison | same dimension |
| bitwise, shifts | dimensionless integers only |

And over the whole table, one rule about the result's **data type**:

> A result that has a dimension carries that dimension's declared data
> type. A result that has none carries the type of its operands, except
> that a division produces `f32`.

That is what makes `(a + b) / 2` on two temperatures a temperature —
computed in base units, truncated to the profile's declared resolution,
and written straight to an entity with nothing in between. And it is
what makes `current / baseline` on two temperatures a decimal: the
dimensions cancel, so nothing is left to declare a resolution, and a
ratio compared against `0.8` is exactly the case that wants a fraction.

Multiplying two dimensioned values is an error rather than a new
dimension, with the single exception of a scale factor, which has no
dimension in the physical sense and leaves the other operand's alone. So
is comparing across dimensions, which is where the feature earns its
place: `if temp > 5min` is caught at compile time and the message names
both sides.

The known imprecision is stated rather than hidden. A point on a scale
and a difference on that scale are different things — 25°C plus 25°C is
nonsense, 25°C plus a 2°C rise is not — and this table does not model the
distinction. Modelling it properly is a research language's job; what
this one does is allow addition and subtraction, forbid multiplying two
dimensioned values, and leave the remaining nonsense to the reader.

#### 6.5.5.1 Scale factors — built; the table is the profile's

A profile may declare a dimension to be a **scale factor**: a quantity
that is a pure ratio, whose units are spellings for a multiplier — `%`
for a hundredth, `‰` for a thousandth, `ppm` for a millionth, and
whatever else that profile needs. The language declares none of them
(ADR 0008); what it defines is what a scale factor *does*.

| Written | Means |
|---|---|
| `x * 5%` | five percent of `x` |
| `x / 5%` | `x` divided by 0.05 |
| `x + 5%` | `x` increased by five percent — the same as `x * 105%` |
| `x - 5%` | `x` decreased by five percent |
| `5% + 3%` | `8%` — two values of one dimension, added |
| `50% * 50%` | `25%` |

Three rules keep that unambiguous, and each of them is a place where
guessing would have been the alternative.

**Same dimension wins.** Where both sides are scale factors, `+` and `-`
are ordinary addition within one dimension: `50% + 5%` is `55%`, never
`52.5%`. The relative reading applies only where the left side is
something else.

**A bare number is not a scale factor.** `x * 1.05` stays legal, as a
dimensionless multiplier always was, and `x + 0.05` stays an error. The
suffix is what says *relative*; with no suffix there is no such
statement, and inventing one would be exactly the silent behaviour this
language refuses.

**`+` and `-` are not commutative here.** `x + 5%` is a relative
increase; `5% + x` is refused. The two are not one expression written in
two orders — the second asks what a temperature added to a ratio is, and
there is no answer to give.

The result keeps the left operand's dimension and therefore its data
type, so `light.brightness * 50%` is a brightness, truncated to whatever
resolution the profile declared for it, and goes to the entity with
nothing in between.

### 6.5.6 Cyclic dimensions — built

A profile may mark a dimension **cyclic**, meaning its values wrap: a
clock that counts milliseconds in an `i32` returns to its start after
about 49.7 days, and a compass bearing does so every 360 degrees.

For a cyclic dimension the compiler lowers `<`, `<=`, `>` and `>=` as
comparisons of the **difference** against zero, so a comparison remains
correct across the wrap for values within half a period of each other —
about 24.8 days in either direction for the clock above. Equality is
unchanged.

**A cyclic value never widens.** There is no implicit promotion to a
wider type and no explicit conversion either. A wrap is invisible in the
arithmetic it was designed for and becomes a jump of −2³² in wider
arithmetic, with no operation to blame it on — so a profile that needs a
wider range declares a second dimension and a second import rather than
converting the first.

## 6.6 Validity in the surface language

§1.3 gives every value a validity state and §1.3.1 fixes the one place
it must be resolved: a `bool` that chooses control flow has to be
`valid`. This section is how a script says what should happen instead of
faulting there. There are three ways, and the language deliberately
offers no fourth.

### 6.6.1 `else` — the fallback — built

`temp else 20` (§6.3.6). One instruction, no branch, catches both
non-valid states. This is the answer for the common case, which is *give
me a usable number*.

### 6.6.2 `is` — asking — built

```
if sensor.temp is unavailable { … }
if sensor.temp is not valid   { … }
```

`a is valid`, `a is unavailable` and `a is invalid` yield a `bool` that
is itself always `valid`, whatever `a` is — which is what makes them
safe to branch on, and what makes them the frame a compiler wraps around
any lowering that would otherwise branch on a value (§6.3.9). `is not`
negates.

The distinction they expose is the one §1.3 exists for. *Unavailable* is
a wait and a fallback is usually right; *invalid* is a defect and
quietly substituting for it hides the defect. A script that does not
care writes `else` and gets both; a script that cares can tell them
apart.

### 6.6.3 `match` on validity — built

§6.3.5. This is the form that scales: the arms that handle absence stand
beside the arms that handle values, in one table, in the order they are
tried. And it is the only construct that can *produce* a non-valid value
— `invalid -> invalid` — which is how a script refuses to turn a faulted
reading into a number.

### 6.6.4 `try` / `catch` — planned

```
try {
    fan.speed = compute_from(sensor.temp)
    log.info("set")
} catch {
    fan.speed = 0
}
```

The block runs; if any operation in it produces a value that is not
`valid`, control leaves for the `catch` block at that point. `catch
unavailable { … }` and `catch invalid { … }` may stand as separate arms,
and a bare `catch` takes both.

**Where the gate fires is specified, not optimised.** It fires at the
*first* operation whose result is not valid — not at the first use, not
at the end of the block. This has to be pinned because it is observable:
where an `unavailable` and an `invalid` arise in the same block, which
one the `catch` sees depends on which operation stopped it, so an
implementation that moved the check to a convenient place would change
the program's meaning. Nothing is undone; a write that already happened
has happened, and whether writes are buffered to a commit point is the
embedder's policy (§1.6).

It is **planned** rather than built for one reason, and it is a real
one: this is the only construct in the language that costs a test after
every operation, in a value model built to propagate validity without
branching at all. `else` and `match` cover the cases scripts actually
have, at one instruction and none respectively. `try` earns its cost
when a real script needs a sequence of writes abandoned partway, and not
before.

## 6.7 Diagnostics are part of the language

Most of this chapter's rules exist to make a compile error possible
where another language would have produced a plausible wrong answer:
`=` where `==` was meant, a chained comparison, a bare number beside a
dimensioned one, an assignment to an undeclared name, a temperature
stored in an `i32`, a missing `else` in a `match`. Each of those is a
place where this document chose the error.

That choice is only worth anything if the message is worth reading, so
three obligations fall on a conforming compiler:

1. **Name the thing, then say what to do.** *"`sensor.tmp` is not a
   known entity. Did you mean `sensor.temp`?"* — the nearest known names
   are computable and this audience is not going to grep a registry.
2. **Never cite this document.** A section number in a message sent to
   someone writing a heating rule is noise, and this project's first
   embedder holds the same rule for its own tools.
3. **Say what was expected in the words of the language.** *"`delay`
   needs a time — did you mean `5s` or `5min`?"*, not *"type error:
   expected dimension #3"*.

These are requirements on a compiler, not on a container, so nothing in
`spec/corpus/` checks them. They are written here because the project's
own record of why this language exists puts diagnostics beside units and
validity as one of the three things that must be planned before the
first line of compiler code, and because a language whose errors are bad
is a language this audience cannot use.

## 6.8 What a script keeps

A script has locals and nothing else. There are no globals, no
module-level variables, and **no state that survives an invocation**.
Between two calls a script remembers nothing.

That is not an omission waiting to be filled. State that survives is
state something must size, initialise, migrate when a script is
replaced, and preserve across a reboot — and the component that already
does all four for this audience is the host, through an entity. A script
that needs a running average reads and writes an entity the embedder
declared for it, and then the averaging window has an owner, a type, a
dimension and a place in the registry.

The consequence for the reader of §1.6 is worth joining up: a script
observes its own writes, so *within* one invocation an entity is a
perfectly good scratch variable, and across invocations it is the only
one.

## 6.9 Arrays — planned

```
let window: i16[64]
window[0] = sensor.temp
for x in window { … }
let recent = window[0..7]
```

An array has a **fixed length written in its declaration** and an
**element storage type**, and it lives in a byte-addressed arena rather
than in slots. Both halves of that matter. A slot is eight bytes and
carries a validity companion, so sixty-four readings held as slots cost
576 bytes — 512 of values and 64 of companions — where the same readings
packed as `i16` cost 128 and one companion. A device that has 128 bytes
to spare frequently does not have 576.

The storage types are `i8`, `i16`, `i32`, `i64` and `f32`. The narrow
ones exist **only** as storage: a read widens to the value type of §1.1
immediately, so nothing in the type system or in the arithmetic learns
about them, and §1.1's reason for having no narrow value types survives
intact.

Indexing out of range yields `invalid` rather than faulting, for the
same reason division by zero does (§1.5): it is overwhelmingly the
consequence of an index computed from a reading, and a value the script
can handle beats a dead script. `len(a)` is a compile-time constant.

An array carries **one validity state for the whole array**, not one per
element. A companion per element would double the arena — which is the
entire reason the arena exists — and the case it would serve, an array
where some readings are absent and others are not, is served by a
sentinel the script chooses.

What the container needs for this is named in §6.13.

## 6.10 Strings — planned, in three stages

Strings arrive in stages because their cost is not in the syntax, and
naming the stages is what keeps the first one from quietly becoming the
third.

**Stage 1 — a literal is an argument.** A string literal may appear only
as an argument to a host function, and the host does the formatting:

```
log.info("temperature is {} in {}", sensor.temp, room.name)
```

The script never holds a string. On the stack the literal is an index
into a constant area, the import declares that parameter as a string,
and the embedder's `invoke` callback resolves it. This is a few hundred
bytes of runtime and it covers logging, notifications and error
reporting, which is what scripts actually want strings for.

**Stage 2 — buffers with a declared maximum.** A string variable with a
written maximum length, living in the arena like an array, with
concatenation and formatting performed on the device. This is a real
feature with a real price, and it is the one to build when a script
needs to *compute* text rather than pass it along.

**Stage 3 — strings as ordinary values**, of any length, assignable and
returnable. This needs allocation, and allocation needs a policy for
running out. It is planned in the sense that nothing here forecloses it,
and it is not on any list of things to build.

## 6.11 Objects — planned; dynamic dispatch — excluded

The import table is flat and a dotted name is one name (§6.3.7). That is
enough for the shapes an embedder wants to offer:

```
temp                    # the entity's canonical value
temp.value              # a named member
temp.set_value(21°C)    # a call
```

All three are import names an embedder declared, and the language is not
involved in the resemblance to objects. What is **planned** is letting a
profile or an embedder declare that resemblance deliberately — a type
with members, projected onto import names at compile time — so that the
naming is checked rather than conventional.

Inheritance is planned only as a **closed world**: every type known at
compile time, every call resolved to one target. **Dynamic dispatch is
excluded permanently**, and the reason is load-bearing rather than
stylistic. The recursion cap (§5.4) and the loop bound (§3.8.1) are what
make a program provably terminating, and both are computed from a call
graph the compiler can see whole. An indirect call destroys that graph,
and with it the one property this language sells. Function pointers and
closures are excluded for exactly the same reason.

## 6.12 Excluded, with reasons

| Not in the language | Why |
|---|---|
| `? :` | an if-expression is the conditional; two spellings for one thing (§6.3.4) |
| significant whitespace | a script embedded in YAML must survive re-indentation (§6.1.1) |
| `null` | `unavailable` and `invalid` are the two things it conflates (§1.3) |
| short-circuit `and`/`or` | it would fault where propagation answers (§6.3.3) |
| assignment as an expression | `if x = 5` is the mistake this language will not make silent (§6.4.2) |
| chained comparison | `a < b < c` reads as maths and would not behave as maths (§6.3.1) |
| dynamic dispatch, function pointers, closures | the call graph is what proves termination (§6.11) |
| `goto` | nothing needs it, and the verifier's job gets harder for nothing |
| exceptions that unwind and undo | nothing is undone; a write that happened happened (§6.6.4, §1.6) |
| globals and state between invocations | the host owns state that survives (§6.8) |
| general dimensional analysis | m/s² arising on its own is a rabbit hole this audience never reaches (§6.5.5) |
| a preprocessor or macros | a second language on top of this one, aimed at people who find one hard |
| an `import` statement | multi-file compilation is the producer's command line, not a module system in a language whose programs are a page long |
| unsigned integers, `f64`, narrow value types | §1.1, unchanged |

## 6.13 What the container must gain

Four instructions, all in `core`, all needed by constructs marked
**built** above. Their encodings belong to §3 and are assigned when they
are implemented.

| Needed | For |
|---|---|
| boolean `AND`, boolean `OR` | non-short-circuiting `and`/`or` (§6.3.3). The set has `NOT` and the `bits` group's `AND.i32`, and nothing that takes two `bool`s — so the only lowering available today is a branch, which is the semantics being refused |
| `CONST.unavailable <type>`, `CONST.invalid <type>` | `match` (§6.3.5), twice over: a match whose subject is not valid must yield that state without evaluating an arm, and `invalid -> invalid` must be writable. No instruction today produces a *chosen* state — every state arises as a side effect of an operand, a host read, or an undefined arithmetic case |

Two further additions are named here so that the planned sections above
are not a wish: **an arena section with sized load and store
instructions** for arrays (§6.9), and **a string constant area plus a
string parameter kind on imports** for stage 1 of strings (§6.10).
Neither is required by anything marked **built**.

## 6.14 Grammar

Tokens are as §6.1 defines them. `NEWLINE` and `;` are the same token
class, written `SEP` here, and §6.1.10 says when a newline is not one.

```ebnf
program        = { SEP } , ( declaration , { SEP , declaration } | expression ) , { SEP } ;
declaration    = entry | function ;
entry          = "on" , identifier , block ;
function       = "fn" , identifier , "(" , [ params ] , ")" , [ "limit" , integer ] , block ;
params         = param , { "," , param } ;
param          = identifier , [ ":" , type ] ;
type           = "i32" | "i64" | "f32" | "bool" | identifier ;

block          = "{" , { SEP } , [ statement , { SEP , statement } , { SEP } ] , "}" ;
statement      = local | assignment | expression
               | "break" | "continue" | return | for | while ;
local          = "let" , identifier , [ ":" , type ] , "=" , expression ;
assignment     = place , ( "=" | "+=" | "-=" | "*=" | "/=" ) , expression ;
place          = name , [ "[" , expression , "]" ] ;
return         = "return" , [ expression ] ;
for            = "for" , identifier , "in" , iterable , block ;
while          = "while" , expression , "limit" , integer , block ;
iterable       = range | expression ;
range          = expression , ".." , expression ;

expression     = or_expr ;
or_expr        = and_expr , { "or" , and_expr } ;
and_expr       = not_expr , { "and" , not_expr } ;
not_expr       = "not" , not_expr | compare ;
compare        = fallback , [ compare_op , fallback | "is" , [ "not" ] , state ] ;
compare_op     = "==" | "!=" | "<" | "<=" | ">" | ">=" ;
state          = "valid" | "unavailable" | "invalid" ;
fallback       = bit_or , { "else" , bit_or } ;
bit_or         = bit_xor , { "|" , bit_xor } ;
bit_xor        = bit_and , { "^" , bit_and } ;
bit_and        = shift ,   { "&" , shift } ;
shift          = additive , { ( "<<" | ">>" ) , additive } ;
additive       = multiplicative , { ( "+" | "-" ) , multiplicative } ;
multiplicative = unary , { ( "*" | "/" | "mod" ) , unary } ;
unary          = ( "-" | "~" ) , unary | postfix ;
postfix        = primary , { "(" , [ args ] , ")" | "[" , index , "]" } ;
index          = expression | range ;
args           = arg , { "," , arg } ;
arg            = expression | unit ;
primary        = number | duration | datetime | string | "true" | "false"
               | name | "(" , expression , ")" | if_expr | match_expr ;

if_expr        = "if" , expression , block , [ "else" , ( if_expr | block ) ] ;
match_expr     = "match" , expression , "{" , { SEP } , arm , { SEP , arm } , { SEP } , "}" ;
arm            = pattern , "->" , expression ;
pattern        = "else" | "unavailable" | "invalid"
               | compare_op , expression | range | expression ;

name           = identifier , { "." , identifier } ;
duration       = number_with_unit , { number_with_unit } ;
datetime       = "@" , string ;
```

`unit` appears in an argument position only for the four conversions of
§6.3.10, where it is a unit spelling from the profile rather than an
expression. Everywhere else a unit exists only glued to a number
(§6.1.5).

`valid`, `unavailable` and `invalid` after `is` are contextual: only
`unavailable` and `invalid` are keywords (§6.1.3), and `valid` is an
ordinary identifier everywhere else. The four type names in `type` are
contextual for the same reason, and `identifier` there is a dimension
name the profile declares.

The one ambiguity the grammar does not resolve on its own is
`match`'s last pattern alternative against a range, and it is resolved
by trying `range` first — which is why `24..28°C` is a range arm and not
an equality arm against `24`.

## 6.15 What is built now

M3 implements the constructs marked **built**: the lexical structure
including unit suffixes, duration literals and `@"…"`; expressions with
the precedence of §6.3.1; `if`, `match` and `else`; locals, assignment,
type annotations, host reads, writes and calls; `for` over a range with
`break` and `continue`; functions with the recursion cap; whole-program
type and dimension inference including scale factors; the conversions
of §6.3.10; and the diagnostics of §6.7.

It does not implement strings, arrays, objects, `while`, `try`/`catch`
or the two-operand built-ins. Those are **planned**, their spellings are
reserved by §6.1.3 and §6.1.9, and the container additions two of them
need are named in §6.13.
