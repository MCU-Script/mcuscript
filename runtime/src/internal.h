/*
 * SPDX-FileCopyrightText: 2026 The MCUScript Contributors
 * SPDX-License-Identifier: Apache-2.0
 *
 * Shared between the loader and the interpreter. Not installed.
 */

#ifndef MCUSCRIPT_INTERNAL_H
#define MCUSCRIPT_INTERNAL_H

#include "mcuscript.h"

/* Instruction length, from the opcode alone (§3.1). Zero means the
 * opcode is not assigned in a group this build implements. */
unsigned mcuscript_instruction_size(uint8_t opcode);

/* A constant-pool entry, already known by the verifier to be an i32. */
int32_t mcuscript_constant_i32(const mcuscript_program *program, uint8_t index);

/* The declared type of a host entity, and of a host function's return,
 * by container import index. */
uint8_t mcuscript_import_type(const mcuscript_program *program, uint8_t index);
uint8_t mcuscript_import_parameter_count(const mcuscript_program *program, uint8_t index);
uint8_t mcuscript_import_parameter_type(const mcuscript_program *program, uint8_t index,
					uint8_t parameter);

#endif /* MCUSCRIPT_INTERNAL_H */
