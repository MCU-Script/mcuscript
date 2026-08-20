<!--
SPDX-FileCopyrightText: 2026 The MCUScript Contributors
SPDX-License-Identifier: Apache-2.0
-->

# 7. Profiles and registries

Chapter 6 twice says that something belongs to somebody else. Which
dimensions exist, what their base units are and how fine they are held
is a **profile's** (§6.5.4). What a script may reach outside itself —
the entities it reads and writes and the functions it calls — is the
**embedder's** (§4.5, §6.3.7). This chapter fixes the form of those two
documents and says nothing whatever about their content.

Why the form is specified at all, when the content deliberately is not:
ADR 0008 pushed the dimensions out of the language so that no unit would
be privileged and no profile would be a special case. If the document
that holds them had no defined form, they would not have left the
language — they would have moved into whichever compiler happened to
read them, and a profile would travel exactly as far as its toolchain.
Chapter 6 without this chapter specifies a language whose meaning is one
implementation's file parser.

**A device reads neither document.** Both are inputs to a compiler. What
reaches a runtime is the container, the profile pin in its header (§2.4)
and the host's own table (§4.5), and a runtime therefore conforms
without knowing this chapter exists.

## 7.1 Both documents are TOML

Both are [TOML](https://toml.io) 1.0 files. The reasons are ordinary and
worth stating anyway, because a format is the kind of decision that gets
revisited by whoever dislikes it:

- **A profile is written by hand and read by review.** Its numbers are
  decisions — that a temperature is held in hundredths of a degree is a
  choice about what a device can express — and the reason belongs beside
  the number. That rules out every binary form and JSON with it.
- **One reading.** A configuration language that has to be memorised
  before it can be trusted is a poor place for a table on which every
  number a script computes depends.
- **A standard-library parser** in the languages a toolchain is likely
  to be written in, so a second implementation spends its effort on
  chapter 6 rather than on a tokenizer.

Filenames are not part of this specification: a path is given, and
nothing is searched for (§7.4).

**Every key this chapter does not define is an error, in both
documents.** A reader that ignored what it did not recognise would read
`ofset = -16000` as a unit with no offset, accept the file, and compile
every temperature in the world 32 degrees wrong. There is no key whose
absence is worth that.

## 7.2 The profile

A profile in full, small enough to read and awkward enough to be real:

```toml
format = 1

[profile]
name = "home"
id = 1
version = "0.1"

[dimension.temperature]
id = 1
type = "i32"
base_unit = "c°C"

[dimension.temperature.units]
"c°C" = 1
"°C" = 100
# 1 °F is 5/9 °C, and the scale starts 32 °F lower.
"°F" = { factor = "500/9", offset = "-16000/9" }

[dimension.instant]
id = 5
type = "i64"
base_unit = "ms_utc"
calendar = { epoch = "1970-01-01 00:00:00", second = 1000 }
```

### 7.2.1 `format` and `[profile]`

| Key | Type | |
|---|---|---|
| `format` | integer | `1`. Top level, not inside a table, so that a reader can decide whether it understands the file before it reads any of it |
| `profile.name` | string | for diagnostics; a script never sees it and nothing is keyed by it |
| `profile.id` | integer | 1 … 4294967295 — the `profile_id` of §2.4 |
| `profile.version` | string | `"MAJOR.MINOR"`, each 0 … 65535 — `profile_major` and `profile_minor` of §2.4 |

**Zero is not available as an id.** It is what a compilation with no
profile pins, and a file that claimed it would produce containers
indistinguishable from the dimensionless ones.

Nothing here allocates ids. The number is an identity in the sense a
magic number is: two profiles that choose the same one is a mistake no
reader can see, which is the reason the version is pinned beside it and
the reason a registry pins both (§7.3.1).

### 7.2.2 A dimension

```toml
[dimension.temperature]
id = 1
type = "i32"
base_unit = "c°C"
```

The table's key is the dimension's **name** — the word an annotation
writes (§6.5.3) and the word a registry names a quantity with (§7.3.2).
It is an identifier per §6.1.3, it is not a keyword, and it is not one
of `i32`, `i64`, `f32`, `bool`: a registry writes a dimension's name or
a type's in the same place, and one word cannot be both.

| Key | | |
|---|---|---|
| `id` | integer | 1 … 65535, unique within the profile. `0x0000` means *dimensionless* in an import record (§4.4), so no dimension may hold it |
| `type` | string | `i32`, `i64` or `f32`. Not `bool` — a quantity that is a yes-or-no has no units to convert |
| `base_unit` | string | the name of what the container holds — one printable word, and **not** held to §7.2.3's character set |
| `units` | table | §7.2.3; may be absent |
| `cyclic` | boolean | §6.5.6 |
| `scale` | boolean | §6.5.5.1 |
| `calendar` | table | §7.2.4 |

`base_unit` need not appear in `units`, and §6.5.4 says why: a profile
working in hundredths of a degree while spelling only `°C` hides
nothing, because `to_i32(temp, °C, 100)` reads every digit it holds.
What the name is for is diagnostics — *"this profile counts temperature
in whole `c°C`"* is the sentence that tells an author why `24.555°C` was
refused.

That is also why it is not held to the character rule below. A script
never writes this word (§6.5.4), so restricting it would restrict
nothing, and `ms_utc` is a better label than a spelling the lexer would
accept. A profile that wants its base unit written as well declares it
under `units` too, and there the rule applies.

### 7.2.3 Units, and why their numbers are strings

```toml
[dimension.duration.units]
ms = 1
s = 1000
min = 60000
```

A table whose keys are **spellings**. A number or a string as the value
is the factor; a table carries `factor` and an optional `offset`. A
value written as `n` of that unit is `n × factor + offset` base units.

A spelling is one or more characters, each of them a letter or one of
`%`, `‰`, `°` — the rule of §6.1.5, which is the lexer's and is not
negotiable per profile. Spellings are unique across the **whole
profile** and not merely within a dimension, because a suffix in a
script names its dimension by itself. A profile with both a duration and
a clock therefore cannot spell `s` twice, and has to choose which one
gets the short word.

**A dimension may declare no units at all**, and that is not a
degenerate case either. Such a quantity is still read from a host, still
annotated by name, still compared and still assigned; what cannot happen
is a literal in it or a conversion out of it, because both name a unit.
A dimension whose values only ever come from the host and go back to it
needs none.

**A factor is exact or the file is refused.**

| Written | Read as |
|---|---|
| `100` | one hundred |
| `"0.001"` | one thousandth, exactly |
| `"500/9"` | five hundred ninths, exactly |
| `100.0` | **refused** |

A TOML float is a binary fraction and `0.001` is not one. §6.3.10
decides at compile time whether a conversion is exact — whether
`24.5°C` is a whole number of base units and `24.555°C` is not — and a
reader that answered that from a binary approximation would answer it
wrongly for precisely the ordinary decimal factors a profile is made of.
The refusal names the string form to write instead.

A factor is greater than zero. An offset may be anything, including a
fraction, and `°F` is why the field exists at all.

### 7.2.4 Cyclic, scale, and the calendar

`cyclic = true` marks a dimension whose values wrap (§6.5.6) and
`scale = true` marks a pure ratio (§6.5.5.1). A dimension is not both: a
ratio does not wrap.

A **calendar** dimension is where a date-and-time literal (§6.1.7) lands,
and one key carries both of its roles:

| Written on a dimension | Takes |
|---|---|
| `calendar = { epoch = "1970-01-01 00:00:00", second = 1000 }` | `@"2026-08-18 13:25"` and `@"2026-08-18"` |
| `calendar = { second = 1000 }` | `@"13:25"` and `@"13:25:30"` |

`second` is what one second is worth in the dimension's base unit,
written like a factor (§7.2.3) and exact for the same reason. `epoch` is
a date, or a date and a time, in the grammar §6.1.7 fixes.

- **With an epoch** the value of a literal is the seconds from the epoch
  to the literal, times `second`. A date with no time is that day's
  midnight.
- **Without one** the value is the seconds since midnight, times
  `second`. There is nothing for an epoch to be: a time of day is not a
  point in history, which is exactly why it needs a dimension of its
  own rather than a default date nobody wrote.

A profile declares at most one of each. One that declares neither makes
`@"…"` an error naming the profile, which is what §6.1.7 promises.

**The arithmetic is fixed here** so that two compilers reading one
profile produce one number: the proleptic Gregorian calendar, every day
86400 seconds, no leap seconds, and **no time zone anywhere**. The
literal and the epoch are both naked wall-clock readings and neither
carries a zone. This is the one place where the alternative is tempting
and wrong — a compiler that resolved `@"13:25"` against a zone would
bake the build machine's location into a container, and the same source
would compile to different numbers in two offices. What the number means
locally is the host's, and a host that needs local time offers a
function.

Two refusals belong to the script rather than to the profile, and both
are the rules already in force for suffixes. A literal whose value is not
a whole number of base units is refused where the dimension is an
integer one (§6.5.4). A literal whose value does not fit the dimension's
declared type is refused rather than wrapped: a profile counting
milliseconds from 1970 in an `i32` covers 24 days, and every date outside
them says so.

### 7.2.5 What a reader refuses

A reader accepts a profile that satisfies everything above and refuses
one that does not. The conditions, gathered:

| Refused | |
|---|---|
| `format` missing, or not `1` | |
| a key this chapter does not define | anywhere in the file |
| `profile.id` outside 1 … 4294967295 | |
| `profile.version` not `MAJOR.MINOR`, or a part above 65535 | |
| a dimension name that is not an identifier, is a keyword, or is a type name | §7.2.2 |
| `id` outside 1 … 65535, or used twice | |
| `type` other than `i32`, `i64`, `f32` | |
| a unit spelling outside §6.1.5's character set | |
| one spelling on two dimensions | |
| a factor that is a TOML float, is zero, or is negative | §7.2.3 |
| an offset that is a TOML float | |
| `cyclic` together with `scale`, or `scale` together with `calendar` | |
| two calendar dimensions with an epoch, or two without | |
| an `epoch` outside the grammar of §6.1.7, or one with no date | |

These refusals have **no names**, and that is a considered difference
from §4.6. A container's refusal is named because a loader reports it to
software that may branch on which one it was. A profile's reader is
reporting to a person with the file open, and the useful output is a
sentence naming the file and the key it is about.

## 7.3 The registry

```toml
format = 1

[profile]
id = 1
version = "0.1"

[entity."sensor.temp"]
quantity = "temperature"

[entity."fan.speed"]
quantity = "i32"
access = "readwrite"

[function."fan.on"]

[function."timer.after"]
params = ["duration"]

[function."math.log"]
params = ["f32"]
returns = "f32"
```

### 7.3.1 The profile it was written against

`[profile]` is required, and carries `id` and `version`. A reader
refuses a registry whose `id` differs from the profile's, whose major
differs, or whose minor is above the profile's — the rule of §2.4, for
the reason of §1.4. A registry says `"sensor.temp"` is a `temperature`;
what a temperature *is* — its base unit, its resolution — is the
profile's, and two profiles that both use the word produce numbers
differing by a scale factor with nothing downstream to notice.

A registry given without a profile is refused rather than accepted for
its dimensionless half. It was written against something, and compiling
against a world that is not that something is the mistake this pin
exists to catch.

### 7.3.2 Entities

The table's key is the name a script writes: one or more identifiers
(§6.1.3) joined by `.`. The **first** of them is not one of the
language's words and the ones after it may be — that is the grammar's
rule (§6.3.7) rather than a concession, since nothing but a name can
stand after a dot, and `fan.on` is the most ordinary line anyone will
write. A name a script cannot write is an entry nothing can reach, and a
registry that holds one has a typo in it.

| Key | | |
|---|---|---|
| `quantity` | string | a dimension's name, or `i32`, `i64`, `f32`, `bool` |
| `access` | string | `read` (the default), `write`, or `readwrite` |

There is one key and not two because **a dimension is a type** (§6.5.3):
a dimension declares the type it is held in (§7.2.2), so naming both
would be naming one thing twice and inviting them to disagree.

### 7.3.3 Functions

| Key | | |
|---|---|---|
| `params` | array of strings | quantities, leftmost first; absent means none |
| `returns` | string | a quantity; absent means the function yields nothing |

A parameter's **dimension is checked by the compiler and is not in the
container.** §4.4's record carries one dimension — an entity's value, or
a function's return — because that is all a loader can check, and it is
enough for the failure a load can see. `timer.after(5s)` compiled against
a registry that says seconds and run against a host that meant
milliseconds is not caught by anything, at any point. That is a fact
about the container format and not a gap in it; §7.5 is the answer.

### 7.3.4 What a reader refuses

| Refused | |
|---|---|
| `format` missing, or not `1` | |
| a key this chapter does not define | |
| `[profile]` missing, or not matching the profile (§7.3.1) | |
| a name that is not writable in a script | §7.3.2 |
| one name declared twice, as an entity and as a function | |
| **two names whose FNV-1a hashes collide** | §4.4.1 |
| a `quantity` that is neither a declared dimension nor a type | |
| `access` other than the three | |
| `quantity` given as `void` | a function that yields nothing leaves `returns` out |
| more than 255 entries | §4.4's count is a `u8`, and so is a host's |

The hash collision is the one worth pointing at. §4.4.1 places that
obligation on the embedder and observes that it cannot be checked from
inside a container. It can be checked *here*, and here is the only place
it can be — which is a plain argument for the embedder's table being a
document rather than a hand-written array.

## 7.4 How a compiler is given them

Two paths, each from a flag or an environment variable, the flag
winning:

| | |
|---|---|
| `--profile <path>` | `MCUSCRIPT_PROFILE` |
| `--registry <path>` | `MCUSCRIPT_REGISTRY` |

**Nothing is searched for.** There is no default location, no walk up
the directory tree and no name a compiler tries. A profile found
silently is a profile that is silently wrong: every number a script
compiles to depends on it, and *which one did I build against* has to be
answerable from the command line or the environment rather than from the
working directory a build happened to run in.

Neither is required. With no profile a compilation declares no
dimensions — legal per §6.5.4, and then every suffix is an error naming
the profile — and pins id 0, version 0.0. With no registry every host
name is an error naming itself.

## 7.5 The host's table — non-normative

The reference toolchain writes the embedder's C table from the registry:

```
mcuscript registry <file> --profile <file> --emit-c <path.h>
```

which generates or overwrites a header holding an index enum and a
`mcuscript_import[]` for the loader (§4.5). This is a facility of one
toolchain and no part of the format.

It is named here because of what it removes rather than what it saves.
§7.3.3 has just said that a parameter's dimension is never checked at
load, and §7.3.4 that a name-hash collision is visible only in this
document — two obligations that fall on a table which is otherwise typed
in a second time by hand, in another language, in another repository.
Generating it is how the second copy stops being a place the first can
be contradicted.
