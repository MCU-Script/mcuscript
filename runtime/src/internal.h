/*
 * SPDX-FileCopyrightText: 2026 The MCUScript Contributors
 * SPDX-License-Identifier: Apache-2.0
 *
 * Shared between the loader and the interpreter. Not installed.
 */

#ifndef MCUSCRIPT_INTERNAL_H
#define MCUSCRIPT_INTERNAL_H

#include "mcuscript.h"

/* A constant-pool entry, of the type the instruction says it is. In a
 * conforming container the instruction and the pool agree (§2.6). */
int32_t mcuscript_constant_i32(const mcuscript_program *program, uint8_t index);
int64_t mcuscript_constant_i64(const mcuscript_program *program, uint8_t index);
uint32_t mcuscript_constant_f32_bits(const mcuscript_program *program, uint8_t index);

/* The declared type of a host entity, and of a host function's return,
 * by container import index. */
uint8_t mcuscript_import_type(const mcuscript_program *program, uint8_t index);
uint8_t mcuscript_import_parameter_count(const mcuscript_program *program, uint8_t index);
uint8_t mcuscript_import_parameter_type(const mcuscript_program *program, uint8_t index,
					uint8_t parameter);

#endif /* MCUSCRIPT_INTERNAL_H */
