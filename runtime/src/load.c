/*
 * SPDX-FileCopyrightText: 2026 The MCUScript Contributors
 * SPDX-License-Identifier: Apache-2.0
 *
 * Loading: parse the container (§2), verify the code (§2.6), resolve
 * the imports (§4.5). Everything here treats its input as hostile,
 * because after the compiler released it, it is.
 */

#include <string.h>

#include "internal.h"
#include "mcuscript.h"
#include "opcodes.h"

#define HEADER_SIZE 28
#define FORMAT_VERSION 1

/* ------------------------------------------------------------------
 * Small readers. Nothing in a container is trusted to be in range, so
 * every read goes through a bound.
 */

static uint16_t read_u16(const uint8_t *p)
{
	return (uint16_t)(p[0] | ((uint16_t)p[1] << 8));
}

static uint32_t read_u32(const uint8_t *p)
{
	return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) |
	       ((uint32_t)p[3] << 24);
}

static int32_t read_i32(const uint8_t *p)
{
	return (int32_t)read_u32(p);
}

static int16_t read_i16(const uint8_t *p)
{
	return (int16_t)read_u16(p);
}

/*
 * CRC-32/ISO-HDLC, bitwise. A table would be four to eight times faster
 * and cost 256 to 1024 bytes of flash on a device that runs this once
 * per load; the loop is the right trade here, and an embedder that
 * disagrees can supply its own.
 */
static uint32_t crc32(const uint8_t *data, size_t length, size_t skip_from,
		      size_t skip_to)
{
	uint32_t crc = 0xFFFFFFFFu;
	for (size_t i = 0; i < length; i++) {
		uint8_t byte = (i >= skip_from && i < skip_to) ? 0u : data[i];
		crc ^= byte;
		for (int bit = 0; bit < 8; bit++)
			crc = (crc >> 1) ^ (0xEDB88320u & (uint32_t)(-(int32_t)(crc & 1u)));
	}
	return ~crc;
}

/* ------------------------------------------------------------------
 * Diagnostics
 */

static bool fail(mcuscript_diagnostic *diagnostic, mcuscript_refusal refusal,
		 uint32_t where)
{
	if (diagnostic != NULL) {
		diagnostic->refusal = refusal;
		diagnostic->where = where;
		diagnostic->name.bytes = NULL;
		diagnostic->name.length = 0;
	}
	return false;
}

static bool fail_named(mcuscript_diagnostic *diagnostic, mcuscript_refusal refusal,
		       uint32_t where, mcuscript_str name)
{
	fail(diagnostic, refusal, where);
	if (diagnostic != NULL)
		diagnostic->name = name;
	return false;
}

/* ------------------------------------------------------------------
 * Instruction sizes
 */

unsigned mcuscript_instruction_size(uint8_t opcode)
{
	switch (opcode) {
	case OP_CONST_TRUE:
	case OP_CONST_FALSE:
	case OP_DROP:
	case OP_DUP:
	case OP_ADD_I32:
	case OP_SUB_I32:
	case OP_MUL_I32:
	case OP_DIV_I32:
	case OP_REM_I32:
	case OP_NEG_I32:
	case OP_EQ_I32:
	case OP_NE_I32:
	case OP_LT_I32:
	case OP_LE_I32:
	case OP_GT_I32:
	case OP_GE_I32:
	case OP_NOT:
	case OP_RET:
	case OP_RET_V:
	case OP_ELSE:
	case OP_IS_VALID:
	case OP_IS_UNAVAILABLE:
	case OP_IS_INVALID:
		return 1;
	case OP_CONST_I32_S8:
	case OP_CONST_I32:
	case OP_LOAD_L:
	case OP_STORE_L:
	case OP_LOAD_H:
	case OP_STORE_H:
	case OP_CALL_H:
		return 2;
	case OP_CONST_I32_S16:
	case OP_JMP:
	case OP_JMP_IF_FALSE:
	case OP_JMP_IF_TRUE:
		return 3;
	default:
		return 0;
	}
}

/* ------------------------------------------------------------------
 * The string area (§4.3)
 */

static bool read_name(const uint8_t *area, uint32_t area_length, uint16_t offset,
		      mcuscript_str *out)
{
	if (offset >= area_length)
		return false;
	uint8_t length = area[offset];
	if ((uint32_t)offset + 1u + length > area_length)
		return false;
	out->bytes = (const char *)(area + offset + 1);
	out->length = length;
	return true;
}

static bool name_equals(mcuscript_str name, const char *zero_terminated)
{
	size_t length = strlen(zero_terminated);
	if (length != name.length)
		return false;
	return memcmp(name.bytes, zero_terminated, length) == 0;
}

/* ------------------------------------------------------------------
 * Import records, read in place
 */

typedef struct {
	mcuscript_str name;
	uint8_t kind;
	uint8_t access;
	uint8_t type;
	uint16_t dimension;
	uint8_t parameter_count;
	const uint8_t *parameter_types;
} import_view;

static void import_at(const mcuscript_program *program, uint8_t index, import_view *out)
{
	const uint8_t *record = program->imports + program->import_offsets[index];
	out->kind = record[2];
	out->access = record[3];
	out->type = record[4];
	out->dimension = read_u16(record + 5);
	out->parameter_count = record[7];
	out->parameter_types = record + 8;
	out->name.bytes = NULL;
	out->name.length = 0;
}

/* ------------------------------------------------------------------
 * Section walk
 */

typedef struct {
	const uint8_t *data;
	uint32_t length;
	bool present;
} section;

static bool is_type_code(uint8_t code, bool allow_void)
{
	if (code == MCUSCRIPT_VOID)
		return allow_void;
	return code >= MCUSCRIPT_I32 && code <= MCUSCRIPT_BOOL;
}

static bool walk_sections(const uint8_t *bytes, size_t length, section *code,
			  section *constants, section *entries, section *imports,
			  mcuscript_diagnostic *diagnostic)
{
	size_t offset = HEADER_SIZE;
	while (offset < length) {
		if (offset + 8 > length)
			return fail(diagnostic, MCUSCRIPT_MALFORMED_SECTION, (uint32_t)offset);
		const uint8_t *type = bytes + offset;
		uint32_t size = read_u32(bytes + offset + 4);
		uint32_t padded = size + ((4u - (size & 3u)) & 3u);
		if (offset + 8u + padded > length || offset + 8u + padded < offset)
			return fail(diagnostic, MCUSCRIPT_MALFORMED_SECTION, (uint32_t)offset);
		for (int i = 0; i < 4; i++)
			if (type[i] < 0x20 || type[i] > 0x7E)
				return fail(diagnostic, MCUSCRIPT_MALFORMED_SECTION,
					    (uint32_t)offset);

		section *target = NULL;
		if (memcmp(type, "CODE", 4) == 0)
			target = code;
		else if (memcmp(type, "CNST", 4) == 0)
			target = constants;
		else if (memcmp(type, "ENTR", 4) == 0)
			target = entries;
		else if (memcmp(type, "HOST", 4) == 0)
			target = imports;
		else if (type[0] >= 'A' && type[0] <= 'Z')
			return fail(diagnostic, MCUSCRIPT_UNKNOWN_CRITICAL_SECTION,
				    (uint32_t)offset);

		if (target != NULL) {
			if (target->present)
				return fail(diagnostic, MCUSCRIPT_DUPLICATE_SECTION,
					    (uint32_t)offset);
			target->present = true;
			target->data = bytes + offset + 8;
			target->length = size;
		}
		offset += 8u + padded;
	}
	if (!code->present || !constants->present || !entries->present || !imports->present)
		return fail(diagnostic, MCUSCRIPT_MISSING_SECTION, 0);
	return true;
}

/* ------------------------------------------------------------------
 * Tables
 */

static bool load_constants(mcuscript_program *program, section pool,
			   mcuscript_diagnostic *diagnostic)
{
	if (pool.length < 1)
		return fail(diagnostic, MCUSCRIPT_MALFORMED_SECTION, 0);
	uint8_t count = pool.data[0];
	if (count > MCUSCRIPT_MAX_CONSTANTS)
		return fail(diagnostic, MCUSCRIPT_BUILD_LIMIT, count);
	program->constants = pool.data;
	program->constant_count = count;

	uint32_t offset = 1;
	for (uint8_t i = 0; i < count; i++) {
		if (offset >= pool.length)
			return fail(diagnostic, MCUSCRIPT_MALFORMED_SECTION, offset);
		uint8_t type = pool.data[offset];
		uint32_t width;
		switch (type) {
		case MCUSCRIPT_I32:
		case MCUSCRIPT_F32:
			width = 4;
			break;
		case MCUSCRIPT_I64:
			width = 8;
			break;
		default:
			return fail(diagnostic, MCUSCRIPT_MALFORMED_SECTION, offset);
		}
		if (offset + 1u + width > pool.length)
			return fail(diagnostic, MCUSCRIPT_MALFORMED_SECTION, offset);
		program->constant_offsets[i] = (uint16_t)offset;
		offset += 1u + width;
	}
	if (offset != pool.length)
		return fail(diagnostic, MCUSCRIPT_MALFORMED_SECTION, offset);
	return true;
}

static bool load_imports(mcuscript_program *program, section table,
			 mcuscript_diagnostic *diagnostic)
{
	if (table.length < 1)
		return fail(diagnostic, MCUSCRIPT_MALFORMED_SECTION, 0);
	uint8_t count = table.data[0];
	if (count > MCUSCRIPT_MAX_IMPORTS)
		return fail(diagnostic, MCUSCRIPT_BUILD_LIMIT, count);
	program->imports = table.data;
	program->import_count = count;

	uint32_t offset = 1;
	for (uint8_t i = 0; i < count; i++) {
		if (offset + 8u > table.length)
			return fail(diagnostic, MCUSCRIPT_MALFORMED_SECTION, offset);
		const uint8_t *record = table.data + offset;
		uint8_t kind = record[2];
		uint8_t access = record[3];
		uint8_t type = record[4];
		uint8_t parameters = record[7];
		if (offset + 8u + parameters > table.length)
			return fail(diagnostic, MCUSCRIPT_MALFORMED_SECTION, offset);
		if (kind != MCUSCRIPT_KIND_ENTITY && kind != MCUSCRIPT_KIND_FUNCTION)
			return fail(diagnostic, MCUSCRIPT_MALFORMED_SECTION, offset);
		if (!is_type_code(type, kind == MCUSCRIPT_KIND_FUNCTION))
			return fail(diagnostic, MCUSCRIPT_MALFORMED_SECTION, offset);
		if (kind == MCUSCRIPT_KIND_ENTITY) {
			if (access != MCUSCRIPT_ACCESS_READ && access != MCUSCRIPT_ACCESS_WRITE &&
			    access != MCUSCRIPT_ACCESS_BOTH)
				return fail(diagnostic, MCUSCRIPT_MALFORMED_SECTION, offset);
			if (parameters != 0)
				return fail(diagnostic, MCUSCRIPT_MALFORMED_SECTION, offset);
		} else if (access != MCUSCRIPT_ACCESS_NONE) {
			return fail(diagnostic, MCUSCRIPT_MALFORMED_SECTION, offset);
		} else if (parameters > MCUSCRIPT_MAX_PARAMETERS) {
			return fail(diagnostic, MCUSCRIPT_BUILD_LIMIT, parameters);
		}
		for (uint8_t p = 0; p < parameters; p++)
			if (!is_type_code(record[8 + p], false))
				return fail(diagnostic, MCUSCRIPT_MALFORMED_SECTION, offset);
		program->import_offsets[i] = (uint16_t)offset;
		offset += 8u + parameters;
	}

	/* Names live after the records. */
	const uint8_t *area = table.data + offset;
	uint32_t area_length = table.length - offset;
	for (uint8_t i = 0; i < count; i++) {
		const uint8_t *record = table.data + program->import_offsets[i];
		mcuscript_str name;
		if (!read_name(area, area_length, read_u16(record), &name))
			return fail(diagnostic, MCUSCRIPT_MALFORMED_SECTION, i);
		for (uint8_t j = 0; j < i; j++) {
			mcuscript_str other;
			(void)read_name(area, area_length,
					read_u16(table.data + program->import_offsets[j]),
					&other);
			if (other.length == name.length &&
			    memcmp(other.bytes, name.bytes, name.length) == 0)
				return fail_named(diagnostic, MCUSCRIPT_DUPLICATE_IMPORT, i,
						  name);
		}
	}
	return true;
}

static bool import_name(const mcuscript_program *program, section table, uint8_t index,
			mcuscript_str *out)
{
	uint32_t records_end = 1;
	for (uint8_t i = 0; i < program->import_count; i++) {
		const uint8_t *record = table.data + program->import_offsets[i];
		uint32_t end = program->import_offsets[i] + 8u + record[7];
		if (end > records_end)
			records_end = end;
	}
	return read_name(table.data + records_end, table.length - records_end,
			 read_u16(table.data + program->import_offsets[index]), out);
}

static bool load_functions(mcuscript_program *program, section table, uint32_t code_length,
			   mcuscript_diagnostic *diagnostic)
{
	if (table.length < 1)
		return fail(diagnostic, MCUSCRIPT_MALFORMED_SECTION, 0);
	uint8_t count = table.data[0];
	if (count > MCUSCRIPT_MAX_FUNCTIONS)
		return fail(diagnostic, MCUSCRIPT_BUILD_LIMIT, count);
	program->function_count = count;

	uint32_t offset = 1;
	uint16_t name_offsets[MCUSCRIPT_MAX_FUNCTIONS];
	for (uint8_t i = 0; i < count; i++) {
		if (offset + 12u > table.length)
			return fail(diagnostic, MCUSCRIPT_MALFORMED_SECTION, offset);
		const uint8_t *record = table.data + offset;
		mcuscript_function *fn = &program->functions[i];
		name_offsets[i] = read_u16(record);
		fn->code_offset = read_u32(record + 2);
		fn->flags = record[6];
		fn->return_type = record[7];
		fn->max_stack = record[8];
		fn->max_call_depth = record[9];
		fn->recursion_cap = record[10];
		fn->local_count = record[11];
		if (fn->flags & (uint8_t)~MCUSCRIPT_ENTRY_INVOCABLE)
			return fail(diagnostic, MCUSCRIPT_RESERVED_FIELD_SET, i);
		if (!is_type_code(fn->return_type, true))
			return fail(diagnostic, MCUSCRIPT_MALFORMED_SECTION, offset);
		if (offset + 12u + fn->local_count > table.length)
			return fail(diagnostic, MCUSCRIPT_MALFORMED_SECTION, offset);
		fn->local_types = record + 12;
		for (uint8_t l = 0; l < fn->local_count; l++)
			if (!is_type_code(fn->local_types[l], false))
				return fail(diagnostic, MCUSCRIPT_MALFORMED_SECTION, offset);
		offset += 12u + fn->local_count;
	}

	const uint8_t *area = table.data + offset;
	uint32_t area_length = table.length - offset;
	for (uint8_t i = 0; i < count; i++)
		if (!read_name(area, area_length, name_offsets[i],
			       &program->functions[i].name))
			return fail(diagnostic, MCUSCRIPT_MALFORMED_SECTION, i);

	/* Code regions tile CODE exactly (§2.6.1): sorted by offset, the
	 * first starts at zero, each ends where the next begins. That is
	 * what makes "a branch outside this function" decidable. */
	if (count == 0)
		return code_length == 0 ? true
					: fail(diagnostic, MCUSCRIPT_MALFORMED_SECTION, 0);
	uint32_t expected = 0;
	for (uint8_t placed = 0; placed < count; placed++) {
		uint8_t next = 0xFF;
		uint32_t best = 0;
		for (uint8_t i = 0; i < count; i++) {
			uint32_t start = program->functions[i].code_offset;
			if (start < expected)
				continue;
			if (next == 0xFF || start < best) {
				next = i;
				best = start;
			}
		}
		if (next == 0xFF || best != expected)
			return fail(diagnostic, MCUSCRIPT_MALFORMED_SECTION, expected);
		/* The end is the next start, found on the following pass; fill
		 * it with the section end and correct it below. */
		program->functions[next].code_end = code_length;
		expected = best + 1; /* at least one byte */
	}
	for (uint8_t i = 0; i < count; i++) {
		uint32_t start = program->functions[i].code_offset;
		uint32_t end = code_length;
		for (uint8_t j = 0; j < count; j++) {
			uint32_t other = program->functions[j].code_offset;
			if (other > start && other < end)
				end = other;
		}
		if (end <= start || start >= code_length)
			return fail(diagnostic, MCUSCRIPT_MALFORMED_SECTION, start);
		program->functions[i].code_end = end;
	}
	return true;
}

/* ------------------------------------------------------------------
 * Verification (§2.6)
 *
 * One forward pass in address order. That is possible only because
 * backward jumps are rejected (§3.8), and it is what keeps the memory
 * bounded: the walk has to remember a stack shape per *outstanding
 * forward branch*, not per instruction.
 *
 * The host-side verifier in tools/ uses a worklist instead, and reports
 * which path produced a conflict. Two algorithms over one specification
 * is deliberate — a corpus binds them together, and agreement between
 * two different methods is worth more than agreement between two copies
 * of one.
 */

typedef struct {
	uint8_t types[MCUSCRIPT_MAX_STACK];
	uint8_t depth;
} shape;

typedef struct {
	uint32_t target;
	shape stack;
	bool used;
} pending_branch;

typedef struct {
	const mcuscript_program *program;
	section imports;
	const mcuscript_function *fn;
	shape stack;
	bool reachable;
	uint8_t high_water;
	pending_branch pending[MCUSCRIPT_MAX_PENDING_BRANCHES];
	uint8_t pending_count;
	mcuscript_diagnostic *diagnostic;
	uint32_t pc;
} walker;

static bool push_type(walker *w, uint8_t type)
{
	if (w->stack.depth >= MCUSCRIPT_MAX_STACK)
		return fail(w->diagnostic, MCUSCRIPT_BUILD_LIMIT, w->pc);
	w->stack.types[w->stack.depth++] = type;
	if (w->stack.depth > w->high_water)
		w->high_water = w->stack.depth;
	return true;
}

static bool pop_type(walker *w, uint8_t want, uint8_t *got)
{
	if (w->stack.depth == 0)
		return fail(w->diagnostic, MCUSCRIPT_STACK_UNDERFLOW, w->pc);
	uint8_t type = w->stack.types[--w->stack.depth];
	if (want != MCUSCRIPT_VOID && type != want)
		return fail(w->diagnostic, MCUSCRIPT_TYPE_MISMATCH, w->pc);
	if (got != NULL)
		*got = type;
	return true;
}

static bool binary_i32(walker *w, uint8_t result)
{
	return pop_type(w, MCUSCRIPT_I32, NULL) && pop_type(w, MCUSCRIPT_I32, NULL) &&
	       push_type(w, result);
}

static bool same_shape(const shape *a, const shape *b)
{
	return a->depth == b->depth && memcmp(a->types, b->types, a->depth) == 0;
}

static bool record_branch(walker *w, uint32_t target)
{
	for (uint8_t i = 0; i < w->pending_count; i++) {
		if (w->pending[i].used || w->pending[i].target != target)
			continue;
		if (!same_shape(&w->pending[i].stack, &w->stack))
			return fail(w->diagnostic, MCUSCRIPT_INCONSISTENT_JOIN, target);
		return true;
	}
	for (uint8_t i = 0; i < w->pending_count; i++) {
		if (!w->pending[i].used)
			continue;
		w->pending[i].target = target;
		w->pending[i].stack = w->stack;
		w->pending[i].used = false;
		return true;
	}
	if (w->pending_count >= MCUSCRIPT_MAX_PENDING_BRANCHES)
		return fail(w->diagnostic, MCUSCRIPT_BUILD_LIMIT, target);
	w->pending[w->pending_count].target = target;
	w->pending[w->pending_count].stack = w->stack;
	w->pending[w->pending_count].used = false;
	w->pending_count++;
	return true;
}

static bool merge_at(walker *w, uint32_t pc)
{
	for (uint8_t i = 0; i < w->pending_count; i++) {
		if (w->pending[i].used || w->pending[i].target != pc)
			continue;
		if (w->reachable) {
			if (!same_shape(&w->pending[i].stack, &w->stack))
				return fail(w->diagnostic, MCUSCRIPT_INCONSISTENT_JOIN, pc);
		} else {
			w->stack = w->pending[i].stack;
			w->reachable = true;
			if (w->stack.depth > w->high_water)
				w->high_water = w->stack.depth;
		}
		w->pending[i].used = true;
	}
	return true;
}

static bool constant_type(const mcuscript_program *program, uint8_t index, uint8_t *type)
{
	if (index >= program->constant_count)
		return false;
	*type = program->constants[program->constant_offsets[index]];
	return true;
}

static bool verify_function(const mcuscript_program *program, section imports,
			    const mcuscript_function *fn, uint8_t *computed_stack,
			    mcuscript_diagnostic *diagnostic)
{
	walker w;
	memset(&w, 0, sizeof w);
	w.program = program;
	w.imports = imports;
	w.fn = fn;
	w.reachable = true;
	w.diagnostic = diagnostic;

	const uint8_t *code = program->code;
	uint32_t pc = fn->code_offset;
	while (pc < fn->code_end) {
		w.pc = pc;
		if (!merge_at(&w, pc))
			return false;
		if (!w.reachable)
			return fail(diagnostic, MCUSCRIPT_UNREACHABLE_CODE, pc);

		uint8_t opcode = code[pc];
		unsigned size = mcuscript_instruction_size(opcode);
		if (size == 0)
			return fail(diagnostic, MCUSCRIPT_UNDEFINED_OPCODE, pc);
		if (pc + size > fn->code_end)
			return fail(diagnostic, MCUSCRIPT_TRUNCATED_INSTRUCTION, pc);
		uint8_t index = (size >= 2) ? code[pc + 1] : 0;
		bool ok = true;

		switch (opcode) {
		case OP_CONST_I32_S8:
		case OP_CONST_I32_S16:
			ok = push_type(&w, MCUSCRIPT_I32);
			break;
		case OP_CONST_I32: {
			uint8_t type;
			if (!constant_type(program, index, &type))
				return fail(diagnostic, MCUSCRIPT_INDEX_OUT_OF_RANGE, pc);
			if (type != MCUSCRIPT_I32)
				return fail(diagnostic, MCUSCRIPT_TYPE_MISMATCH, pc);
			ok = push_type(&w, MCUSCRIPT_I32);
			break;
		}
		case OP_CONST_TRUE:
		case OP_CONST_FALSE:
			ok = push_type(&w, MCUSCRIPT_BOOL);
			break;
		case OP_LOAD_L:
			if (index >= fn->local_count)
				return fail(diagnostic, MCUSCRIPT_INDEX_OUT_OF_RANGE, pc);
			ok = push_type(&w, fn->local_types[index]);
			break;
		case OP_STORE_L:
			if (index >= fn->local_count)
				return fail(diagnostic, MCUSCRIPT_INDEX_OUT_OF_RANGE, pc);
			ok = pop_type(&w, fn->local_types[index], NULL);
			break;
		case OP_LOAD_H:
		case OP_STORE_H:
		case OP_CALL_H: {
			if (index >= program->import_count)
				return fail(diagnostic, MCUSCRIPT_INDEX_OUT_OF_RANGE, pc);
			import_view imp;
			import_at(program, index, &imp);
			if (opcode == OP_CALL_H) {
				if (imp.kind != MCUSCRIPT_KIND_FUNCTION)
					return fail(diagnostic, MCUSCRIPT_KIND_MISMATCH, pc);
				for (uint8_t p = imp.parameter_count; p > 0; p--)
					if (!pop_type(&w, imp.parameter_types[p - 1], NULL))
						return false;
				ok = (imp.type == MCUSCRIPT_VOID) ? true
								  : push_type(&w, imp.type);
				break;
			}
			if (imp.kind != MCUSCRIPT_KIND_ENTITY)
				return fail(diagnostic, MCUSCRIPT_KIND_MISMATCH, pc);
			if (opcode == OP_LOAD_H) {
				if (!(imp.access & MCUSCRIPT_ACCESS_READ))
					return fail(diagnostic, MCUSCRIPT_ACCESS_DENIED, pc);
				ok = push_type(&w, imp.type);
			} else {
				if (!(imp.access & MCUSCRIPT_ACCESS_WRITE))
					return fail(diagnostic, MCUSCRIPT_ACCESS_DENIED, pc);
				ok = pop_type(&w, imp.type, NULL);
			}
			break;
		}
		case OP_DROP:
			ok = pop_type(&w, MCUSCRIPT_VOID, NULL);
			break;
		case OP_DUP: {
			uint8_t type;
			ok = pop_type(&w, MCUSCRIPT_VOID, &type) && push_type(&w, type) &&
			     push_type(&w, type);
			break;
		}
		case OP_ADD_I32:
		case OP_SUB_I32:
		case OP_MUL_I32:
		case OP_DIV_I32:
		case OP_REM_I32:
			ok = binary_i32(&w, MCUSCRIPT_I32);
			break;
		case OP_NEG_I32:
			ok = pop_type(&w, MCUSCRIPT_I32, NULL) && push_type(&w, MCUSCRIPT_I32);
			break;
		case OP_EQ_I32:
		case OP_NE_I32:
		case OP_LT_I32:
		case OP_LE_I32:
		case OP_GT_I32:
		case OP_GE_I32:
			ok = binary_i32(&w, MCUSCRIPT_BOOL);
			break;
		case OP_NOT:
			ok = pop_type(&w, MCUSCRIPT_BOOL, NULL) && push_type(&w, MCUSCRIPT_BOOL);
			break;
		case OP_ELSE: {
			uint8_t fallback, value;
			ok = pop_type(&w, MCUSCRIPT_VOID, &fallback) &&
			     pop_type(&w, MCUSCRIPT_VOID, &value);
			if (ok && fallback != value)
				return fail(diagnostic, MCUSCRIPT_TYPE_MISMATCH, pc);
			ok = ok && push_type(&w, value);
			break;
		}
		case OP_IS_VALID:
		case OP_IS_UNAVAILABLE:
		case OP_IS_INVALID:
			ok = pop_type(&w, MCUSCRIPT_VOID, NULL) && push_type(&w, MCUSCRIPT_BOOL);
			break;
		case OP_RET:
			if (fn->return_type != MCUSCRIPT_VOID || w.stack.depth != 0)
				return fail(diagnostic, MCUSCRIPT_UNBALANCED_RETURN, pc);
			w.reachable = false;
			break;
		case OP_RET_V:
			if (fn->return_type == MCUSCRIPT_VOID)
				return fail(diagnostic, MCUSCRIPT_UNBALANCED_RETURN, pc);
			if (!pop_type(&w, fn->return_type, NULL))
				return false;
			if (w.stack.depth != 0)
				return fail(diagnostic, MCUSCRIPT_UNBALANCED_RETURN, pc);
			w.reachable = false;
			break;
		case OP_JMP:
		case OP_JMP_IF_FALSE:
		case OP_JMP_IF_TRUE: {
			if (opcode != OP_JMP && !pop_type(&w, MCUSCRIPT_BOOL, NULL))
				return false;
			int32_t delta = read_i16(code + pc + 1);
			int64_t target = (int64_t)pc + (int64_t)size + delta;
			if (target <= (int64_t)pc)
				return fail(diagnostic, MCUSCRIPT_BACKWARD_BRANCH, pc);
			if (target >= (int64_t)fn->code_end)
				return fail(diagnostic, MCUSCRIPT_BAD_BRANCH_TARGET, pc);
			if (!record_branch(&w, (uint32_t)target))
				return false;
			if (opcode == OP_JMP)
				w.reachable = false;
			break;
		}
		default:
			return fail(diagnostic, MCUSCRIPT_UNDEFINED_OPCODE, pc);
		}
		if (!ok)
			return false;
		pc += size;
	}

	if (w.reachable)
		return fail(diagnostic, MCUSCRIPT_BAD_BRANCH_TARGET, fn->code_end);
	/* A branch target the pass never landed on is a target that is not
	 * an instruction boundary — the pc walked straight past it. */
	for (uint8_t i = 0; i < w.pending_count; i++)
		if (!w.pending[i].used)
			return fail(diagnostic, MCUSCRIPT_BAD_BRANCH_TARGET,
				    w.pending[i].target);

	*computed_stack = w.high_water;
	return true;
}

/* ------------------------------------------------------------------
 * Linking (§4.5)
 */

static bool link_imports(mcuscript_program *program, section table,
			 const mcuscript_host *host, mcuscript_diagnostic *diagnostic)
{
	for (uint8_t i = 0; i < program->import_count; i++) {
		import_view imp;
		import_at(program, i, &imp);
		mcuscript_str name;
		if (!import_name(program, table, i, &name))
			return fail(diagnostic, MCUSCRIPT_MALFORMED_SECTION, i);

		uint8_t found = 0xFF;
		for (uint8_t h = 0; h < host->import_count; h++) {
			if (name_equals(name, host->imports[h].name)) {
				found = h;
				break;
			}
		}
		if (found == 0xFF)
			return fail_named(diagnostic, MCUSCRIPT_UNKNOWN_IMPORT, i, name);

		const mcuscript_import *decl = &host->imports[found];
		if (decl->kind != imp.kind)
			return fail_named(diagnostic, MCUSCRIPT_KIND_MISMATCH, i, name);
		if (decl->type != imp.type)
			return fail_named(diagnostic, MCUSCRIPT_IMPORT_TYPE_MISMATCH, i, name);
		if (decl->dimension != imp.dimension)
			return fail_named(diagnostic, MCUSCRIPT_DIMENSION_MISMATCH, i, name);
		if (imp.kind == MCUSCRIPT_KIND_ENTITY) {
			if ((decl->access & imp.access) != imp.access)
				return fail_named(diagnostic, MCUSCRIPT_ACCESS_DENIED, i, name);
		} else {
			if (decl->parameter_count != imp.parameter_count)
				return fail_named(diagnostic, MCUSCRIPT_SIGNATURE_MISMATCH, i,
						  name);
			for (uint8_t p = 0; p < imp.parameter_count; p++)
				if (decl->parameter_types[p] != imp.parameter_types[p])
					return fail_named(diagnostic,
							  MCUSCRIPT_SIGNATURE_MISMATCH, i,
							  name);
		}
		program->import_map[i] = found;
	}
	return true;
}

/* ------------------------------------------------------------------
 * mcuscript_load
 */

bool mcuscript_load(mcuscript_program *program, const uint8_t *bytes, size_t length,
		    const mcuscript_host *host, uint32_t profile_id,
		    uint16_t profile_major, mcuscript_diagnostic *diagnostic)
{
	memset(program, 0, sizeof *program);
	if (diagnostic != NULL) {
		diagnostic->refusal = MCUSCRIPT_OK;
		diagnostic->where = 0;
		diagnostic->name.bytes = NULL;
		diagnostic->name.length = 0;
	}

	if (length < HEADER_SIZE)
		return fail(diagnostic, MCUSCRIPT_LENGTH_MISMATCH, (uint32_t)length);
	if (memcmp(bytes, "MCUS", 4) != 0)
		return fail(diagnostic, MCUSCRIPT_BAD_MAGIC, 0);
	uint16_t format_version = read_u16(bytes + 4);
	if (format_version > FORMAT_VERSION)
		return fail(diagnostic, MCUSCRIPT_UNSUPPORTED_FORMAT_VERSION, format_version);
	uint16_t flags = read_u16(bytes + 6);
	uint32_t total_length = read_u32(bytes + 8);
	if (total_length != length)
		return fail(diagnostic, MCUSCRIPT_LENGTH_MISMATCH, total_length);
	if (flags != 0)
		return fail(diagnostic, MCUSCRIPT_RESERVED_FIELD_SET, flags);
	if (crc32(bytes, length, 24, 28) != read_u32(bytes + 24))
		return fail(diagnostic, MCUSCRIPT_BAD_CHECKSUM, 0);

	if (read_u32(bytes + 12) != profile_id || read_u16(bytes + 16) != profile_major)
		return fail(diagnostic, MCUSCRIPT_PROFILE_MISMATCH, read_u32(bytes + 12));

	program->required_groups = read_u32(bytes + 20);
	if (program->required_groups & ~(uint32_t)MCUSCRIPT_GROUPS_IMPLEMENTED)
		return fail(diagnostic, MCUSCRIPT_UNSUPPORTED_GROUP,
			    program->required_groups & ~(uint32_t)MCUSCRIPT_GROUPS_IMPLEMENTED);

	section code = { 0 }, constants = { 0 }, entries = { 0 }, imports = { 0 };
	if (!walk_sections(bytes, length, &code, &constants, &entries, &imports, diagnostic))
		return false;

	program->code = code.data;
	program->code_length = code.length;
	if (!load_constants(program, constants, diagnostic))
		return false;
	if (!load_imports(program, imports, diagnostic))
		return false;
	if (!load_functions(program, entries, code.length, diagnostic))
		return false;

	for (uint8_t i = 0; i < program->function_count; i++) {
		mcuscript_function *fn = &program->functions[i];
		uint8_t computed = 0;
		if (!verify_function(program, imports, fn, &computed, diagnostic))
			return false;
		if (computed != fn->max_stack)
			return fail_named(diagnostic, MCUSCRIPT_STACK_DEPTH_MISMATCH, computed,
					  fn->name);
		/* No `call` group in this build, so nothing can call anything
		 * and the only honest call depth is zero. */
		if (fn->max_call_depth != 0)
			return fail_named(diagnostic, MCUSCRIPT_CALL_DEPTH_MISMATCH,
					  fn->max_call_depth, fn->name);
		if ((uint32_t)fn->local_count + fn->max_stack > MCUSCRIPT_MAX_SLOTS)
			return fail_named(diagnostic, MCUSCRIPT_BUILD_LIMIT,
					  (uint32_t)fn->local_count + fn->max_stack, fn->name);
	}

	if (!link_imports(program, imports, host, diagnostic))
		return false;

	program->host = host;
	return true;
}

int mcuscript_find_entry(const mcuscript_program *program, const char *name)
{
	for (uint8_t i = 0; i < program->function_count; i++) {
		const mcuscript_function *fn = &program->functions[i];
		if ((fn->flags & MCUSCRIPT_ENTRY_INVOCABLE) && name_equals(fn->name, name))
			return i;
	}
	return -1;
}

int32_t mcuscript_constant_i32(const mcuscript_program *program, uint8_t index)
{
	return read_i32(program->constants + program->constant_offsets[index] + 1);
}

uint8_t mcuscript_import_type(const mcuscript_program *program, uint8_t index)
{
	return program->imports[program->import_offsets[index] + 4];
}

uint8_t mcuscript_import_parameter_count(const mcuscript_program *program, uint8_t index)
{
	return program->imports[program->import_offsets[index] + 7];
}

uint8_t mcuscript_import_parameter_type(const mcuscript_program *program, uint8_t index,
					uint8_t parameter)
{
	return program->imports[program->import_offsets[index] + 8 + parameter];
}
