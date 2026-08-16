# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0
"""The container format: round-trips, and every refusal a reader owes."""

from __future__ import annotations

import struct
import zlib

import pytest

from mcuscript.asm import assemble
from mcuscript.container import (
    HEADER_SIZE,
    Access,
    Constant,
    Container,
    Function,
    Import,
    ImportKind,
    Section,
)
from mcuscript.errors import Refusal, Refused
from mcuscript.opcodes import Group, ValType

SOURCE = """
.profile 7 1.2
.entity read i32 temp dim 3
.entity write i32 fan.speed dim 4
.const big i32 100000

.entry on_temp
  load.h temp
  const.i32 big
  gt.i32
  jmp_if_false low
  const.i32.s8 3
  store.h fan.speed
  ret
low:
  const.i32.s8 0
  store.h fan.speed
  ret
"""


@pytest.fixture
def container() -> Container:
    return assemble(SOURCE)


def _corrupt(blob: bytes, offset: int, value: bytes) -> bytes:
    """Replace bytes and repair the checksum, so the test exercises the
    field it means to and not the CRC."""
    patched = blob[:offset] + value + blob[offset + len(value) :]
    zeroed = patched[:24] + b"\0\0\0\0" + patched[28:]
    crc = zlib.crc32(zeroed) & 0xFFFFFFFF
    return patched[:24] + struct.pack("<I", crc) + patched[28:]


def test_round_trip(container):
    blob = container.encode()
    back = Container.decode(blob)
    assert back.code == container.code
    assert back.constants == container.constants
    assert back.functions == container.functions
    assert back.imports == container.imports
    assert (back.profile_id, back.profile_major, back.profile_minor) == (7, 1, 2)
    assert back.required_groups == Group.CORE.mask
    assert back.encode() == blob


def test_header_is_the_documented_shape(container):
    blob = container.encode()
    assert blob[:4] == b"MCUS"
    assert struct.unpack_from("<H", blob, 4)[0] == 1
    assert struct.unpack_from("<I", blob, 8)[0] == len(blob)
    assert len(blob) % 4 == 0  # sections stay 4-byte aligned


def test_sections_are_padded_to_four_bytes():
    container = assemble(".profile 0 0.0\n.entry go\n  ret\n")
    blob = container.encode()
    offset = HEADER_SIZE
    while offset < len(blob):
        length = struct.unpack_from("<I", blob, offset + 4)[0]
        offset += 8 + length + (-length % 4)
    assert offset == len(blob), "sections must tile the container exactly"


def test_ancillary_sections_survive_a_round_trip(container):
    container.ancillary.append(Section("note", b"built by a test"))
    back = Container.decode(container.encode())
    assert back.ancillary == [Section("note", b"built by a test")]


def test_an_unknown_ancillary_section_is_skipped(container):
    container.ancillary.append(Section("xyzq", b"\x01\x02"))
    back = Container.decode(container.encode())
    assert [s.type for s in back.ancillary] == ["xyzq"]


# -- refusals -------------------------------------------------------------


def _expect(refusal: Refusal, blob: bytes) -> Refused:
    with pytest.raises(Refused) as caught:
        Container.decode(blob)
    assert caught.value.refusal is refusal, caught.value
    return caught.value


def test_bad_magic(container):
    _expect(Refusal.BAD_MAGIC, _corrupt(container.encode(), 0, b"XCUS"))


def test_a_newer_format_version_is_refused_rather_than_guessed(container):
    error = _expect(
        Refusal.UNSUPPORTED_FORMAT_VERSION,
        _corrupt(container.encode(), 4, struct.pack("<H", 2)),
    )
    assert "2" in str(error)


def test_an_older_format_version_is_not_refused_here(container):
    # Version 0 has never existed, so the decoder gets further and trips
    # over something else; what matters is that it is not refused for
    # being *older* (§2.1).
    blob = _corrupt(container.encode(), 4, struct.pack("<H", 0))
    assert Container.decode(blob).format_version == 0


def test_truncation_is_caught_by_total_length(container):
    blob = container.encode()
    with pytest.raises(Refused) as caught:
        Container.decode(blob[:-4])
    assert caught.value.refusal is Refusal.LENGTH_MISMATCH


def test_a_flipped_bit_is_caught_by_the_checksum(container):
    blob = bytearray(container.encode())
    blob[HEADER_SIZE + 9] ^= 0x01
    with pytest.raises(Refused) as caught:
        Container.decode(bytes(blob))
    assert caught.value.refusal is Refusal.BAD_CHECKSUM


def test_reserved_header_flags_must_be_zero(container):
    _expect(
        Refusal.RESERVED_FIELD_SET,
        _corrupt(container.encode(), 6, struct.pack("<H", 0x0001)),
    )


def test_an_unknown_critical_section_is_refused(container):
    blob = container.encode()
    error = _expect(
        Refusal.UNKNOWN_CRITICAL_SECTION, _corrupt(blob, HEADER_SIZE, b"XTRA")
    )
    assert "XTRA" in str(error)


def test_a_missing_critical_section_is_refused(container):
    blob = bytearray(container.encode())
    # Turn CODE into an ancillary section: now nothing supplies the code.
    blob[HEADER_SIZE] = ord("c")
    _expect(Refusal.MISSING_SECTION, _corrupt(bytes(blob), 0, b"MCUS"))


def test_a_duplicated_critical_section_is_refused(container):
    blob = container.encode()
    length = struct.unpack_from("<I", blob, HEADER_SIZE + 4)[0]
    section = blob[HEADER_SIZE : HEADER_SIZE + 8 + length + (-length % 4)]
    doubled = blob[:HEADER_SIZE] + section + blob[HEADER_SIZE:]
    doubled = doubled[:8] + struct.pack("<I", len(doubled)) + doubled[12:]
    _expect(Refusal.DUPLICATE_SECTION, _corrupt(doubled, 0, b"MCUS"))


def test_a_section_running_past_the_end_is_refused(container):
    _expect(
        Refusal.MALFORMED_SECTION,
        _corrupt(container.encode(), HEADER_SIZE + 4, struct.pack("<I", 0xFFFF)),
    )


def test_a_duplicate_import_is_refused():
    container = Container(
        imports=[
            Import("temp", ImportKind.ENTITY, Access.READ, ValType.I32),
            Import("temp", ImportKind.ENTITY, Access.WRITE, ValType.I32),
        ]
    )
    _expect(Refusal.DUPLICATE_IMPORT, container.encode(required_groups=0))


# -- compatibility --------------------------------------------------------


def test_a_profile_mismatch_is_a_refusal_not_a_warning(container):
    container.check_profile(7, 1, 2)
    container.check_profile(7, 1, 9)  # a differing minor is allowed here
    with pytest.raises(Refused) as caught:
        container.check_profile(7, 2, 0)
    assert caught.value.refusal is Refusal.PROFILE_MISMATCH
    with pytest.raises(Refused):
        container.check_profile(8, 1, 2)


def test_a_missing_group_is_refused_by_name():
    container = assemble(
        ".profile 0 0.0\n.const n i64 5\n.entry go\n  const.i64 n\n  drop\n  ret\n"
    )
    container.check_groups(frozenset({Group.CORE, Group.I64}))
    with pytest.raises(Refused) as caught:
        container.check_groups(frozenset({Group.CORE}))
    assert caught.value.refusal is Refusal.UNSUPPORTED_GROUP
    assert "i64" in str(caught.value)


# -- table encodings ------------------------------------------------------


def test_bool_may_not_enter_the_constant_pool():
    container = Container(constants=[Constant(ValType.BOOL, 1)])
    with pytest.raises(ValueError):
        container.encode(required_groups=0)


def test_names_are_stored_once():
    """Two functions with the same-looking name cannot happen, but two
    imports and a function sharing a spelling can, and the string area
    should not pay for it twice."""
    container = Container(
        functions=[
            Function("same", 0, max_stack=0),
            Function("same", 1, max_stack=0),
        ]
    )
    blob = container.encode(required_groups=0)
    assert blob.count(b"same") == 1


def test_a_function_record_carries_its_invocability():
    container = Container(
        code=b"\x23\x23",
        functions=[
            Function("shown", 0, invocable=True),
            Function("hidden", 1, invocable=False),
        ],
    )
    back = Container.decode(container.encode())
    assert [f.invocable for f in back.functions] == [True, False]
