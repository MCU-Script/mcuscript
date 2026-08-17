<!--
SPDX-FileCopyrightText: 2026 The MCUScript Contributors
SPDX-License-Identifier: Apache-2.0
-->

# 2. The container

A compiled program is one **container**: a header followed by
type-tagged sections. It is what a compiler emits and what a VM loads,
and it is untrusted input at every point after the compiler released
it.

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

That is a duty, and §2.6 point 1 is its enforcement: an opcode belonging
to a group the header does **not** require is undefined *for this
container*, and refused as `undefined_opcode`, however complete the
implementation is. Stated separately because it is easy to read the
group check as a courtesy to small builds and skip it in a large one.
It is not: a container that under-declares would pass the check above on
every implementation that has the group, and reach an implementation
that does not with nothing left to stop it. The header can only protect
a narrowed build if a complete build refuses to accept a wrong one.

## 2.6 Verification

**Verification is mandatory. It is not a build option, a debug feature
or a fast-path skip.** An implementation that runs unverified
containers does not conform.

The reason is narrow and decisive: the `ENTR` section states, per entry
point, the maximum operand-stack depth and call depth the program
needs, and the VM *allocates from those numbers*. They come from an
untrusted file. A container claiming a depth of two while needing
twenty would overflow a stack sized from its own claim, into whatever
is next to it — silent memory corruption on a device with no MMU. This
is the classic verifier bypass, and it is why the JVM made verification
unconditional.

So the verifier does not check that the declared numbers are plausible.
**It recomputes them**, by the same arithmetic the compiler used, and
refuses the container if what it computes differs from what the file
claims. The file's numbers are then either redundant or a lie, and
either way the VM uses its own.

Verification walks each function from its first instruction along every
path its branches can take. Everything below is established before any
instruction runs:

1. every instruction is fully contained in its function's code region
   and its opcode is defined in a required group;
2. every branch target is a valid instruction boundary within the same
   function's region, and lies forward (§3.8);
3. the operand stack is type-consistent along every path — the type
   stack at a join point is the same by every route to it — and every
   instruction receives the types it takes;
4. the stack is empty at `RET`, or holds exactly the return value;
5. the maximum stack depth and call depth, recomputed, match `ENTR`;
6. the call graph's cycles all carry a declared depth cap, no function
   outside a cycle carries one, and the worst-case call depth follows
   from it;
7. every index into `CNST`, `HOST`, the local slots and the function
   table is in range.

Points 3 and 4 are what make the untagged slots of §1.2 safe: nothing
at runtime checks a type because nothing at runtime *can* be the wrong
type.

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

Within a region, verification counts how often each byte is decoded, and
neither zero nor twice is allowed:

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

Loading is: check the header, check `total_length` and the CRC, walk
the sections, refuse on an unrecognised critical section, check the
profile, check the required groups, verify (§2.6), then resolve the
`HOST` table against the embedder's registry.

Every failure is a **named, typed refusal before execution**, never a
partial load and never a silent degradation. The full error taxonomy —
including the eight distinct ways `HOST` resolution can fail — is
chapter 4.

A **fault** is different: it happens during execution rather than
before it, there are exactly three of them, and they are §5.5. A fault
ends the invocation. What that means for writes the script had already
made is the embedder's policy (§1.6), not this chapter's.
