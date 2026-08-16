/*
 * SPDX-FileCopyrightText: 2026 The MCUScript Contributors
 * SPDX-License-Identifier: Apache-2.0
 *
 * The names of the refusals and the faults, in their own translation
 * unit so a build that has no loader can still print one. Generated C
 * needs no runtime at all; a program that reports a fault to a human
 * needs these strings and nothing else.
 */

#include "mcuscript.h"

static const char *const REFUSAL_NAMES[] = {
	"ok",
	"bad_magic",
	"unsupported_format_version",
	"length_mismatch",
	"bad_checksum",
	"malformed_section",
	"unknown_critical_section",
	"missing_section",
	"duplicate_section",
	"reserved_field_set",
	"entry_takes_parameters",
	"profile_mismatch",
	"unsupported_group",
	"undefined_opcode",
	"truncated_instruction",
	"bad_branch_target",
	"backward_branch",
	"unreachable_code",
	"type_mismatch",
	"stack_underflow",
	"inconsistent_join",
	"unbalanced_return",
	"stack_depth_mismatch",
	"call_depth_mismatch",
	"uncapped_recursion",
	"recursion_cap_mismatch",
	"index_out_of_range",
	"unknown_import",
	"kind_mismatch",
	"import_type_mismatch",
	"dimension_mismatch",
	"access_denied",
	"signature_mismatch",
	"duplicate_import",
	"import_limit",
	"build_limit",
};

const char *mcuscript_refusal_name(mcuscript_refusal refusal)
{
	if ((unsigned)refusal >= sizeof(REFUSAL_NAMES) / sizeof(REFUSAL_NAMES[0]))
		return "?";
	return REFUSAL_NAMES[refusal];
}

const char *mcuscript_fault_name(mcuscript_fault fault)
{
	switch (fault) {
	case MCUSCRIPT_NO_FAULT:
		return "none";
	case MCUSCRIPT_ABSENT_CONDITION:
		return "absent_condition";
	case MCUSCRIPT_RECURSION_LIMIT:
		return "recursion_limit";
	case MCUSCRIPT_HOST_FAULT:
		return "host_fault";
	}
	return "?";
}
