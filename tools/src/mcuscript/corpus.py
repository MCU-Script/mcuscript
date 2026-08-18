# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0
"""The conformance corpus: containers with the verdict they must get.

This project has two loaders on purpose — a Python one written for
diagnostics and a C one written for a device — and everywhere they do
the same job they use a different algorithm: a worklist against a
single forward pass, Tarjan against a reachability matrix. Two methods
over one specification is worth more than two copies of one method, but
only if something makes them answer the same question. That is this.

**The corpus is bytes, and the bytes are committed.** Not a list of
programs each implementation assembles for itself: an implementation
that agrees with itself about what it wrote is not evidence. The
definitions below produce the files under ``spec/corpus/``, a test
compares the committed bytes against what they produce today, and a
change to the container format therefore shows up as a reviewable diff
rather than as a corpus that quietly no longer tests what it says.

It belongs to the specification rather than to either implementation,
which is why it lives in ``spec/``. A third party writing a conforming
loader should be able to take that directory alone and find out where
they disagree with this document, without reading a line of Python.

Every refusal §4.6 names has at least one entry, and a test enforces
that. It is a stronger property than it sounds: a name that no
container can produce is a name nobody has checked, and writing this
found one — `import_limit`, which was in the specification and which
neither implementation ever raised, because the two things it could
have meant are `unknown_import` and "this build is too small".
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

from .asm import assemble
from .container import (
    Access,
    Constant,
    Container,
    Function,
    Import,
    ImportKind,
)
from .opcodes import Group, ValType

#: The profile every corpus container is compiled against. A loader
#: running the corpus must present this one, or every container is a
#: `profile_mismatch` and nothing else gets tested.
PROFILE_ID = 1
PROFILE_MAJOR = 0
PROFILE_MINOR = 0

_HEAD = f".profile {PROFILE_ID} {PROFILE_MAJOR}.{PROFILE_MINOR}\n"

#: The five verdict classes, named after §4.6's own headings plus one
#: for the containers that must be accepted. The split is not cosmetic:
#: it says *which* implementation owes the verdict. A host toolchain
#: does not link — resolving names against a registry is the embedder's,
#: at load — so on a `linking` case the host verifier must **accept**,
#: and only a full loader refuses.
STAGES = ("ok", "container", "compatibility", "verification", "linking")


@dataclass(frozen=True, slots=True)
class Case:
    name: str
    stage: str
    #: The refusal a conforming loader gives, or "" when it must accept.
    refusal: str
    description: str
    blob: bytes
    #: A host description in the format of `runtime/tests/hostfile.h`,
    #: or "" for a world with nothing in it.
    host: str = ""
    #: Whether a **runtime** owes this verdict too, or only a verifier.
    #: A runtime does not verify (spec §2.6, ADR 0006), so it answers for
    #: identity — is this container meant for me — and for bytes it
    #: cannot parse, and for nothing else. Derived from the stage where
    #: the stage decides it; stated per case where it does not, because
    #: `container` holds both "these bytes make no sense" and "this
    #: container is a bad program", and only the first is a runtime's.
    runtime: bool | None = None

    @property
    def runtime_refuses(self) -> bool:
        if self.runtime is not None:
            return self.runtime
        return self.stage != "verification"

    @property
    def filename(self) -> str:
        return f"{self.name}.mcs"

    @property
    def host_filename(self) -> str:
        return f"{self.name}.host" if self.host else ""


# -- building blocks ------------------------------------------------------


def _asm(body: str) -> bytes:
    return assemble(_HEAD + body).encode()


def _raw(
    code: bytes,
    *,
    functions: list[Function] | None = None,
    imports: tuple[Import, ...] = (),
    constants: tuple[Constant, ...] = (),
    groups: int = Group.CORE.mask,
    max_stack: int = 0,
) -> bytes:
    """A container assembled by hand.

    Most of the malformed cases cannot come from the assembler, and that
    is the point of having one: an out-of-range index or a forged stack
    depth is exactly what an assembler prevents and exactly what a
    verifier must catch.
    """
    container = Container(
        code=code,
        constants=list(constants),
        imports=list(imports),
        functions=(
            functions
            if functions is not None
            else [Function("go", 0, max_stack=max_stack)]
        ),
        profile_id=PROFILE_ID,
        profile_major=PROFILE_MAJOR,
        profile_minor=PROFILE_MINOR,
    )
    return container.encode(required_groups=groups)


def _recrc(blob: bytes) -> bytes:
    """Recompute the checksum after surgery.

    Every mutated case below does this, so that each container has
    exactly **one** defect. A corpus entry that is wrong in two ways
    tests whichever check happens to run first, which is a test of the
    implementation's order rather than of the container.
    """
    zeroed = blob[:24] + b"\0\0\0\0" + blob[28:]
    crc = zlib.crc32(zeroed) & 0xFFFFFFFF
    return blob[:24] + struct.pack("<I", crc) + blob[28:]


def _patch(blob: bytes, offset: int, data: bytes) -> bytes:
    return _recrc(blob[:offset] + data + blob[offset + len(data) :])


def _sections(blob: bytes) -> list[tuple[str, int, int]]:
    """(type, start of the section header, total size including padding)."""
    out = []
    offset = 28
    while offset < len(blob):
        (length,) = struct.unpack_from("<I", blob, offset + 4)
        padded = 8 + length + ((-length) % 4)
        out.append((blob[offset : offset + 4].decode("ascii"), offset, padded))
        offset += padded
    return out


def _rebuild(blob: bytes, body: bytes) -> bytes:
    """A new container from a new section body, with the header fixed."""
    total = 28 + len(body)
    header = blob[:8] + struct.pack("<I", total) + blob[12:28]
    return _recrc(header + body)


def _body(blob: bytes) -> bytes:
    return blob[28:]


# -- the world the linking cases are resolved against ---------------------

_HOST_TEMP = "entity read i32 temp dim 1 = 291\nentity write i32 fan.speed dim 2\n"


# -- the cases ------------------------------------------------------------

MINIMAL = _asm(".entry go\n  ret\n")

WORKED = _asm(
    ".entity read i32 temp dim 1\n"
    ".entity write i32 fan.speed dim 2\n"
    ".entry on_temp\n"
    "  load.h temp\n  const.i32.s16 280\n  gt.i32\n  jmp_if_false L1\n"
    "  const.i32.s8 3\n  jmp end\n"
    "L1:\n  load.h temp\n  const.i32.s16 250\n  gt.i32\n  jmp_if_false L2\n"
    "  const.i32.s8 2\n  jmp end\n"
    "L2:\n  const.i32.s8 0\n"
    "end:\n  store.h fan.speed\n  ret\n"
)


def _cases() -> list[Case]:
    cases: list[Case] = []

    def case(name, stage, refusal, description, blob, host="", runtime=None):
        cases.append(Case(name, stage, refusal, description, blob, host, runtime))

    # -- accepted ---------------------------------------------------
    case(
        "ok-minimal",
        "ok",
        "",
        "One entry point that returns immediately. The smallest thing a "
        "loader must accept.",
        MINIMAL,
    )
    case(
        "ok-worked-example",
        "ok",
        "",
        "The threshold ladder of specification §3.9, with the imports it "
        "reads and writes.",
        WORKED,
        _HOST_TEMP,
    )
    case(
        "ok-every-group",
        "ok",
        "",
        "One container that requires every instruction group: i64, "
        "i64div, float, call, bits and loop alongside core.",
        _asm(
            ".const big i64 4294967296\n"
            ".const two i64 2\n"
            ".const half f32 0.5\n"
            ".entry go -> i32\n"
            "  .local turns i32\n"
            "  const.i32.s8 2\n"
            "  store.l turns\n"
            # Turns twice and leaves by its own test, so the guard is
            # what an `ok` case should show it as: a ceiling nobody hits.
            "top:\n"
            "  loop.guard turns\n"
            "  load.l turns\n"
            "  const.i32.s8 0\n"
            "  gt.i32\n"
            "  jmp_if_true top\n"
            "  const.i64 big\n"
            "  const.i64 two\n"
            "  div.i64\n"
            "  wrap.i64_i32\n"
            "  const.i32.s8 3\n"
            "  and.i32\n"
            "  call scale\n"
            "  ret_v\n"
            ".fn scale -> i32\n"
            "  .param n i32\n"
            "  load.l n\n"
            "  convert.i32_f32\n"
            "  const.f32 half\n"
            "  mul.f32\n"
            "  trunc.f32_i32\n"
            "  ret_v\n"
        ),
    )
    case(
        "ok-capped-recursion",
        "ok",
        "",
        "A cycle in the call graph with a declared cap — accepted at "
        "load, bounded at run time (§5.4).",
        _asm(
            ".entry go -> i32\n"
            "  const.i32.s8 3\n"
            "  call down\n"
            "  ret_v\n"
            ".fn down -> i32\n"
            "  .param n i32\n"
            "  .cap 5\n"
            "  load.l n\n"
            "  const.i32.s8 0\n"
            "  gt.i32\n"
            "  jmp_if_false bottom\n"
            "  load.l n\n"
            "  const.i32.s8 1\n"
            "  sub.i32\n"
            "  call down\n"
            "  ret_v\n"
            "bottom:\n"
            "  const.i32.s8 0\n"
            "  ret_v\n"
        ),
    )

    # -- the container ----------------------------------------------
    case(
        "bad-magic",
        "container",
        "bad_magic",
        "The first four bytes are not MCUS.",
        _patch(MINIMAL, 0, b"XCUS"),
    )
    case(
        "unsupported-format-version",
        "container",
        "unsupported_format_version",
        "The header claims format version 2. A reader refuses anything "
        "above the version it implements rather than guessing.",
        _patch(MINIMAL, 4, struct.pack("<H", 2)),
    )
    case(
        "length-mismatch",
        "container",
        "length_mismatch",
        "total_length is one byte more than the file.",
        _patch(MINIMAL, 8, struct.pack("<I", len(MINIMAL) + 1)),
    )
    case(
        "bad-checksum",
        "container",
        "bad_checksum",
        "Everything is well-formed and the stored CRC is wrong — so this "
        "is the one case that must not be repaired before it is checked.",
        MINIMAL[:24] + struct.pack("<I", 0xDEADBEEF) + MINIMAL[28:],
    )
    case(
        "malformed-section",
        "container",
        "malformed_section",
        "A section declares more bytes than the container holds.",
        _patch(MINIMAL, 32, struct.pack("<I", 0xFFFF)),
    )
    case(
        "unknown-critical-section",
        "container",
        "unknown_critical_section",
        "A section whose type starts with an uppercase letter and which "
        "this format version does not define. Lowercase would be "
        "ancillary and carried through untouched (§2.3).",
        _rebuild(MINIMAL, _body(MINIMAL) + b"ZZZZ" + struct.pack("<I", 0)),
    )
    case(
        "missing-section",
        "container",
        "missing_section",
        "HOST is absent. All four critical sections are mandatory; an "
        "empty table is a count of zero, not an absent section.",
        _without_section(MINIMAL, "HOST"),
    )
    case(
        "duplicate-section",
        "container",
        "duplicate_section",
        "CNST appears twice.",
        _duplicate_section(MINIMAL, "CNST"),
    )
    case(
        "reserved-field-set",
        "container",
        "reserved_field_set",
        "The header's flags field is not zero. Every bit of it is "
        "reserved in version 1, and a reader that ignored one would "
        "accept a container written for a version it does not know.",
        _patch(MINIMAL, 6, struct.pack("<H", 1)),
    )
    case(
        "entry-takes-parameters",
        "container",
        "entry_takes_parameters",
        "An invocable record declares a parameter. The host has no way "
        "to pass one, and the two backends would disagree about what an "
        "unsupplied one holds (§4.3).",
        _raw(
            b"\x23",
            functions=[
                Function("go", 0, local_types=(ValType.I32,), param_count=1),
            ],
        ),
        runtime=False,
    )

    # -- compatibility ----------------------------------------------
    case(
        "profile-mismatch",
        "compatibility",
        "profile_mismatch",
        "Compiled against a different profile. A changed base unit makes "
        "existing bytecode silently wrong, so this is a refusal rather "
        "than arithmetic on wrongly scaled numbers (§1.4).",
        _patch(MINIMAL, 12, struct.pack("<I", PROFILE_ID + 1)),
    )
    case(
        "unsupported-group",
        "compatibility",
        "unsupported_group",
        "The header requires group 7, which this version of the "
        "specification does not define — the shape a container from a "
        "later version has. The check reads the header, not the code, "
        "which is what lets a build without float say no at load rather "
        "than meet a float opcode at run time.",
        _patch(MINIMAL, 20, struct.pack("<I", Group.CORE.mask | (1 << 7))),
    )

    # -- verification -----------------------------------------------
    case(
        "undefined-opcode",
        "verification",
        "undefined_opcode",
        "Opcode 0x00, which is deliberately unassigned so that a run of "
        "erased flash is refused rather than executed (§3.1).",
        _raw(b"\x00"),
    )
    case(
        "opcode-outside-the-required-groups",
        "verification",
        "undefined_opcode",
        "add.i64 in a container whose header requires only `core`. The "
        "opcode is assigned, and a complete build implements it — but "
        "§2.6 point 1 asks whether it is in a group the *container* required, "
        "and it is not. Without this the header could under-declare, and "
        "the header is the whole of what lets a narrowed build refuse a "
        "container before meeting an instruction it does not have (§2.5).",
        _raw(
            b"\x40\x00\x40\x00\x41\x0b\x23",
            constants=(Constant(ValType.I64, 7),),
            max_stack=2,
        ),
    )
    case(
        "truncated-instruction",
        "verification",
        "truncated_instruction",
        "const.i32.s16 needs three bytes and two remain.",
        _raw(b"\x02\x01"),
    )
    case(
        "bad-branch-target",
        "verification",
        "bad_branch_target",
        "A branch into the middle of an instruction — the classic "
        "verifier bypass. Both readings are individually well-typed: the "
        "immediate of `const.i32.s16 1281` is itself a valid "
        "`const.i32.s8 5`, both push one i32 and both fall into the same "
        "`drop`. Only counting how often each byte is decoded "
        "distinguishes this from honest code (§2.6.1).",
        _raw(b"\x04\x21\x01\x00\x02\x01\x05\x0b\x23", max_stack=1),
    )
    case(
        "branch-past-the-end",
        "verification",
        "bad_branch_target",
        "A branch to an offset outside the function's own code region.",
        _raw(b"\x20\x64\x00\x23"),
    )
    case(
        "unguarded-loop",
        "verification",
        "unguarded_loop",
        "A jump to itself. A backward branch is a cycle, and a cycle is "
        "bounded only if it lands on a `loop.guard` — which is what "
        "keeps termination provable from the container and lets the "
        "runtime carry no execution budget (§3.8, §5.6).",
        _raw(b"\x20\xfd\xff"),
    )
    case(
        "loop-counter-written",
        "verification",
        "loop_counter_written",
        "A guarded loop that assigns its own counter, so the countdown "
        "restarts every turn and the bound never arrives. The guard is "
        "in the right place; what fails is the one other thing the "
        "bound rests on (§3.8).",
        _raw(
            # loop.guard v0 / const 0 / store.l v0 / jmp back
            b"\xa0\x00\x01\x00\x07\x00\x20\xf7\xff",
            functions=[Function("go", 0, local_types=(ValType.I32,), max_stack=1)],
            groups=Group.CORE.mask | Group.LOOP.mask,
            max_stack=1,
        ),
    )
    case(
        "unreachable-code",
        "verification",
        "unreachable_code",
        "A byte after the return that no path reaches. Not a safety "
        "problem — it cannot execute — but a container should mean one "
        "thing, and a dead byte is an encoder bug or something smuggled "
        "in.",
        _raw(b"\x23\x04"),
    )
    case(
        "unreachable-function",
        "verification",
        "unreachable_code",
        "The same rule one level up: a function no entry point reaches. "
        "A VM would never notice; a C backend turns functions into "
        "file-local symbols and a C compiler rejects one nobody calls, "
        "so this is a container only one backend can express.",
        _raw(
            b"\x23\x23",
            functions=[Function("go", 0), Function("orphan", 1, invocable=False)],
        ),
    )
    case(
        "records-out-of-code-order",
        "container",
        "malformed_section",
        "Two functions whose regions tile CODE, declared in the wrong "
        "order (§4.3). The bytes are a valid program; only the table's "
        "order is wrong, and a reader promised the order would compute "
        "the second function's extent from the first one's start.",
        _raw(
            b"\x23\x23",
            functions=[Function("second", 1), Function("first", 0)],
        ),
        runtime=False,
    )
    case(
        "type-mismatch",
        "verification",
        "type_mismatch",
        "add.i32 applied to two bools.",
        _raw(b"\x04\x04\x10\x23", max_stack=2),
    )
    case(
        "stack-underflow",
        "verification",
        "stack_underflow",
        "add.i32 with an empty stack.",
        _raw(b"\x10\x23"),
    )
    case(
        "inconsistent-join",
        "verification",
        "inconsistent_join",
        "Two paths reach one instruction with different stack shapes. "
        "This is what makes the untagged slots of §1.2 safe: if the type "
        "at every position is the same by every route, the runtime never "
        "has to ask.",
        # const.true; jmp_if_false +1 → 5; const.true; drop; ret.
        # The branch arrives at the `drop` with an empty stack and the
        # fall-through with a bool on it.
        _raw(b"\x04\x21\x01\x00\x04\x0b\x23", max_stack=1),
    )
    case(
        "unbalanced-return",
        "verification",
        "unbalanced_return",
        "A function that returns nothing, returning with a value still on the stack.",
        _raw(b"\x04\x23", max_stack=1),
    )
    case(
        "stack-depth-mismatch",
        "verification",
        "stack_depth_mismatch",
        "The code needs one slot and the record claims ninety-nine. The "
        "VM allocates from that number, so the verifier recomputes it "
        "rather than asking whether it is plausible (§2.6).",
        _raw(b"\x04\x0b\x23", max_stack=99),
    )
    case(
        "call-depth-mismatch",
        "verification",
        "call_depth_mismatch",
        "The recomputed worst-case frame count differs from the declared one.",
        _raw(
            b"\x80\x01\x23\x23",
            functions=[
                Function("go", 0, max_call_depth=7),
                Function("helper", 3, invocable=False),
            ],
            groups=Group.CORE.mask | Group.CALL.mask,
        ),
    )
    case(
        "uncapped-recursion",
        "verification",
        "uncapped_recursion",
        "A function that calls itself with no declared cap. The cap is "
        "the one number a verifier cannot derive — it is a decision the "
        "author made — so its absence is a refusal (§5.4).",
        _raw(
            b"\x80\x00\x23",
            functions=[Function("go", 0)],
            groups=Group.CORE.mask | Group.CALL.mask,
        ),
    )
    case(
        "recursion-cap-mismatch",
        "verification",
        "recursion_cap_mismatch",
        "A cap on a function that is in no cycle. A number that bounds "
        "nothing reads as a safeguard and is not.",
        _raw(b"\x23", functions=[Function("go", 0, recursion_cap=5)]),
    )
    case(
        "index-out-of-range",
        "verification",
        "index_out_of_range",
        "const.i32 addresses a constant pool that is empty.",
        _raw(b"\x03\x00\x23", max_stack=1),
    )
    case(
        "kind-mismatch",
        "verification",
        "kind_mismatch",
        "load.h addresses a host *function*. An entity is not a "
        "function, and the container's own table says so before any "
        "registry is consulted.",
        _raw(
            b"\x08\x00\x0b\x23",
            imports=(Import("clamp", ImportKind.FUNCTION, Access.NONE, ValType.I32),),
            max_stack=1,
        ),
    )
    case(
        "access-denied",
        "verification",
        "access_denied",
        "store.h targets an entity the container itself declares read-only.",
        _raw(
            b"\x01\x01\x09\x00\x23",
            imports=(Import("temp", ImportKind.ENTITY, Access.READ, ValType.I32, 1),),
            max_stack=1,
        ),
    )
    case(
        "duplicate-import",
        "container",
        "duplicate_import",
        "Two HOST records name the same entity. Not a harmless "
        "redundancy: the two records can declare different types, and "
        "then one name has two contradictory contracts inside one "
        "program.",
        _raw(
            b"\x23",
            imports=(
                Import("temp", ImportKind.ENTITY, Access.READ, ValType.I32, 1),
                Import("temp", ImportKind.ENTITY, Access.READ, ValType.I64, 1),
            ),
        ),
        runtime=False,
    )

    # -- linking ----------------------------------------------------
    #
    # A host toolchain does not resolve names against a registry — that
    # is the embedder's, at load — so on every case below the host
    # verifier must *accept* and only a full loader refuses.
    case(
        "unknown-import",
        "linking",
        "unknown_import",
        "The container reads an entity the registry does not have. There "
        "is no partial link and no deferring the question to first use: "
        "a script that refers to something absent must not start (§4.5).",
        _asm(
            ".entity read i32 nowhere dim 1\n"
            ".entry go -> i32\n  load.h nowhere\n  ret_v\n"
        ),
        "entity read i32 elsewhere dim 1 = 5\n",
    )
    case(
        "import-type-mismatch",
        "linking",
        "import_type_mismatch",
        "The container declares i32 and the registry offers i64.",
        _asm(".entity read i32 temp dim 1\n.entry go -> i32\n  load.h temp\n  ret_v\n"),
        "entity read i64 temp dim 1 = 5\n",
    )
    case(
        "dimension-mismatch",
        "linking",
        "dimension_mismatch",
        "Same name, same type, different dimension — the script was "
        "compiled against a different world and its numbers would be "
        "wrong by a scale factor. The header catches a wholesale profile "
        "change; this catches the one entity that moved (§4.4).",
        _asm(".entity read i32 temp dim 1\n.entry go -> i32\n  load.h temp\n  ret_v\n"),
        "entity read i32 temp dim 9 = 5\n",
    )
    case(
        "signature-mismatch",
        "linking",
        "signature_mismatch",
        "A host function the container calls with one argument and the "
        "registry declares with two.",
        _asm(
            ".hostfn i32 clamp i32\n"
            ".entry go -> i32\n  const.i32.s8 1\n  call.h clamp\n  ret_v\n"
        ),
        "function i32 clamp i32 i32 = 7\n",
    )

    return cases


def _without_section(blob: bytes, type_: str) -> bytes:
    body = b""
    for name, start, size in _sections(blob):
        if name != type_:
            body += blob[start : start + size]
    return _rebuild(blob, body)


def _duplicate_section(blob: bytes, type_: str) -> bytes:
    body = b""
    for name, start, size in _sections(blob):
        body += blob[start : start + size]
        if name == type_:
            body += blob[start : start + size]
    return _rebuild(blob, body)


def cases() -> tuple[Case, ...]:
    return tuple(_cases())


# -- the manifest ---------------------------------------------------------


def manifest() -> str:
    """``corpus.toml``, written by hand rather than by a library.

    The toolchain has no runtime dependencies and `tomllib` only reads,
    so the writer is here. The format is small on purpose: a third party
    should be able to consume it without a TOML parser if they would
    rather not have one.
    """
    out = [
        "# The MCUScript conformance corpus.",
        "#",
        "# Each case is a container and the verdict a conforming verifier",
        "# must give it. `runtime` says whether a runtime, which does not",
        "# verify, owes the same verdict. See README.md in this directory.",
        "#",
        "# Generated by mcuscript from tools/src/mcuscript/corpus.py.",
        "# Do not edit.",
        "",
        f"profile_id = {PROFILE_ID}",
        f"profile_major = {PROFILE_MAJOR}",
        f"profile_minor = {PROFILE_MINOR}",
        "",
    ]
    for c in cases():
        out.append("[[case]]")
        out.append(f'name = "{c.name}"')
        out.append(f'file = "{c.filename}"')
        out.append(f'stage = "{c.stage}"')
        out.append(f'refusal = "{c.refusal}"')
        out.append(f"runtime = {str(c.runtime_refuses).lower()}")
        if c.host:
            out.append(f'host = "{c.host_filename}"')
        out.append(f"description = {_toml_string(c.description)}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def _toml_string(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def write(directory) -> list[str]:
    """Write the corpus. Returns the filenames it produced, README
    excluded — that one is prose and is maintained by hand."""
    from pathlib import Path

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for c in cases():
        (directory / c.filename).write_bytes(c.blob)
        written.append(c.filename)
        if c.host:
            (directory / c.host_filename).write_text(c.host, encoding="utf-8")
            written.append(c.host_filename)
    (directory / "corpus.toml").write_text(manifest(), encoding="utf-8")
    written.append("corpus.toml")
    return written
