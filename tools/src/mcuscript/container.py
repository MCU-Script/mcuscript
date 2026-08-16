# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0
"""The container format of specification chapter 2, and the tables of
chapter 4.

This module reads and writes containers and does nothing else — it does
not verify the code (:mod:`mcuscript.verify`) and it does not link
(that is the embedder's, at load). The split matters: parsing is where
a hostile file gets its first say, so every read here is bounds-checked
and every failure is a named refusal rather than an exception from the
struct module.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field

from .errors import Refusal, refuse
from .opcodes import Group, ValType, group_names

MAGIC = b"MCUS"
FORMAT_VERSION = 1
HEADER_SIZE = 28

_HEADER = struct.Struct("<4sHHIIHHII")
assert _HEADER.size == HEADER_SIZE

#: Sections whose first character is uppercase are critical: an
#: unrecognised one is a refusal (§2.3). These four are the ones this
#: format version defines, and all four are mandatory — an empty table
#: is a count of zero, not an absent section.
CRITICAL_SECTIONS = ("CODE", "CNST", "ENTR", "HOST")


class ImportKind:
    ENTITY = 0x01
    FUNCTION = 0x02


class Access:
    NONE = 0x00
    READ = 0x01
    WRITE = 0x02
    BOTH = 0x03


#: Bit 0 of an ``ENTR`` record's flags: the host may invoke this by
#: name. A record without it is a plain function, reachable only from
#: other code in the same container (§4.3).
ENTRY_INVOCABLE = 0x01


@dataclass(frozen=True, slots=True)
class Constant:
    type: ValType
    value: int | float


@dataclass(frozen=True, slots=True)
class Function:
    """An ``ENTR`` record: an entry point, or a plain function."""

    name: str
    code_offset: int
    return_type: ValType = ValType.VOID
    max_stack: int = 0
    max_call_depth: int = 0
    local_types: tuple[ValType, ...] = ()
    invocable: bool = True
    #: Recursion cap for the call-graph cycle this function belongs to,
    #: or 0 when it is in no cycle (§5.4). Written by the compiler,
    #: recomputed by the verifier.
    recursion_cap: int = 0


@dataclass(frozen=True, slots=True)
class Import:
    """A ``HOST`` record: an entity the script reads or writes, or a
    function it calls."""

    name: str
    kind: int
    access: int
    type: ValType
    dimension: int = 0
    param_types: tuple[ValType, ...] = ()


@dataclass(frozen=True, slots=True)
class Section:
    """An ancillary section carried through untouched."""

    type: str
    data: bytes


@dataclass(slots=True)
class Container:
    code: bytes = b""
    constants: list[Constant] = field(default_factory=list)
    functions: list[Function] = field(default_factory=list)
    imports: list[Import] = field(default_factory=list)
    ancillary: list[Section] = field(default_factory=list)

    profile_id: int = 0
    profile_major: int = 0
    profile_minor: int = 0
    format_version: int = FORMAT_VERSION
    flags: int = 0
    #: Set on encode from the code itself; carried verbatim on decode so
    #: a lying header survives to be caught by the verifier.
    required_groups: int = 0

    # -- encoding --------------------------------------------------------

    def encode(self, *, required_groups: int | None = None) -> bytes:
        """Serialise. ``required_groups`` defaults to the mask the code
        actually needs; passing one is for building test containers whose
        header lies."""
        from .opcodes import groups_used

        mask = groups_used(self.code) if required_groups is None else required_groups
        self.required_groups = mask

        body = b"".join(
            _pack_section(t, d)
            for t, d in (
                ("CODE", self.code),
                ("CNST", _encode_constants(self.constants)),
                ("ENTR", _encode_functions(self.functions)),
                ("HOST", _encode_imports(self.imports)),
            )
        )
        body += b"".join(_pack_section(s.type, s.data) for s in self.ancillary)

        total = HEADER_SIZE + len(body)
        header = _HEADER.pack(
            MAGIC,
            self.format_version,
            self.flags,
            total,
            self.profile_id,
            self.profile_major,
            self.profile_minor,
            mask,
            0,
        )
        blob = header + body
        crc = zlib.crc32(blob) & 0xFFFFFFFF
        return blob[:24] + struct.pack("<I", crc) + blob[28:]

    # -- decoding --------------------------------------------------------

    @classmethod
    def decode(cls, blob: bytes) -> Container:
        if len(blob) < HEADER_SIZE:
            raise refuse(
                Refusal.LENGTH_MISMATCH,
                detail=f"{len(blob)} bytes, a header needs {HEADER_SIZE}",
            )
        (
            magic,
            format_version,
            flags,
            total_length,
            profile_id,
            profile_major,
            profile_minor,
            required_groups,
            crc,
        ) = _HEADER.unpack_from(blob, 0)

        if magic != MAGIC:
            raise refuse(Refusal.BAD_MAGIC, detail=f"{magic!r}")
        if format_version > FORMAT_VERSION:
            raise refuse(
                Refusal.UNSUPPORTED_FORMAT_VERSION,
                detail=f"container says {format_version}, this reader "
                f"implements {FORMAT_VERSION}",
            )
        if total_length != len(blob):
            raise refuse(
                Refusal.LENGTH_MISMATCH,
                detail=f"header says {total_length}, the file is {len(blob)}",
            )
        if flags != 0:
            raise refuse(
                Refusal.RESERVED_FIELD_SET,
                where="header flags",
                detail=f"0x{flags:04X}; every bit is reserved in version 1",
            )

        zeroed = blob[:24] + b"\0\0\0\0" + blob[28:]
        actual = zlib.crc32(zeroed) & 0xFFFFFFFF
        if actual != crc:
            raise refuse(
                Refusal.BAD_CHECKSUM,
                detail=f"header says 0x{crc:08X}, the bytes give 0x{actual:08X}",
            )

        sections, ancillary = _walk_sections(blob)

        self = cls(
            code=sections["CODE"],
            constants=_decode_constants(sections["CNST"]),
            functions=_decode_functions(sections["ENTR"]),
            imports=_decode_imports(sections["HOST"]),
            ancillary=ancillary,
            profile_id=profile_id,
            profile_major=profile_major,
            profile_minor=profile_minor,
            format_version=format_version,
            flags=flags,
        )
        self.required_groups = required_groups
        return self

    # -- compatibility ---------------------------------------------------

    def check_profile(self, profile_id: int, major: int, minor: int) -> None:
        """§2.4: a differing id or major version is a refusal, because a
        changed base unit produces wrong numbers and no symptom."""
        if self.profile_id != profile_id or self.profile_major != major:
            raise refuse(
                Refusal.PROFILE_MISMATCH,
                detail=f"compiled against {self.profile_id}"
                f" v{self.profile_major}.{self.profile_minor}, "
                f"this host carries {profile_id} v{major}.{minor}",
            )

    def check_groups(self, implemented: frozenset[Group]) -> None:
        """§2.5: a required group this build does not have is a refusal at
        load, in words, before anything runs."""
        available = 0
        for group in implemented:
            available |= group.mask
        missing = self.required_groups & ~available
        if missing:
            raise refuse(
                Refusal.UNSUPPORTED_GROUP,
                detail="this build does not implement "
                + ", ".join(group_names(missing)),
            )


# -- section framing ------------------------------------------------------


def _pack_section(type_: str, data: bytes) -> bytes:
    raw = type_.encode("ascii")
    assert len(raw) == 4
    padding = (-len(data)) % 4
    return raw + struct.pack("<I", len(data)) + data + b"\0" * padding


def _walk_sections(blob: bytes) -> tuple[dict[str, bytes], list[Section]]:
    """Walk the section list, refusing anything that does not tile the
    container exactly."""
    found: dict[str, bytes] = {}
    ancillary: list[Section] = []
    offset = HEADER_SIZE
    end = len(blob)

    while offset < end:
        if offset + 8 > end:
            raise refuse(
                Refusal.MALFORMED_SECTION,
                where=f"offset {offset}",
                detail="a section header needs 8 bytes and fewer remain",
            )
        raw_type = blob[offset : offset + 4]
        (length,) = struct.unpack_from("<I", blob, offset + 4)
        data_start = offset + 8
        padded = length + ((-length) % 4)
        if data_start + padded > end:
            raise refuse(
                Refusal.MALFORMED_SECTION,
                where=f"offset {offset}",
                detail=f"declares {length} bytes, only {end - data_start} remain",
            )
        if any(c < 0x20 or c > 0x7E for c in raw_type):
            raise refuse(
                Refusal.MALFORMED_SECTION,
                where=f"offset {offset}",
                detail=f"section type is not printable ASCII: {raw_type!r}",
            )

        type_ = raw_type.decode("ascii")
        data = blob[data_start : data_start + length]
        critical = "A" <= type_[0] <= "Z"

        if critical:
            if type_ not in CRITICAL_SECTIONS:
                raise refuse(
                    Refusal.UNKNOWN_CRITICAL_SECTION,
                    where=type_,
                    detail="a critical section this reader does not implement",
                )
            if type_ in found:
                raise refuse(Refusal.DUPLICATE_SECTION, where=type_)
            found[type_] = data
        else:
            ancillary.append(Section(type_, data))

        offset = data_start + padded

    for required in CRITICAL_SECTIONS:
        if required not in found:
            raise refuse(Refusal.MISSING_SECTION, where=required)
    return found, ancillary


# -- a bounds-checked cursor ----------------------------------------------


class _Cursor:
    __slots__ = ("data", "pos", "what")

    def __init__(self, data: bytes, what: str) -> None:
        self.data = data
        self.pos = 0
        self.what = what

    def _need(self, n: int) -> None:
        if self.pos + n > len(self.data):
            raise refuse(
                Refusal.MALFORMED_SECTION,
                where=f"{self.what} offset {self.pos}",
                detail=f"needs {n} more bytes, {len(self.data) - self.pos} remain",
            )

    def u8(self) -> int:
        self._need(1)
        v = self.data[self.pos]
        self.pos += 1
        return v

    def u16(self) -> int:
        self._need(2)
        (v,) = struct.unpack_from("<H", self.data, self.pos)
        self.pos += 2
        return v

    def u32(self) -> int:
        self._need(4)
        (v,) = struct.unpack_from("<I", self.data, self.pos)
        self.pos += 4
        return v

    def bytes(self, n: int) -> bytes:
        self._need(n)
        v = self.data[self.pos : self.pos + n]
        self.pos += n
        return v

    def type_code(self, *, allow_void: bool = False) -> ValType:
        raw = self.u8()
        try:
            t = ValType(raw)
        except ValueError:
            raise refuse(
                Refusal.MALFORMED_SECTION,
                where=f"{self.what} offset {self.pos - 1}",
                detail=f"0x{raw:02X} is not a type code",
            ) from None
        if t is ValType.VOID and not allow_void:
            raise refuse(
                Refusal.MALFORMED_SECTION,
                where=f"{self.what} offset {self.pos - 1}",
                detail="the void type code is legal only as a return type",
            )
        return t


# -- the string area ------------------------------------------------------
#
# Names are stored once, after the records, as a length-prefixed run:
# one unsigned byte of length, then that many UTF-8 bytes, no
# terminator. A record's ``name_offset`` addresses the length byte and
# is relative to the start of the area.


def _encode_strings(names: list[str]) -> tuple[bytes, list[int]]:
    blob = bytearray()
    offsets = []
    seen: dict[str, int] = {}
    for name in names:
        if name in seen:
            offsets.append(seen[name])
            continue
        raw = name.encode("utf-8")
        if len(raw) > 255:
            raise ValueError(f"name longer than 255 bytes: {name!r}")
        offset = len(blob)
        if offset > 0xFFFF:
            raise ValueError("string area larger than 64 KiB")
        seen[name] = offset
        offsets.append(offset)
        blob.append(len(raw))
        blob += raw
    return bytes(blob), offsets


def _read_string(area: bytes, offset: int, what: str) -> str:
    if offset >= len(area):
        raise refuse(
            Refusal.MALFORMED_SECTION,
            where=what,
            detail=f"name offset {offset} is past the string area",
        )
    length = area[offset]
    start = offset + 1
    if start + length > len(area):
        raise refuse(
            Refusal.MALFORMED_SECTION,
            where=what,
            detail=f"name at {offset} runs past the string area",
        )
    try:
        return area[start : start + length].decode("utf-8")
    except UnicodeDecodeError:
        raise refuse(
            Refusal.MALFORMED_SECTION, where=what, detail="name is not valid UTF-8"
        ) from None


# -- CNST -----------------------------------------------------------------


def _encode_constants(constants: list[Constant]) -> bytes:
    if len(constants) > 255:
        raise ValueError("a container holds at most 255 constants")
    out = bytearray([len(constants)])
    for c in constants:
        out.append(int(c.type))
        if c.type is ValType.I32:
            out += struct.pack("<i", c.value)
        elif c.type is ValType.I64:
            out += struct.pack("<q", c.value)
        elif c.type is ValType.F32:
            out += struct.pack("<f", c.value)
        else:
            raise ValueError(f"{c.type} may not appear in the constant pool")
    return bytes(out)


def _decode_constants(data: bytes) -> list[Constant]:
    cur = _Cursor(data, "CNST")
    count = cur.u8()
    out = []
    for _ in range(count):
        t = cur.type_code()
        if t is ValType.I32:
            (v,) = struct.unpack("<i", cur.bytes(4))
        elif t is ValType.I64:
            (v,) = struct.unpack("<q", cur.bytes(8))
        elif t is ValType.F32:
            (v,) = struct.unpack("<f", cur.bytes(4))
        else:
            raise refuse(
                Refusal.MALFORMED_SECTION,
                where="CNST",
                detail=f"{t} may not appear in the constant pool",
            )
        out.append(Constant(t, v))
    if cur.pos != len(data):
        raise refuse(
            Refusal.MALFORMED_SECTION,
            where="CNST",
            detail=f"{len(data) - cur.pos} trailing bytes after {count} entries",
        )
    return out


# -- ENTR -----------------------------------------------------------------


def _encode_functions(functions: list[Function]) -> bytes:
    if len(functions) > 255:
        raise ValueError("a container holds at most 255 functions")
    area, offsets = _encode_strings([f.name for f in functions])
    out = bytearray([len(functions)])
    for fn, name_offset in zip(functions, offsets, strict=True):
        out += struct.pack("<HI", name_offset, fn.code_offset)
        out.append(ENTRY_INVOCABLE if fn.invocable else 0)
        out.append(int(fn.return_type))
        out.append(fn.max_stack)
        out.append(fn.max_call_depth)
        out.append(fn.recursion_cap)
        out.append(len(fn.local_types))
        out += bytes(int(t) for t in fn.local_types)
    return bytes(out) + area


def _decode_functions(data: bytes) -> list[Function]:
    cur = _Cursor(data, "ENTR")
    count = cur.u8()
    raw = []
    for i in range(count):
        name_offset = cur.u16()
        code_offset = cur.u32()
        flags = cur.u8()
        return_type = cur.type_code(allow_void=True)
        max_stack = cur.u8()
        max_call_depth = cur.u8()
        recursion_cap = cur.u8()
        local_count = cur.u8()
        locals_ = tuple(cur.type_code() for _ in range(local_count))
        if flags & ~ENTRY_INVOCABLE:
            raise refuse(
                Refusal.RESERVED_FIELD_SET,
                where=f"ENTR record {i}",
                detail=f"flags 0x{flags:02X}",
            )
        raw.append(
            (
                name_offset,
                code_offset,
                flags,
                return_type,
                max_stack,
                max_call_depth,
                recursion_cap,
                locals_,
            )
        )
    area = data[cur.pos :]
    return [
        Function(
            name=_read_string(area, name_offset, f"ENTR record {i}"),
            code_offset=code_offset,
            return_type=return_type,
            max_stack=max_stack,
            max_call_depth=max_call_depth,
            local_types=locals_,
            invocable=bool(flags & ENTRY_INVOCABLE),
            recursion_cap=recursion_cap,
        )
        for i, (
            name_offset,
            code_offset,
            flags,
            return_type,
            max_stack,
            max_call_depth,
            recursion_cap,
            locals_,
        ) in enumerate(raw)
    ]


# -- HOST -----------------------------------------------------------------


def _encode_imports(imports: list[Import]) -> bytes:
    if len(imports) > 255:
        raise ValueError("a container holds at most 255 imports")
    area, offsets = _encode_strings([i.name for i in imports])
    out = bytearray([len(imports)])
    for imp, name_offset in zip(imports, offsets, strict=True):
        out += struct.pack(
            "<HBBBHB",
            name_offset,
            imp.kind,
            imp.access,
            int(imp.type),
            imp.dimension,
            len(imp.param_types),
        )
        out += bytes(int(t) for t in imp.param_types)
    return bytes(out) + area


def _decode_imports(data: bytes) -> list[Import]:
    cur = _Cursor(data, "HOST")
    count = cur.u8()
    raw = []
    for i in range(count):
        name_offset = cur.u16()
        kind = cur.u8()
        access = cur.u8()
        type_ = cur.type_code(allow_void=True)
        dimension = cur.u16()
        param_count = cur.u8()
        params = tuple(cur.type_code() for _ in range(param_count))
        if kind not in (ImportKind.ENTITY, ImportKind.FUNCTION):
            raise refuse(
                Refusal.MALFORMED_SECTION,
                where=f"HOST record {i}",
                detail=f"kind 0x{kind:02X} is neither entity nor function",
            )
        if kind == ImportKind.ENTITY:
            if access not in (Access.READ, Access.WRITE, Access.BOTH):
                raise refuse(
                    Refusal.MALFORMED_SECTION,
                    where=f"HOST record {i}",
                    detail=f"access 0x{access:02X} is not read, write or both",
                )
            if type_ is ValType.VOID:
                raise refuse(
                    Refusal.MALFORMED_SECTION,
                    where=f"HOST record {i}",
                    detail="an entity has no void type",
                )
            if param_count:
                raise refuse(
                    Refusal.MALFORMED_SECTION,
                    where=f"HOST record {i}",
                    detail="an entity takes no parameters",
                )
        elif access != Access.NONE:
            raise refuse(
                Refusal.MALFORMED_SECTION,
                where=f"HOST record {i}",
                detail=f"a function's access field must be zero, not 0x{access:02X}",
            )
        raw.append((name_offset, kind, access, type_, dimension, params))
    area = data[cur.pos :]
    imports = [
        Import(
            name=_read_string(area, name_offset, f"HOST record {i}"),
            kind=kind,
            access=access,
            type=type_,
            dimension=dimension,
            param_types=params,
        )
        for i, (name_offset, kind, access, type_, dimension, params) in enumerate(raw)
    ]

    seen: set[str] = set()
    for imp in imports:
        if imp.name in seen:
            raise refuse(Refusal.DUPLICATE_IMPORT, where=imp.name)
        seen.add(imp.name)
    return imports
