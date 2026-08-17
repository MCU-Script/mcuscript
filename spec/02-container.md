<!--
SPDX-FileCopyrightText: 2026 The MCUScript Contributors
SPDX-License-Identifier: Apache-2.0
-->

# 2. The container

A compiled program is one **container**: a header followed by
type-tagged sections. It is what a compiler emits and what a VM loads.

A container that satisfies §2.6 is **conforming**, and this chapter
describes what a conforming container looks like and how one is loaded.
Everything a runtime is promised, and everything it promises, is about
conforming containers; what happens between the compiler that produced
one and the device that loads it is the embedder's concern, and §2.6
says why the language draws the line there.

All integers are **little-endian**. There is no field declaring that
and no mode in which it is otherwise. WebAssembly made the same call;
every architecture in the target class is little-endian, and a
byte-order field is a compatibility promise nobody would ever be able
to test.

## 2.1 Header

28 bytes, at offset 0.

| Offset | Size | Field | |
|---|---|---|---|
| 0 | 4 | `magic` | `4D 43 55 53`, the bytes `MCUS` |
| 4 | 2 | `format_version` | u16, this specification defines 1 |
| 6 | 2 | `flags` | u16, all bits reserved; a non-zero value is `reserved_field_set` |
| 8 | 4 | `total_length` | u32, the size of the whole container in bytes, header included |
| 12 | 4 | `profile_id` | u32, identifies the profile this was compiled against |
| 16 | 2 | `profile_major` | u16 |
| 18 | 2 | `profile_minor` | u16 |
| 20 | 4 | `required_groups` | u32 bitmask, the instruction groups this container uses (§2.5) |
| 24 | 4 | `crc32` | u32, over the whole container with these four bytes taken as zero |

Sections begin at offset 28, which is 4-byte aligned.

**`total_length` exists so that truncation is detectable without
trusting anything inside the file.** A container whose actual size
differs from this field is refused before a single section is read. The
alternative — walking section lengths to find the end — asks a hostile
file where its own end is.

**`crc32` detects corruption and nothing else.** The algorithm is
CRC-32/ISO-HDLC — the one PNG, gzip and Ethernet use, and the one
`zlib.crc32` computes — over the whole container from offset 0 to
`total_length`, with these four bytes taken as zero. Naming it matters:
"CRC32" alone describes at least four incompatible functions, and two
implementations that pick differently reject each other's containers
with a checksum error that looks like corruption.

It is not a security
mechanism, and an implementation must not present it as one. It catches
a flipped bit in flash or a truncated transfer. Whether a container is
*authentic* — whether it came from someone entitled to put it on this
device — is the embedder's question, answered by whatever channel or
signature it uses, and the container is built so an embedder can attach
a signature without this specification knowing what a signature is
(§2.3).

**Version rule.** A reader refuses any container whose `format_version`
is greater than the highest it implements. It does not attempt a
best-effort read of a newer file. Lower versions may be accepted by a
reader that still implements them.

## 2.2 Sections

Sections follow the header consecutively until `total_length`. Each is:

| Offset | Size | Field |
|---|---|---|
| 0 | 4 | `type`, four ASCII characters |
| 4 | 4 | `length`, u32, the size of `data` in bytes, padding excluded |
| 8 | `length` | `data` |
| | 0–3 | zero padding to the next 4-byte boundary |

Padding keeps every section header 4-byte aligned, so a reader may load
`type` and `length` as words. Section *data* is read according to its
own rules; a reader must not assume alignment inside it, because the
instruction stream is byte-granular by design.

## 2.3 Critical and ancillary sections

The first character of `type` decides what a reader does with a section
it does not recognise. **Uppercase means critical, lowercase means
ancillary** — PNG's convention, which has the pleasant property of
being legible in a hex dump.

- An unrecognised **critical** section is a refusal. The file is
  asking for something this reader cannot provide, and continuing would
  execute a program that has been partly understood.
- An unrecognised **ancillary** section is skipped.

This is the distinction the first sketch of the format lacked, and its
absence was a forward-compatibility trap: with everything skippable, a
compiler that emitted a new critical section would have its output
silently half-executed by an older VM instead of cleanly refused.

Defined in version 1:

| Type | | Contents |
|---|---|---|
| `CODE` | critical | the instruction stream |
| `CNST` | critical | the constant pool |
| `ENTR` | critical | entry points, with their static resource requirements |
| `HOST` | critical | the import table: the entities and host functions this program refers to |
| `dbug` | ancillary | source line mapping and names, for diagnostics |
| `note` | ancillary | free-form text; ignored |

**All four appear exactly once, in every container.** A program that
refers to nothing outside itself carries a `HOST` section with a count
of zero; it does not omit it. An empty table and an absent section are
the same fact, and a format that can express it twice makes every
reader carry a branch for the second spelling.

**An embedder that wants a signature gives it an ancillary type of its
own** and looks for it in its own loader. Ancillary is the right choice
even though the signature matters greatly to that embedder: the *VM*
must be able to skip it, because verifying signatures is not the VM's
job. Note the interaction with the debug section — stripping `dbug`
changes the bytes, so an embedder that signs must decide whether it
signs before or after stripping, and this specification's advice is to
strip first and sign what will actually be stored.

## 2.4 Profile pinning

`profile_id`, `profile_major` and `profile_minor` name the profile the
compiler assumed. At load, a VM compares them against the profile it
carries and **refuses on any mismatch of id or major version**. A minor
version difference is accepted in the direction the profile's own rules
permit; profiles that only add dimensions may declare minor
compatibility.

The reason this is a refusal and not a warning is in §1.4: a changed
base unit produces no crash and no symptom, only numbers that are
wrong by a factor. It is the one error class that cannot be caught
downstream, so it is caught here.

## 2.5 Instruction groups

`required_groups` is a bitmask of the instruction groups the code
uses. An implementation that does not implement a required group
refuses the container at load.

| Bit | Group | Contents |
|---|---|---|
| 0 | `core` | stack, locals, `i32` arithmetic and comparison, branches, host access, validity. Every implementation has it |
| 1 | `i64` | 64-bit arithmetic, comparison and conversion |
| 2 | `float` | `f32` arithmetic, comparison and conversion |
| 3 | `call` | user-defined function calls and the frame machinery |
| 4 | `bits` | bitwise operations and shifts on `i32` |
| 5 | `loop` | reserved — counted loops (§3.8) |
| 6 | `i64div` | `DIV` and `REM` on `i64`; needs `i64` (§3.4) |
| 7–31 | reserved | must be zero in version 1 |

`RET` and `RET_V` are in `core`, not in `call`: an entry point has to
return whether or not the program has functions. Only calling belongs
to `call`, so an expression-only device carries no call apparatus.

This is what makes an expression-only device honest rather than
hopeful. Without the declaration, a build with no float support that
received float bytecode would decode an instruction it does not
implement, and the best case is a fault. With it, the build says no at
load, in words, before anything runs.

The compiler sets exactly the bits the code needs — not the bits the
language has.

That is a duty on the producer, and §2.6 point 1 says the same thing
from the other side: an opcode belonging to a group the header does
**not** require is undefined *for this container*, however complete the
implementation reading it happens to be. Stated separately because
under-declaring is the one mistake here that looks harmless. A container
naming fewer groups than it uses runs on every implementation that has
those groups anyway, so nothing about it feels wrong — until it reaches
the narrowed build the declaration existed to protect.

Note what the refusal above *is*, though, because it is easy to read
more into it. It is an **identity** check: this container is not meant
for this build, and a build says so rather than decoding an instruction
it does not have. It is not an inspection of whether the container is
otherwise sound — see §2.6.

## 2.6 What a conforming container is

This section defines the properties a container must have. It is an
obligation on whoever **produces** a container, and the definition a
verifier decides. It is **not** a duty imposed on a runtime: a runtime
executes conforming containers as this document says, and on
non-conforming input its behaviour is undefined.

That sentence is the load-bearing one, so it is worth saying why it
reads that way. This language has two backends, and the same source is
equally expressible as a container for a VM or as C compiled into the
firmware. Nothing protects the C on its way to a device, and nothing
here could. A rule obliging every runtime to police its input would
give one of two equivalent paths a guarantee the other cannot have, and
would invite the reading that the language protects a device against
code it did not produce. It does not. **Getting an artifact from a
compiler to a device unaltered is the embedder's concern, equally for
both backends** — and an embedder whose delivery path is untrusted
wants a verifier, which is exactly the component this section defines.

A container is conforming when, for every function, along every path
its branches can take:

1. every instruction is fully contained in its function's code region
   (§2.6.1) and its opcode is defined in a group the header requires;
2. every branch target is a valid instruction boundary within the same
   function's region, and lies forward (§3.8);
3. the operand stack is type-consistent along every path — the type
   stack at a join point is the same by every route to it — and every
   instruction receives the types it takes;
4. the stack is empty at `RET`, or holds exactly the return value;
5. `max_stack` and `max_call_depth` in `ENTR` are the values this code
   actually needs;
6. the call graph's cycles all carry a declared depth cap, no function
   outside a cycle carries one, and the worst-case call depth follows
   from it;
7. every index into `CNST`, `HOST`, the local slots and the function
   table is in range.

Points 3 and 4 are what make the untagged slots of §1.2 work: nothing
at runtime checks a type, because in a conforming container nothing at
runtime *can* be the wrong type.

Point 5 is where a non-conforming container does the most damage, and
naming that is more useful than pretending otherwise. The VM sizes its
frame from those two numbers. A container claiming a depth of two while
needing twenty overflows a buffer sized from its own claim, into
whatever is next to it, on a device with no MMU. A producer that gets
point 5 wrong has not produced a slow program or a wrong answer; it has
produced something with no defined behaviour at all.

### 2.6.0 Verifiers

A **verifier** is a component that decides the list above for arbitrary
bytes. Writing one is optional and this document does not require any
implementation to contain one; defining it precisely is how the option
stays available.

A conforming verifier accepts exactly the conforming containers, and
refuses everything else with one of the refusals of §4.6. In particular
it does not ask whether `max_stack` and `max_call_depth` look plausible
— it **recomputes** them and compares.

Two places a verifier belongs:

- **Beside a compiler**, as a second opinion on its output, written from
  this document rather than from the compiler's internals. The reference
  toolchain does this, and it is why the reference implementation has
  two independent implementations of these rules.
- **In front of a runtime whose input is untrusted.** Whether that is
  the case is a property of the embedding, not of the language: a device
  that accepts signed pushes over an authenticated channel is in a
  different position from one that accepts anything that arrives.

`spec/corpus/` is the conformance material for both: containers with
the verdict a conforming verifier must reach, committed as bytes.

### 2.6.1 Code regions

Point 1 needs "the function's code region" to mean something, so the
format fixes it: **the functions' code regions tile `CODE` exactly.**
The first begins at 0, each one ends where the next begins, the last
ends at the end of the section, and none is empty. **The records are in
`code_offset` order** (§4.3), so a reader walks the table once instead
of sorting it — which on a device is the difference between comparing
every record against every other and comparing each against the one
before.

The regions are what makes "a branch outside this function" a decidable
question rather than a matter of taste, and the tiling is what leaves
no bytes in `CODE` that belong to nobody.

Within a region, each byte must be decoded exactly once by a walk of
every path — neither zero times nor twice. Counting is how a verifier
decides that, and each count means something different:

- a byte decoded **twice** means two instruction boundaries overlap, so
  some branch landed in the middle of an instruction and the code has
  two readings — `bad_branch_target`. Counting is what catches this;
  checking targets against a list of boundaries only works if the list
  is complete, and its completeness is precisely what is in question.
- a byte decoded **never** is code no path reaches — `unreachable_code`.
  It cannot execute, so this is not a safety rule; it is a rule that a
  container means one thing. Dead bytes are an encoder bug or something
  smuggled in, and neither should be quietly accepted.

The same rule applies one level up: **a function no entry point can
reach, directly or through calls, is `unreachable_code` too.** Same
argument, and one more — a container with a dead function is a program
the two backends disagree about, because a C backend turns functions
into file-local symbols and a C compiler rejects one that nobody calls,
while a VM would never notice.

## 2.7 Load and fault behaviour

Loading a container establishes that it is meant for this
implementation, and prepares it to run. In order: check the header,
check `total_length` and the CRC, walk the sections, refuse on an
unrecognised critical section, check the profile pin, check the required
groups, then resolve the `HOST` table against the embedder's registry.

Every one of those is an **identity** question — *is this container
meant for me* — and every failure is a named, typed refusal before
execution, never a partial load and never a silent degradation. The full
error taxonomy, including the eight distinct ways `HOST` resolution can
fail, is chapter 4.

Loading is not an inspection. A loader is not required to establish that
the container is conforming (§2.6); if that has to be established here
rather than earlier, a verifier is what does it, before or during the
load.

The CRC deserves its own sentence, because it is the one check here that
is easy to mistake for something it is not. It catches a **flipped
bit**: a mangled encoding, a truncated transfer, a bad flash write —
accidents that neither the toolchain nor the embedder can see from where
they stand, and which would otherwise put arbitrary bytes in front of a
decoder. It is **not** a security control. CRC-32 is trivially forged,
and an implementation that treats a correct checksum as evidence of
anything but the absence of an accident has misread this paragraph.

A **fault** is different: it happens during execution rather than
before it, there are exactly three of them, and they are §5.5. A fault
ends the invocation. What that means for writes the script had already
made is the embedder's policy (§1.6), not this chapter's.
