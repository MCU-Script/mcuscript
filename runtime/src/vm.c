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
#include "mcuscript_ops.h"
#include "opcodes.h"

static mcuscript_value slot_to_value(uint8_t type, uint64_t raw, uint8_t state)
{
	mcuscript_value value;
	value.as.i64 = 0;
	switch (type) {
	case MCUSCRIPT_I32:
		value.as.i32 = mcuscript_op_as_i32(raw);
		break;
	case MCUSCRIPT_BOOL:
		value.as.boolean = raw != 0;
		break;
	case MCUSCRIPT_F32:
		value.as.f32 = mcuscript_op_as_f32(raw);
		break;
	default:
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
		return mcuscript_op_from_i32(value.as.i32);
	case MCUSCRIPT_BOOL:
		return value.as.boolean ? 1u : 0u;
	case MCUSCRIPT_F32:
		return mcuscript_op_from_f32(value.as.f32);
	default:
		return (uint64_t)value.as.i64;
	}
}

/*
 * What a call has to remember. `base` is the *caller's* frame base, not
 * the callee's: the callee's is held in a register-resident local and
 * restoring it is what pops the frame.
 */
typedef struct {
	uint32_t return_pc;
	uint32_t base;
	uint8_t function;
} call_frame;

bool mcuscript_invoke(const mcuscript_program *program, int entry, mcuscript_slots *slots,
		      mcuscript_value *result, mcuscript_fault *fault)
{
	if (fault != NULL)
		*fault = MCUSCRIPT_NO_FAULT;
	if (entry < 0 || (uint8_t)entry >= program->function_count)
		return false;

	uint8_t current = (uint8_t)entry;
	const mcuscript_function *fn = &program->functions[current];
	const mcuscript_host *host = program->host;
	const uint8_t *code = program->code;

	call_frame frames[MCUSCRIPT_MAX_CALL_DEPTH];
	uint8_t depth = 0;

	/*
	 * The recursion counters of §5.4, one per call-graph component.
	 * They live here rather than in the program because they belong to
	 * an invocation: a fault that unwinds cannot leave one wrong, and
	 * a `const` program stays const.
	 */
	unsigned counters[MCUSCRIPT_MAX_FUNCTIONS];
	memset(counters, 0, sizeof counters);

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
	uint32_t base = 0;
	uint32_t sp = fn->local_count;
	uint32_t pc = fn->code_offset;

	/* Being invoked is an entry into the component too, so an entry
	 * point inside a cycle occupies the first of its cap. */
	if (program->component_cap[program->component[current]] != 0)
		counters[program->component[current]] = 1;

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
			PUSH(mcuscript_op_from_i32((int8_t)OPERAND), MCUSCRIPT_VALID);
			pc += 2;
			break;
		case OP_CONST_I32_S16:
			PUSH(mcuscript_op_from_i32((int16_t)(uint16_t)(code[pc + 1] |
							  ((uint16_t)code[pc + 2] << 8))),
			     MCUSCRIPT_VALID);
			pc += 3;
			break;
		case OP_CONST_I32:
			PUSH(mcuscript_op_from_i32(mcuscript_constant_i32(program, OPERAND)), MCUSCRIPT_VALID);
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
			uint32_t local = base + OPERAND;
			PUSH(values[local], states[local]);
			pc += 2;
			break;
		}
		case OP_STORE_L: {
			uint32_t local = base + OPERAND;
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
			int32_t b = mcuscript_op_as_i32(values[sp - 1]);
			int32_t a = mcuscript_op_as_i32(values[sp - 2]);
			int32_t out = (opcode == OP_ADD_I32)   ? mcuscript_op_add_i32(a, b)
				      : (opcode == OP_SUB_I32) ? mcuscript_op_sub_i32(a, b)
							       : mcuscript_op_mul_i32(a, b);
			sp--;
			values[sp - 1] = mcuscript_op_from_i32(out);
			states[sp - 1] = mcuscript_op_worse(states[sp - 1], states[sp]);
			pc += 1;
			break;
		}
		case OP_DIV_I32:
		case OP_REM_I32: {
			int32_t b = mcuscript_op_as_i32(values[sp - 1]);
			int32_t a = mcuscript_op_as_i32(values[sp - 2]);
			uint8_t state = mcuscript_op_worse(states[sp - 2], states[sp - 1]);
			int32_t out = (opcode == OP_DIV_I32)
					      ? mcuscript_op_div_i32(a, b, &state)
					      : mcuscript_op_rem_i32(a, b, &state);
			sp--;
			values[sp - 1] = mcuscript_op_from_i32(out);
			states[sp - 1] = state;
			pc += 1;
			break;
		}
		case OP_NEG_I32:
			values[sp - 1] = mcuscript_op_from_i32(mcuscript_op_neg_i32(mcuscript_op_as_i32(values[sp - 1])));
			pc += 1;
			break;

		case OP_EQ_I32:
		case OP_NE_I32:
		case OP_LT_I32:
		case OP_LE_I32:
		case OP_GT_I32:
		case OP_GE_I32: {
			int32_t b = mcuscript_op_as_i32(values[sp - 1]);
			int32_t a = mcuscript_op_as_i32(values[sp - 2]);
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
			states[sp - 1] = mcuscript_op_worse(states[sp - 1], states[sp]);
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

		/* -- i64 ------------------------------------------------ */
		case OP_CONST_I64:
			PUSH(mcuscript_op_from_i64(mcuscript_constant_i64(program, OPERAND)),
			     MCUSCRIPT_VALID);
			pc += 2;
			break;
		case OP_ADD_I64:
		case OP_SUB_I64:
		case OP_MUL_I64: {
			int64_t b = mcuscript_op_as_i64(values[sp - 1]);
			int64_t a = mcuscript_op_as_i64(values[sp - 2]);
			int64_t out = (opcode == OP_ADD_I64)   ? mcuscript_op_add_i64(a, b)
				      : (opcode == OP_SUB_I64) ? mcuscript_op_sub_i64(a, b)
							       : mcuscript_op_mul_i64(a, b);
			sp--;
			values[sp - 1] = mcuscript_op_from_i64(out);
			states[sp - 1] = mcuscript_op_worse(states[sp - 1], states[sp]);
			pc += 1;
			break;
		}
		case OP_DIV_I64:
		case OP_REM_I64: {
			int64_t b = mcuscript_op_as_i64(values[sp - 1]);
			int64_t a = mcuscript_op_as_i64(values[sp - 2]);
			uint8_t state = mcuscript_op_worse(states[sp - 2], states[sp - 1]);
			int64_t out = (opcode == OP_DIV_I64)
					      ? mcuscript_op_div_i64(a, b, &state)
					      : mcuscript_op_rem_i64(a, b, &state);
			sp--;
			values[sp - 1] = mcuscript_op_from_i64(out);
			states[sp - 1] = state;
			pc += 1;
			break;
		}
		case OP_NEG_I64:
			values[sp - 1] = mcuscript_op_from_i64(
				mcuscript_op_neg_i64(mcuscript_op_as_i64(values[sp - 1])));
			pc += 1;
			break;
		case OP_EQ_I64:
		case OP_NE_I64:
		case OP_LT_I64:
		case OP_LE_I64:
		case OP_GT_I64:
		case OP_GE_I64: {
			int64_t b = mcuscript_op_as_i64(values[sp - 1]);
			int64_t a = mcuscript_op_as_i64(values[sp - 2]);
			bool out;
			switch (opcode) {
			case OP_EQ_I64:
				out = a == b;
				break;
			case OP_NE_I64:
				out = a != b;
				break;
			case OP_LT_I64:
				out = a < b;
				break;
			case OP_LE_I64:
				out = a <= b;
				break;
			case OP_GT_I64:
				out = a > b;
				break;
			default:
				out = a >= b;
				break;
			}
			sp--;
			values[sp - 1] = out ? 1u : 0u;
			states[sp - 1] = mcuscript_op_worse(states[sp - 1], states[sp]);
			pc += 1;
			break;
		}
		case OP_EXTEND_I32_I64:
			values[sp - 1] = mcuscript_op_from_i64(
				(int64_t)mcuscript_op_as_i32(values[sp - 1]));
			pc += 1;
			break;
		case OP_WRAP_I64_I32:
			/* Truncates silently rather than producing `invalid`:
			 * it is the explicit "I want the low half" operation
			 * (§3.4). */
			values[sp - 1] = mcuscript_op_from_i32(
				(int32_t)(uint32_t)(uint64_t)values[sp - 1]);
			pc += 1;
			break;

		/* -- f32 ------------------------------------------------ */
		case OP_CONST_F32:
			PUSH((uint64_t)mcuscript_constant_f32_bits(program, OPERAND),
			     MCUSCRIPT_VALID);
			pc += 2;
			break;
		case OP_ADD_F32:
		case OP_SUB_F32:
		case OP_MUL_F32:
		case OP_DIV_F32: {
			float b = mcuscript_op_as_f32(values[sp - 1]);
			float a = mcuscript_op_as_f32(values[sp - 2]);
			float out = (opcode == OP_ADD_F32)   ? mcuscript_op_add_f32(a, b)
				    : (opcode == OP_SUB_F32) ? mcuscript_op_sub_f32(a, b)
				    : (opcode == OP_MUL_F32) ? mcuscript_op_mul_f32(a, b)
							     : mcuscript_op_div_f32(a, b);
			sp--;
			/* Storing the result narrows it back to binary32 here
			 * and in the generated C at the same point, which is
			 * what makes an FPU with wider intermediates harmless
			 * to the agreement of the two backends. */
			values[sp - 1] = mcuscript_op_from_f32(out);
			states[sp - 1] = mcuscript_op_worse(states[sp - 1], states[sp]);
			pc += 1;
			break;
		}
		case OP_NEG_F32:
			values[sp - 1] = mcuscript_op_from_f32(
				mcuscript_op_neg_f32(mcuscript_op_as_f32(values[sp - 1])));
			pc += 1;
			break;
		case OP_EQ_F32:
		case OP_NE_F32:
		case OP_LT_F32:
		case OP_LE_F32:
		case OP_GT_F32:
		case OP_GE_F32: {
			float b = mcuscript_op_as_f32(values[sp - 1]);
			float a = mcuscript_op_as_f32(values[sp - 2]);
			bool out;
			switch (opcode) {
			/* IEEE-754 comparison: every one of these is false
			 * when either operand is NaN, except `ne`. */
			case OP_EQ_F32:
				out = a == b;
				break;
			case OP_NE_F32:
				out = a != b;
				break;
			case OP_LT_F32:
				out = a < b;
				break;
			case OP_LE_F32:
				out = a <= b;
				break;
			case OP_GT_F32:
				out = a > b;
				break;
			default:
				out = a >= b;
				break;
			}
			sp--;
			values[sp - 1] = out ? 1u : 0u;
			states[sp - 1] = mcuscript_op_worse(states[sp - 1], states[sp]);
			pc += 1;
			break;
		}
		case OP_CONVERT_I32_F32:
			values[sp - 1] = mcuscript_op_from_f32(
				mcuscript_op_convert_i32_f32(mcuscript_op_as_i32(values[sp - 1])));
			pc += 1;
			break;
		case OP_TRUNC_F32_I32: {
			uint8_t state = states[sp - 1];
			int32_t out = mcuscript_op_trunc_f32_i32(
				mcuscript_op_as_f32(values[sp - 1]), &state);
			values[sp - 1] = mcuscript_op_from_i32(out);
			states[sp - 1] = state;
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

		case OP_CALL: {
			uint8_t index = OPERAND;
			const mcuscript_function *callee = &program->functions[index];
			uint8_t component = program->component[index];
			uint8_t cap = program->component_cap[component];
			if (cap != 0 && ++counters[component] > (unsigned)cap)
				FAULT(MCUSCRIPT_RECURSION_LIMIT);

			frames[depth].return_pc = pc + 2;
			frames[depth].base = base;
			frames[depth].function = current;
			depth++;

			/*
			 * The arguments are already where the callee's first
			 * locals have to be — on top of the caller's stack, in
			 * order (§5.3). So the frame simply *begins* there and
			 * nothing is copied.
			 */
			base = sp - callee->param_count;
			for (uint8_t i = callee->param_count; i < callee->local_count; i++) {
				values[base + i] = 0;
				states[base + i] = MCUSCRIPT_UNAVAILABLE;
			}
			sp = base + callee->local_count;
			current = index;
			fn = callee;
			pc = callee->code_offset;
			break;
		}

		case OP_RET:
		case OP_RET_V: {
			uint64_t produced = 0;
			uint8_t produced_state = MCUSCRIPT_UNAVAILABLE;
			if (opcode == OP_RET_V) {
				produced = values[sp - 1];
				produced_state = states[sp - 1];
			}
			if (depth == 0) {
				if (opcode == OP_RET_V && result != NULL)
					*result = slot_to_value(fn->return_type, produced,
								produced_state);
				return true;
			}
			uint8_t component = program->component[current];
			if (program->component_cap[component] != 0)
				counters[component]--;

			depth--;
			/* Restoring the stack pointer to the callee's frame base
			 * is what removes the arguments: they were the bottom of
			 * that frame and the top of the caller's stack. */
			sp = base;
			base = frames[depth].base;
			pc = frames[depth].return_pc;
			current = frames[depth].function;
			fn = &program->functions[current];
			if (opcode == OP_RET_V) {
				values[sp] = produced;
				states[sp] = produced_state;
				sp++;
			}
			break;
		}

		default:
			/* Verification proved this cannot happen. */
			return false;
		}
	}

#undef OPERAND
#undef PUSH
#undef FAULT
}
