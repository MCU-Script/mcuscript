/*
 * SPDX-FileCopyrightText: 2026 The MCUScript Contributors
 * SPDX-License-Identifier: Apache-2.0
 *
 * The interpreter (§5).
 *
 * There is no bounds check in this loop, no type check, no instruction
 * budget and no stack-overflow test, and each absence is something the
 * loader paid for: verification proved the types and the depth (§2.6),
 * and the absence of backward jumps proved termination (§5.6). An
 * implementation that needs a check here has a verifier that is not
 * doing its job.
 */

#include <string.h>

#include "internal.h"
#include "mcuscript.h"
#include "opcodes.h"

/* Validity propagates as the maximum of the operands' ordinals (§1.3):
 * a defect outranks a wait. Branchless on purpose — there is nothing
 * here for the two backends to get subtly different. */
static inline uint8_t worse(uint8_t a, uint8_t b)
{
	return a > b ? a : b;
}

static inline int32_t as_i32(uint64_t slot)
{
	return (int32_t)(uint32_t)slot;
}

static inline uint64_t from_i32(int32_t value)
{
	return (uint64_t)(uint32_t)value;
}

/*
 * Signed overflow is undefined in C, so every wrapping operation is
 * computed in the unsigned type of the same width and converted back
 * (§1.5). This is not defensive style; it is the only way the VM and
 * the transpiled C can be made to agree, because the C compiler is
 * entitled to assume the undefined case never happens.
 */
static inline int32_t wrap_add(int32_t a, int32_t b)
{
	return (int32_t)((uint32_t)a + (uint32_t)b);
}

static inline int32_t wrap_sub(int32_t a, int32_t b)
{
	return (int32_t)((uint32_t)a - (uint32_t)b);
}

static inline int32_t wrap_mul(int32_t a, int32_t b)
{
	return (int32_t)((uint32_t)a * (uint32_t)b);
}

static inline int32_t wrap_neg(int32_t a)
{
	return (int32_t)(0u - (uint32_t)a);
}

static mcuscript_value slot_to_value(uint8_t type, uint64_t raw, uint8_t state)
{
	mcuscript_value value;
	value.as.i64 = 0;
	switch (type) {
	case MCUSCRIPT_I32:
		value.as.i32 = as_i32(raw);
		break;
	case MCUSCRIPT_BOOL:
		value.as.boolean = raw != 0;
		break;
	default:
		/* i64 and f32 arrive with their groups; until then the
		 * verifier has made this unreachable. */
		value.as.i64 = (int64_t)raw;
		break;
	}
	value.validity = state;
	return value;
}

static uint64_t value_to_slot(uint8_t type, mcuscript_value value)
{
	switch (type) {
	case MCUSCRIPT_I32:
		return from_i32(value.as.i32);
	case MCUSCRIPT_BOOL:
		return value.as.boolean ? 1u : 0u;
	default:
		return (uint64_t)value.as.i64;
	}
}

bool mcuscript_invoke(const mcuscript_program *program, int entry, mcuscript_slots *slots,
		      mcuscript_value *result, mcuscript_fault *fault)
{
	if (fault != NULL)
		*fault = MCUSCRIPT_NO_FAULT;
	if (entry < 0 || (uint8_t)entry >= program->function_count)
		return false;

	const mcuscript_function *fn = &program->functions[entry];
	const mcuscript_host *host = program->host;
	const uint8_t *code = program->code;

	/*
	 * A local that has not been written reads as `unavailable`, never
	 * as uninitialized memory (§3.3). Nothing carries over from a
	 * previous invocation: a program has no state between them (§5.2),
	 * and clearing here is what makes that true rather than hoped.
	 */
	for (uint8_t i = 0; i < fn->local_count; i++) {
		slots->values[i] = 0;
		slots->states[i] = MCUSCRIPT_UNAVAILABLE;
	}

	uint64_t *values = slots->values;
	uint8_t *states = slots->states;
	uint32_t sp = fn->local_count;
	uint32_t pc = fn->code_offset;

#define PUSH(v, s)                       \
	do {                             \
		values[sp] = (v);        \
		states[sp] = (s);        \
		sp++;                    \
	} while (0)

#define FAULT(kind)                          \
	do {                                 \
		if (fault != NULL)           \
			*fault = (kind);     \
		return false;                \
	} while (0)

	/* The operand byte is read inside the cases that have one: a
	 * one-byte instruction at the very end of CODE has no pc+1. */
#define OPERAND (code[pc + 1])

	for (;;) {
		uint8_t opcode = code[pc];

		switch (opcode) {
		case OP_CONST_I32_S8:
			PUSH(from_i32((int8_t)OPERAND), MCUSCRIPT_VALID);
			pc += 2;
			break;
		case OP_CONST_I32_S16:
			PUSH(from_i32((int16_t)(uint16_t)(code[pc + 1] |
							  ((uint16_t)code[pc + 2] << 8))),
			     MCUSCRIPT_VALID);
			pc += 3;
			break;
		case OP_CONST_I32:
			PUSH(from_i32(mcuscript_constant_i32(program, OPERAND)), MCUSCRIPT_VALID);
			pc += 2;
			break;
		case OP_CONST_TRUE:
			PUSH(1u, MCUSCRIPT_VALID);
			pc += 1;
			break;
		case OP_CONST_FALSE:
			PUSH(0u, MCUSCRIPT_VALID);
			pc += 1;
			break;

		case OP_LOAD_L: {
			uint8_t local = OPERAND;
			PUSH(values[local], states[local]);
			pc += 2;
			break;
		}
		case OP_STORE_L: {
			uint8_t local = OPERAND;
			sp--;
			values[local] = values[sp];
			states[local] = states[sp];
			pc += 2;
			break;
		}

		case OP_LOAD_H: {
			uint8_t index = OPERAND;
			uint8_t type = mcuscript_import_type(program, index);
			mcuscript_value value = host->read(host->context,
							   program->import_map[index]);
			PUSH(value_to_slot(type, value), value.validity);
			pc += 2;
			break;
		}
		case OP_STORE_H: {
			uint8_t index = OPERAND;
			uint8_t type = mcuscript_import_type(program, index);
			sp--;
			host->write(host->context, program->import_map[index],
				    slot_to_value(type, values[sp], states[sp]));
			pc += 2;
			break;
		}
		case OP_CALL_H: {
			uint8_t index = OPERAND;
			uint8_t count = mcuscript_import_parameter_count(program, index);
			mcuscript_value arguments[MCUSCRIPT_MAX_PARAMETERS];
			for (uint8_t p = 0; p < count; p++) {
				uint8_t type =
					mcuscript_import_parameter_type(program, index, p);
				uint32_t at = sp - count + p;
				arguments[p] = slot_to_value(type, values[at], states[at]);
			}
			sp -= count;
			mcuscript_value produced = mcuscript_absent(MCUSCRIPT_UNAVAILABLE);
			if (!host->invoke(host->context, program->import_map[index], arguments,
					  &produced))
				FAULT(MCUSCRIPT_HOST_FAULT);
			uint8_t type = mcuscript_import_type(program, index);
			if (type != MCUSCRIPT_VOID)
				PUSH(value_to_slot(type, produced), produced.validity);
			pc += 2;
			break;
		}

		case OP_DROP:
			sp--;
			pc += 1;
			break;
		case OP_DUP:
			values[sp] = values[sp - 1];
			states[sp] = states[sp - 1];
			sp++;
			pc += 1;
			break;

		case OP_ADD_I32:
		case OP_SUB_I32:
		case OP_MUL_I32: {
			int32_t b = as_i32(values[sp - 1]);
			int32_t a = as_i32(values[sp - 2]);
			int32_t out = (opcode == OP_ADD_I32)   ? wrap_add(a, b)
				      : (opcode == OP_SUB_I32) ? wrap_sub(a, b)
							       : wrap_mul(a, b);
			sp--;
			values[sp - 1] = from_i32(out);
			states[sp - 1] = worse(states[sp - 1], states[sp]);
			pc += 1;
			break;
		}
		case OP_DIV_I32:
		case OP_REM_I32: {
			int32_t b = as_i32(values[sp - 1]);
			int32_t a = as_i32(values[sp - 2]);
			uint8_t state = worse(states[sp - 2], states[sp - 1]);
			int32_t out;
			if (b == 0) {
				/* A value the script can handle beats a dead
				 * script: division by zero is overwhelmingly a
				 * sensor that happened to read zero (§1.5). */
				out = 0;
				state = MCUSCRIPT_INVALID;
			} else if (a == INT32_MIN && b == -1) {
				/* The quotient is not representable, so it is
				 * `invalid`; the remainder is defined and is
				 * zero (§1.5). */
				out = 0;
				if (opcode == OP_DIV_I32)
					state = MCUSCRIPT_INVALID;
			} else {
				out = (opcode == OP_DIV_I32) ? a / b : a % b;
			}
			sp--;
			values[sp - 1] = from_i32(out);
			states[sp - 1] = state;
			pc += 1;
			break;
		}
		case OP_NEG_I32:
			values[sp - 1] = from_i32(wrap_neg(as_i32(values[sp - 1])));
			pc += 1;
			break;

		case OP_EQ_I32:
		case OP_NE_I32:
		case OP_LT_I32:
		case OP_LE_I32:
		case OP_GT_I32:
		case OP_GE_I32: {
			int32_t b = as_i32(values[sp - 1]);
			int32_t a = as_i32(values[sp - 2]);
			bool out;
			switch (opcode) {
			case OP_EQ_I32:
				out = a == b;
				break;
			case OP_NE_I32:
				out = a != b;
				break;
			case OP_LT_I32:
				out = a < b;
				break;
			case OP_LE_I32:
				out = a <= b;
				break;
			case OP_GT_I32:
				out = a > b;
				break;
			default:
				out = a >= b;
				break;
			}
			sp--;
			values[sp - 1] = out ? 1u : 0u;
			states[sp - 1] = worse(states[sp - 1], states[sp]);
			pc += 1;
			break;
		}
		case OP_NOT:
			values[sp - 1] = values[sp - 1] ? 0u : 1u;
			pc += 1;
			break;

		case OP_ELSE:
			/* The fallback carries its own state, so a fallback
			 * that is itself absent does not become valid. */
			sp--;
			if (states[sp - 1] != MCUSCRIPT_VALID) {
				values[sp - 1] = values[sp];
				states[sp - 1] = states[sp];
			}
			pc += 1;
			break;
		case OP_IS_VALID:
		case OP_IS_UNAVAILABLE:
		case OP_IS_INVALID: {
			uint8_t wanted = (uint8_t)(opcode - OP_IS_VALID);
			values[sp - 1] = (states[sp - 1] == wanted) ? 1u : 0u;
			states[sp - 1] = MCUSCRIPT_VALID;
			pc += 1;
			break;
		}

		case OP_JMP:
			pc = (uint32_t)((int32_t)pc + 3 +
					(int16_t)(uint16_t)(code[pc + 1] |
							    ((uint16_t)code[pc + 2] << 8)));
			break;
		case OP_JMP_IF_FALSE:
		case OP_JMP_IF_TRUE: {
			sp--;
			/* An absent reading must not become a wrong action:
			 * the branch is a fault, not a default (§1.3.1). */
			if (states[sp] != MCUSCRIPT_VALID)
				FAULT(MCUSCRIPT_ABSENT_CONDITION);
			bool taken = (opcode == OP_JMP_IF_FALSE) ? values[sp] == 0
								 : values[sp] != 0;
			int16_t delta = (int16_t)(uint16_t)(code[pc + 1] |
							    ((uint16_t)code[pc + 2] << 8));
			pc = taken ? (uint32_t)((int32_t)pc + 3 + delta) : pc + 3;
			break;
		}

		case OP_RET:
			return true;
		case OP_RET_V:
			if (result != NULL)
				*result = slot_to_value(fn->return_type, values[sp - 1],
							states[sp - 1]);
			return true;

		default:
			/* Verification proved this cannot happen. */
			return false;
		}
	}

#undef OPERAND
#undef PUSH
#undef FAULT
}
