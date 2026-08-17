<!--
SPDX-FileCopyrightText: 2026 The MCUScript Contributors
SPDX-License-Identifier: Apache-2.0
-->

# 4. Tables, linking and errors

Chapter 2 described the container's frame; this chapter specifies the
three critical sections the instructions index into, how the references
to the outside world are resolved, and every way that can fail.

## 4.1 Type codes

One byte, used by every table below.

| Code | Type |
|---|---|
| `0x01` | `i32` |
| `0x02` | `i64` |
| `0x03` | `f32` |
| `0x04` | `bool` |
| `0x00` | no value — legal only as a host function's return type |

## 4.2 `CNST` — the constant pool

A count followed by entries; instructions address entries by their
index in this order.

| Offset | Size | Field |
|---|---|---|
| 0 | 1 | `count`, u8 |
| 1 | … | `count` entries |

Each entry is a type code followed by its value, little-endian: 4 bytes
for `i32` and `f32`, 8 for `i64`. `bool` may not appear — it has
dedicated instructions and a pool entry would be a wasted byte.

`count` is one byte, so a container holds at most 255 constants. That
is not a limit any script in this domain approaches, and a wide form is
a reserved extension rather than a cost paid now by every program.

Pool entries are always `valid`. There is no way to write an
`unavailable` or `invalid` literal, and that is deliberate: those
states describe what the world did, not what an author meant.

## 4.3 `ENTR` — entry points

An entry point is a callable start: what the host invokes when a
trigger fires. A container may declare several — a device with three
filters has three — and they share the `CODE`, `CNST` and `HOST`
sections.

| Offset | Size | Field |
|---|---|---|
| 0 | 1 | `count`, u8 |
| 1 | … | `count` records |

Each record:

| Size | Field | |
|---|---|---|
| 2 | `name_offset` | u16 into the string area, the function's name |
| 4 | `code_offset` | u32, the first instruction, relative to `CODE` |
| 1 | `flags` | bit 0: the host may invoke this by name. Other bits reserved |
| 1 | `return_type` | type code, `0x00` for none |
| 1 | `max_stack` | slots |
| 1 | `max_call_depth` | frames below this one, `0` when it calls nothing |
| 1 | `recursion_cap` | the cap of the call-graph cycle this belongs to, `0` for none (§5.4) |
| 1 | `param_count` | arguments the caller pushes; at most `local_count` |
| 1 | `local_count` | |
| `local_count` | `local_types` | one type code per local, in index order |

Records are followed by the **string area**: for each name, one byte of
length and then that many UTF-8 bytes, with no terminator. A record's
`name_offset` addresses the length byte and is relative to the start of
the area, so a name is at most 255 bytes and the area at most 64 KiB.
Identical names are stored once.

**Records are in `code_offset` order**, and their regions tile `CODE`
(§2.6.1); a table out of order is `malformed_section`. The order costs a
writer nothing — code goes into the section in some sequence already,
and the records can be numbered in the same one — and it saves a reader
the only quadratic step in loading a container.

**No two records name the same function** (`malformed_section`). The
bytecode addresses functions by index and a VM would not notice, but a
name is what the host invokes by and what a C backend turns into a
symbol — so two records sharing one would be a program only one backend
can express, which is the thing this specification exists to prevent.

`max_stack` and `max_call_depth` are what the VM allocates from, and it
takes them as given. They are therefore the two fields a producer has
the least freedom about: §2.6 point 5 requires them to be the values the
code actually needs, and a container that gets them wrong is not a
container with a wrong number in it but one whose behaviour is
undefined. A verifier **recomputes and compares** them rather than
asking whether they look plausible; that is the whole of what makes
these two fields checkable at all.

`recursion_cap` is the one number that cannot be derived: a cap is a
*decision* the author made, not a property of the code (§5.4). What is
derivable is which functions form a cycle, so a conforming container has
a cap on every cycle, one cap per cycle, and none on a function outside
one (`recursion_cap_mismatch`) — a number that changes nothing is a
compiler bug or an attempt to make one look harmless.

`param_count` is what makes a call checkable. Arguments become the
callee's first locals (§3.6) and the record does not otherwise
distinguish them, so without a declared arity a caller's pushes could
not be counted and every local would have to be an argument. The first
`param_count` entries of `local_types` are therefore the signature; the
rest are scratch and begin `unavailable`.

**An invocable record declares no parameters** (`entry_takes_parameters`).
The host has no typed argument channel — it communicates with a script
through entities (§5.2) — and inventing one would put the two backends
at odds: the VM would start the unsupplied locals `unavailable` while
the transpiled C would take whatever its caller passed. A trigger value
that a script needs is an entity, which is also where the script can
read it more than once.

Function definitions — the targets of `CALL` (§3.6) — use the same
record layout in the same section. An entry point is a function the
host may invoke by name; a plain function is one only other code calls.
The distinction is `flags` bit 0 rather than a separate table, so the
call-graph analysis of §5.4 sees one uniform set of nodes.

## 4.4 `HOST` — the import table

Everything the script reaches outside itself: entities it reads and
writes, and functions it calls. Each import is a **name**, which is
what makes a container portable across firmware versions — the script
says `"fan.speed"`, not an address, and the address is found when the
container is loaded.

| Offset | Size | Field |
|---|---|---|
| 0 | 1 | `count`, u8 |
| 1 | … | `count` records, then the string area (§4.3) |

Each record:

| Size | Field | |
|---|---|---|
| 2 | `name_offset` | u16 into the string area |
| 1 | `kind` | `0x01` entity, `0x02` function |
| 1 | `access` | entities: `0x01` read, `0x02` write, `0x03` both. Functions: `0x00` |
| 1 | `type` | entities: the value's type code. Functions: the return type code |
| 2 | `dimension` | the profile's dimension id, or `0x0000` for dimensionless |
| 1 | `param_count` | functions only, otherwise `0` |
| `param_count` | `param_types` | type codes, leftmost first |

`LOAD.H`, `STORE.H` and `CALL.H` address records by index.

The `dimension` field is what turns units from a compile-time
convenience into a checked contract. The compiler recorded which
dimension it believed `"fan.speed"` had; the host knows which dimension
it actually has; a mismatch means the script was compiled against a
different world and its numbers would be wrong by a scale factor
(§1.4). It is checked at load, and it is the reason the profile is
pinned in the header as well: the header catches a wholesale profile
change, the dimension field catches a single entity that moved.

## 4.5 Linking

After verification (§2.6) and before execution, every `HOST` record is
resolved once against the embedder's registry. Resolution is by name,
exact match, case-sensitive. After it, access is array indexing and no
name is looked at again — the cost is paid once at load.

For each record the loader checks, in this order:

1. the name exists in the registry;
2. the kind matches — an entity is not a function;
3. the type matches exactly;
4. the dimension matches, or both are dimensionless;
5. the access is available — a read-only entity may not be the target
   of `STORE.H`;
6. for functions, the parameter count and every parameter type match.

Any failure refuses the container. There is no partial link, no
placeholder address, and no deferring the question to first use: a
script that refers to something that is not there must not start,
because the alternative is a device that runs for a week and then
faults when a rarely-taken branch is finally taken.

## 4.6 Errors

Every failure below is a refusal *before execution*, and every one is
distinguishable. A loader reports which and, where an index or a name
is involved, which one — diagnostics for people who did not write the
compiler are a stated goal of this project, and they are impossible if
the loader can only say "invalid".

### Container errors

| Error | Condition |
|---|---|
| `bad_magic` | the first four bytes are not `MCUS` |
| `unsupported_format_version` | `format_version` exceeds what this reader implements |
| `length_mismatch` | the actual size differs from `total_length` |
| `bad_checksum` | the CRC does not match |
| `malformed_section` | a section extends past `total_length`, or the sections do not tile the container exactly |
| `unknown_critical_section` | a section with an uppercase type this reader does not know (§2.3) |
| `missing_section` | one of the four critical sections is absent |
| `duplicate_section` | a critical section appears more than once |
| `reserved_field_set` | a field this version reserves is not zero — the header's `flags`, an `ENTR` record's unused flag bits |
| `entry_takes_parameters` | an `ENTR` record has the invocable flag and a non-zero `param_count` (§4.3) |
| `duplicate_import` | two `HOST` records name the same import |

### Compatibility errors

| Error | Condition |
|---|---|
| `profile_mismatch` | `profile_id` differs, or `profile_major` differs (§2.4) |
| `unsupported_group` | `required_groups` names a group this implementation does not have (§2.5) |

### Verification errors

| Error | Condition |
|---|---|
| `undefined_opcode` | an opcode not assigned, or assigned to a group not required |
| `truncated_instruction` | an instruction's operands extend past `CODE` |
| `bad_branch_target` | a target outside the function's code region, or not on an instruction boundary (§2.6.1) |
| `backward_branch` | a backward jump (§3.8) |
| `unreachable_code` | a byte of a function's region that no path reaches (§2.6.1), or a function no entry point can reach |
| `type_mismatch` | an instruction receives an operand type it does not take |
| `stack_underflow` | an instruction pops from an empty stack on some path |
| `inconsistent_join` | two paths reach the same instruction with different stack shapes |
| `unbalanced_return` | the stack at `RET`/`RET_V` does not hold exactly what the return type requires |
| `stack_depth_mismatch` | the recomputed `max_stack` differs from the declared one |
| `call_depth_mismatch` | the recomputed `max_call_depth` differs from the declared one |
| `uncapped_recursion` | a cycle in the call graph without a declared cap, or whose members declare different ones (§5.4) |
| `recursion_cap_mismatch` | a `recursion_cap` on a function that is in no cycle |
| `index_out_of_range` | an index into `CNST`, `HOST`, the locals or the function table is past its count |
| `kind_mismatch` | `LOAD.H` or `STORE.H` addresses a record the container's own `HOST` table calls a function, or `CALL.H` one it calls an entity |
| `access_denied` | `STORE.H` targets an entity the container's own table declares read-only, or `LOAD.H` a write-only one |

### Linking errors

One per check in §4.5:

| Error | Condition |
|---|---|
| `unknown_import` | the name is not in the registry |
| `kind_mismatch` | the registry has an entity where the container declares a function, or the reverse |
| `import_type_mismatch` | the declared type is not the registry's type |
| `dimension_mismatch` | the declared dimension is not the registry's |
| `access_denied` | the registry declares the entity read-only and the container writes it, or write-only and the container reads it |
| `signature_mismatch` | a host function's parameter count or types differ |

**`kind_mismatch` and `access_denied` appear twice, on purpose.** A
container can contradict *itself* — an instruction that writes an entity
its own table calls read-only — and it can contradict the *registry*. It
is the same thing being wrong and it gets the same name, but the two
happen at different times and only the second needs an embedder: the
first is caught by a host toolchain with no registry in sight, and the
second cannot be. Splitting them into four names would say that a
script writing a read-only entity is two different mistakes depending
on who noticed.

`duplicate_import` is not a linking error at all and is filed above with
the container's own defects, because it needs no registry to see: two
records for one name can hold *different* declared types, and accepting
that would mean the same entity had two contradictory contracts inside
one program.

### What is deliberately not in these tables

**An implementation running out of its own capacity.** A runtime sized
at build time will meet containers with more imports, deeper call
chains or wider stacks than it was built for, and it must refuse them —
but not with a name from above, because every name above says *the
container is wrong*, and this one says the container is fine and the
build is too small. The fix is a rebuild, the refusal is the
implementation's own, and conformance cannot cover it: §"Conformance"
requires accepting every well-formed container, and this is exactly the
case where a conforming implementation does not.

An earlier draft of this chapter had an `import_limit` row for it. It
was removed rather than implemented, because no implementation ever
produced it and neither could: the two readings of it are "the registry
does not have the name" — which is `unknown_import` — and "this build
is too small", which is the paragraph above.

## 4.7 What is not an error here

A host read returning `unavailable` is not a link failure — it is the
normal state of a sensor that has not been read yet, and it is carried
as a value (§1.3), not as a refusal. Linking establishes that the name,
type and dimension are right; whether there is a reading behind it at
any given moment is a runtime matter and always will be.
