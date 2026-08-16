# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0
"""Load-time refusals and run-time faults, by name.

Every way a container can be refused has a name in specification §4.6,
and the point of naming them is that a loader can say *which* — a
diagnostic for people who did not write the compiler is a stated goal
of this project. So the names live in one enum, a test checks that enum
against the specification's own tables, and nothing raises a refusal
that the specification has not named.

A refusal happens before execution; a fault happens during it, and
there are exactly three (§5.5).
"""

from __future__ import annotations

import enum


class Refusal(enum.Enum):
    """A load-time refusal. The value is the name the specification uses."""

    # -- container (§4.6) --------------------------------------------
    BAD_MAGIC = "bad_magic"
    UNSUPPORTED_FORMAT_VERSION = "unsupported_format_version"
    LENGTH_MISMATCH = "length_mismatch"
    BAD_CHECKSUM = "bad_checksum"
    MALFORMED_SECTION = "malformed_section"
    UNKNOWN_CRITICAL_SECTION = "unknown_critical_section"
    MISSING_SECTION = "missing_section"
    DUPLICATE_SECTION = "duplicate_section"
    RESERVED_FIELD_SET = "reserved_field_set"
    ENTRY_TAKES_PARAMETERS = "entry_takes_parameters"

    # -- compatibility ------------------------------------------------
    PROFILE_MISMATCH = "profile_mismatch"
    UNSUPPORTED_GROUP = "unsupported_group"

    # -- verification ---------------------------------------------------
    UNDEFINED_OPCODE = "undefined_opcode"
    TRUNCATED_INSTRUCTION = "truncated_instruction"
    BAD_BRANCH_TARGET = "bad_branch_target"
    BACKWARD_BRANCH = "backward_branch"
    UNREACHABLE_CODE = "unreachable_code"
    TYPE_MISMATCH = "type_mismatch"
    STACK_UNDERFLOW = "stack_underflow"
    INCONSISTENT_JOIN = "inconsistent_join"
    UNBALANCED_RETURN = "unbalanced_return"
    STACK_DEPTH_MISMATCH = "stack_depth_mismatch"
    CALL_DEPTH_MISMATCH = "call_depth_mismatch"
    UNCAPPED_RECURSION = "uncapped_recursion"
    RECURSION_CAP_MISMATCH = "recursion_cap_mismatch"
    INDEX_OUT_OF_RANGE = "index_out_of_range"

    # -- linking ---------------------------------------------------------
    UNKNOWN_IMPORT = "unknown_import"
    KIND_MISMATCH = "kind_mismatch"
    IMPORT_TYPE_MISMATCH = "import_type_mismatch"
    DIMENSION_MISMATCH = "dimension_mismatch"
    ACCESS_DENIED = "access_denied"
    SIGNATURE_MISMATCH = "signature_mismatch"
    DUPLICATE_IMPORT = "duplicate_import"
    IMPORT_LIMIT = "import_limit"

    def __str__(self) -> str:
        return self.value


class Fault(enum.Enum):
    """A run-time fault (§5.5). There are three, and no others."""

    ABSENT_CONDITION = "absent_condition"
    RECURSION_LIMIT = "recursion_limit"
    HOST_FAULT = "host_fault"

    def __str__(self) -> str:
        return self.value


class Refused(Exception):
    """A container was refused. Carries the name and where it happened.

    ``where`` is free-form but never empty in practice: an index, an
    offset, an import name. A refusal that cannot say which of two
    hundred instructions it means is only half a diagnostic.
    """

    def __init__(self, refusal: Refusal, where: str = "", detail: str = "") -> None:
        self.refusal = refusal
        self.where = where
        self.detail = detail
        parts = [refusal.value]
        if where:
            parts.append(f"at {where}")
        if detail:
            parts.append(f"— {detail}")
        super().__init__(" ".join(parts))


def refuse(refusal: Refusal, where: str = "", detail: str = "") -> Refused:
    """Build a :class:`Refused`; written as ``raise refuse(...)``."""
    return Refused(refusal, where, detail)
