/*
 * SPDX-FileCopyrightText: 2026 The MCUScript Contributors
 * SPDX-License-Identifier: Apache-2.0
 *
 * A host described by a text file, and the output protocol both backends
 * answer in.
 *
 * The point of putting this in one place is the differential test: the
 * VM runner and the generated C are given the *same* world and print
 * through the *same* code, so a difference in their output is a
 * difference in the program, not in the scaffolding around it.
 *
 * Host file lines:
 *     entity read i32 temp dim 1 = 250
 *     entity write i32 fan.speed dim 2
 *     entity rw i32 memory
 *     function i32 clamp i32 i32 = 7
 *     function void log i32 = fault
 *
 * A value is a number, `true`, `false`, `unavailable` or `invalid`;
 * `fault` makes a host function signal failure.
 */

#ifndef MCUSCRIPT_HOSTFILE_H
#define MCUSCRIPT_HOSTFILE_H

#include "mcuscript.h"

/* Read the description. Returns false and complains on stderr. */
bool hostfile_load(const char *path);

/* The registry, for the VM's loader. */
const mcuscript_host *hostfile_host(void);

/* The same world addressed by name, for generated C — which has no
 * import table, because its linking was the C linker's (§ cbackend). */
mcuscript_value hostfile_read_by_name(const char *name);
void hostfile_write_by_name(const char *name, mcuscript_value value);
bool hostfile_call_by_name(const char *name, const mcuscript_value *arguments,
			   mcuscript_value *result);

/* The output protocol. */
void hostfile_print_result(uint8_t type, mcuscript_value value);
void hostfile_print_fault(mcuscript_fault fault);
void hostfile_print_done(void);

#endif /* MCUSCRIPT_HOSTFILE_H */
