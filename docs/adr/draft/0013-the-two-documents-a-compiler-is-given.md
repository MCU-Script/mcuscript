<!--
SPDX-FileCopyrightText: 2026 The MCUScript Contributors
SPDX-License-Identifier: Apache-2.0
-->

# 0013 — The two documents a compiler is given

- Status: draft — decision taken, implemented and tested (2026-08-20).
- Date: 2026-08-20

## Context

M4. ADR 0008 pushed the dimensions out of the language: `°C` and `lux`
are not MCUScript vocabulary, a **profile** declares them, and what a
script may reach outside itself is the **embedder's** registry. Until
now neither had a written form. `profile.py` and `registry.py` were data
models filled in by hand, and `mcuscript build` compiled against a world
that declared nothing — legal per §6.5.4 and useless for anything real.

Two consequences were waiting on this. A date literal parsed, typed and
could not be lowered, because what its fields count from is an epoch and
an epoch belongs to a profile. And the first embedder had nowhere to put
its answer: MCUHome cannot ship a profile if there is nothing a profile
is.

The product owner had already fixed the interface (2026-08-20): the
integrator supplies both, and MCUScript's side of it is that a **path**
can be passed in, by argument or by environment variable. No search
order, no default location, no discovery.

## Decision

### 1. The format is specified, in chapter 7

The form of both documents is normative and lives in the specification;
none of their content is.

The alternative was a toolchain convention documented in `tools/`, and
it fails on the argument that produced ADR 0008 in the first place. The
dimensions were moved out of the language so that no unit is privileged
and no embedder is a special case. If the document holding them has no
defined form, they have not left the language — they have moved into
whichever compiler reads them, and a profile is portable exactly as far
as its toolchain. Chapter 6 without chapter 7 specifies a language whose
meaning is one implementation's file parser.

What that costs is a second thing to keep honest, and the corpus
argument does not extend here: §4.6's refusals are named because a
loader reports them to software, and these are reported to a person with
the file open. Chapter 7 therefore lists the conditions and names no
refusals.

### 2. TOML, and two files

`tomllib` is in the standard library, so the no-dependency rule survives;
the format has one reading; and a profile is written by hand and read by
review, because its numbers are decisions. *A temperature is held in
hundredths of a degree* is a statement about what a device can express,
and the reason belongs next to the number — which rules out every binary
form, and JSON with it.

Two files rather than one, because the halves have different lifetimes.
A profile is written once and shared between embedders; a registry
belongs to one firmware build and, in MCUHome's case, will be generated
per device.

### 3. Numbers are exact, so a factor is never a TOML float

`factor = 100`, `factor = "0.001"`, `factor = "500/9"`; `factor = 100.0`
is refused with the string to write instead. §6.3.10 decides at compile
time whether a conversion is exact — whether `24.5°C` is a whole number
of base units — and a binary fraction cannot answer that for the decimal
factors a profile is made of. This is the one place where the file
format is stricter than the format it is written in, and it is worth the
irritation: the alternative is a compiler that is subtly wrong about
which literals are representable.

### 4. The registry pins the profile it was written against

Required, and checked with §2.4's rule: same id, same major, minor not
above. A registry says `"sensor.temp"` is a `temperature`, and what a
temperature *is* belongs to the profile — two profiles that both use the
word produce numbers differing by a scale factor, with nothing
downstream to notice (§1.4). A registry given with no profile at all is
refused rather than read for its dimensionless half.

### 5. A time of day is a dimension of its own

`calendar = { epoch = "1970-01-01 00:00:00", second = 1000 }` takes every
literal that carries a date. The same key **without** an epoch marks
where `@"13:25"` lands, counted from midnight.

They are two dimensions because they are two quantities: a time of day
is not a point in history, and there is nothing for an epoch to be. The
alternative — resolving a bare time against some default date — is a
guess of exactly the kind §6.1.7 rejected when it refused the bare
`2026-08-18` spelling.

The arithmetic is fixed in the chapter so that two compilers reading one
profile produce one number: proleptic Gregorian, 86400 seconds a day, no
leap seconds, and **no time zone at either end**. A compiler that
resolved a literal against a zone would bake the build machine's
location into a container, and the same source would compile to
different numbers in two offices. What the number means locally is the
host's.

### 6. Nothing is searched for

`--profile <path>` or `MCUSCRIPT_PROFILE`, `--registry <path>` or
`MCUSCRIPT_REGISTRY`, the flag winning. No default location and no walk
up the tree, which was the product owner's decision and is also the one
this project would have made: every number a script compiles to depends
on the profile, so *which one did I build against* must be answerable
from the command line or the environment, never from the directory a
build happened to run in.

### 7. The embedder's C table is generated from the registry

`mcuscript registry <file> --profile <file> --emit-c <path.h>` writes or
overwrites a header holding an index enum and the `mcuscript_import[]`
a loader resolves against. Everything else — the callbacks, the
`mcuscript_host` — stays the embedder's.

This is not a convenience. §4.4 carries an entity's dimension into the
container and checks it at load, but a **parameter's** dimension is
never carried and never checked, so a host that means milliseconds where
the registry said seconds is wrong at run time and silent about it. And
§4.4.1 obliges the embedder to keep its names free of hash collisions
while observing that a container cannot check it — the registry document
can, and is the only place that can. Both duties fall on a table that
was otherwise typed in a second time, by hand, in another language.

The header is `static const` and is included in one translation unit.
Nothing about it fails quietly: a name that moved, a header included
twice, a type that changed — the C compiler says so.

### 8. An unknown key is an error

In both documents, everywhere. A reader that skipped what it did not
recognise would read `ofset = -16000` as a unit with no offset, accept
the file, and compile every temperature 32 degrees wrong. The reader
suggests the key it thinks was meant, from the keys the chapter defines
at that place.

## What implementing it corrected

Four, and the first two are the useful kind — a rule that had been read
many times and was wrong about its own subject.

- **A base unit is not a unit.** §6.5.4 says a profile need not spell its
  base unit and a script never names it, so holding the *label* to
  §6.1.5's character set restricts nothing and forbids `ms_utc`, which
  is the better label. The test profile had declared three spellings —
  `ms_utc`, `ms_up`, `s_up` — that no script could ever have written,
  and nothing had noticed because nothing validated. The label is now
  one printable word; a unit is §6.1.5's alphabet; and a conversion out
  of a dimension that spells no unit says *this profile spells no unit
  of daytime* instead of naming a word that cannot be typed.
- **A name may end in one of the language's words.** `fan.on` is the
  most ordinary line anyone will write, and the parser has always
  allowed a keyword after a dot. §7.3.2 said "no segment a keyword",
  which would have refused it. Only the first segment is held to it.
- **Two dimensions could share an id.** The model checked duplicate names
  and duplicate spellings and not this, and §4.4 records an import's
  dimension as exactly that number. Checked in the model, not in the
  reader, because it is an invariant of a profile and not of a file.
- **A quantity could disagree with its dimension.** "A dimension is a
  type" (§6.5.3) was a sentence in a docstring; `Quantity` now refuses
  to hold a type its dimension does not have.

Two consequences of the format worth knowing before writing a real
profile. Unit spellings are unique across the whole profile, so a
profile with both a duration and a clock cannot spell `s` twice and has
to choose. And a dimension may declare no units at all — it is still
read, annotated, compared and assigned; what it cannot have is a literal
or a conversion.

## Consequences

- **A date literal has a number.** The one construct the front end typed
  and could not lower now compiles, and the differential tests run it
  through both backends: `@"2026-08-20 04:02:51"` is 1787198571000 in a
  profile counting milliseconds from 1970, and `@"12:00"` is 43200 in
  one counting seconds from midnight.
- **The test profile is a file.** `homeprofile.py` is now the reader
  called on `home.toml` and `home-registry.toml`, so every test that
  writes `24.5°C` is also a test that the format was read.
- **`profile-home` has somewhere to be written**, and ADR 0008's two
  open questions — whether its clock is called `now`, and where the
  recommended fragment lives — become answerable in its own repository.
- **MCUHome inherits a task rather than a design.** It supplies both
  documents; how it generates the registry, and from what, is its
  business (ADR 0001's boundary).

## Open

- **A registry names no dimension for a parameter in the container**, and
  §7.5 removes the ordinary way to get that wrong rather than the
  possibility. Carrying parameter dimensions in `HOST` is a container
  change and has not been argued for.
- **Nothing allocates profile ids.** Two profiles that choose the same
  number is a mistake no reader can see. The version is pinned beside it
  and a registry pins both, which narrows it; it does not close it.
- **No corpus for profiles.** If a second toolchain appears, the argument
  that produced `spec/corpus/` applies here too.
