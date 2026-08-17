/*
 * SPDX-FileCopyrightText: 2026 The MCUScript Contributors
 * SPDX-License-Identifier: Apache-2.0
 *
 * Loading: parse the container (§2) and resolve the imports (§4.5).
 *
 * **This does not verify** (ADR 0006). Every check here answers one
 * question — *is this container meant for me* — and none of them asks
 * whether it is a good program. That is a decision about what this
 * language is for rather than a shortcut: the same source is equally
 * expressible as this container or as C built into the firmware,
 * nothing guards the C on its way to a device, and a runtime that
 * policed its input would give one of two interchangeable paths a
 * guarantee the other cannot carry. Deciding whether arbitrary bytes
 * are a conforming container is a verifier's job (§2.6.0), and where
 * one belongs is the embedder's call.
 *
 * What that leaves is a rule for the code below: **bounds against the
 * buffer stay, judgements about content go.** A parser that walks off
 * the end of a container it was handed is a defect here, whatever the
 * container was; a parser that has an opinion about the container's
 * stack depth is doing another component's work.
 */

#include <string.h>

#include "internal.h"
#include "mcuscript.h"
#include "opcodes.h"

#define HEADER_SIZE 28
#define FORMAT_VERSION 1

/* ------------------------------------------------------------------
 * Small readers
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

/*
 * CRC-32/ISO-HDLC, bitwise. A table would be four to eight times faster
 * and cost 256 to 1024 bytes of flash on a device that runs this once
 * per load; the loop is the right trade here, and an embedder that
 * disagrees can supply its own.
 *
 * This catches a flipped bit — a mangled encoding, a truncated
 * transfer, a bad flash write — and nothing else. It is not a security
 * control (§2.7).
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
	if (diagnostic != NULL) {
		diagnostic->refusal = refusal;
		diagnostic->where = where;
		diagnostic->name = name;
	}
	return false;
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
			/* Critical and unknown: §2.3 says this container needs
			 * something this build has never heard of, which is an
			 * identity answer and not a judgement. */
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
 *
 * Each of these walks a table to find where its entries start, and
 * stops at the first thing it cannot walk past. A type code it does not
 * know is one of those: the width of a constant follows from its type,
 * so an unrecognised type is not a bad program, it is a table this code
 * cannot step through.
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
		uint32_t width;
		switch (pool.data[offset]) {
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
		uint8_t parameters = table.data[offset + 7];
		if (offset + 8u + parameters > table.length)
			return fail(diagnostic, MCUSCRIPT_MALFORMED_SECTION, offset);
		if (parameters > MCUSCRIPT_MAX_PARAMETERS)
			return fail(diagnostic, MCUSCRIPT_BUILD_LIMIT, parameters);
		program->import_offsets[i] = (uint16_t)offset;
		offset += 8u + parameters;
	}
	program->import_names = table.data + offset;
	program->import_names_length = table.length - offset;
	return true;
}

/* The fixed part of an ENTR record (§4.3), before `local_types`. */
#define RECORD_SIZE 14u

static bool load_functions(mcuscript_program *program, section table,
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
		if (offset + RECORD_SIZE > table.length)
			return fail(diagnostic, MCUSCRIPT_MALFORMED_SECTION, offset);
		const uint8_t *record = table.data + offset;
		mcuscript_function *fn = &program->functions[i];
		name_offsets[i] = read_u16(record);
		fn->code_offset = read_u32(record + 2);
		fn->flags = record[6];
		fn->return_type = record[7];
		/* record[8] is max_stack and record[9] max_call_depth: a
		 * verifier's business, stepped over here (§4.3). */
		fn->recursion_cap = record[10];
		uint8_t component = record[11];
		fn->param_count = record[12];
		fn->local_count = record[13];
		/* The one field read from a record that indexes an array. A
		 * component is named by its lowest member, so it is a function
		 * index — and this loader believes the container about
		 * everything except whether that index is inside the table. */
		if (component >= count)
			return fail(diagnostic, MCUSCRIPT_MALFORMED_SECTION, offset);
		program->component[i] = component;
		if (offset + RECORD_SIZE + fn->local_count > table.length)
			return fail(diagnostic, MCUSCRIPT_MALFORMED_SECTION, offset);
		offset += RECORD_SIZE + fn->local_count;
	}

	const uint8_t *area = table.data + offset;
	uint32_t area_length = table.length - offset;
	for (uint8_t i = 0; i < count; i++)
		if (!read_name(area, area_length, name_offsets[i],
			       &program->functions[i].name))
			return fail(diagnostic, MCUSCRIPT_MALFORMED_SECTION, i);

	/* A component's cap is the cap its members declare (§5.4). They all
	 * declare the same one in a conforming container; this takes the
	 * last, which is the cheapest way to take one of them. */
	memset(program->component_cap, 0, sizeof program->component_cap);
	for (uint8_t i = 0; i < count; i++)
		program->component_cap[program->component[i]] =
			program->functions[i].recursion_cap;
	return true;
}

#undef RECORD_SIZE

/* ------------------------------------------------------------------
 * Linking (§4.5)
 *
 * The one part of loading that is neither parsing nor a header check,
 * and it stays for the same reason the header checks do: an import the
 * host does not offer, or offers with another signature, means this
 * container was built against a different firmware. That is identity.
 */

static bool link_imports(mcuscript_program *program, const mcuscript_host *host,
			 mcuscript_diagnostic *diagnostic)
{
	for (uint8_t i = 0; i < program->import_count; i++) {
		import_view imp;
		import_at(program, i, &imp);
		mcuscript_str name;
		if (!read_name(program->import_names, program->import_names_length,
			       read_u16(program->imports + program->import_offsets[i]),
			       &name))
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
	if (program->required_groups & ~(uint32_t)MCUSCRIPT_GROUPS)
		return fail(diagnostic, MCUSCRIPT_UNSUPPORTED_GROUP,
			    program->required_groups & ~(uint32_t)MCUSCRIPT_GROUPS);

	section code = { 0 }, constants = { 0 }, entries = { 0 }, imports = { 0 };
	if (!walk_sections(bytes, length, &code, &constants, &entries, &imports, diagnostic))
		return false;

	program->code = code.data;
	program->code_length = code.length;
	if (!load_constants(program, constants, diagnostic))
		return false;
	if (!load_imports(program, imports, diagnostic))
		return false;
	if (!load_functions(program, entries, diagnostic))
		return false;
	if (!link_imports(program, host, diagnostic))
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

int64_t mcuscript_constant_i64(const mcuscript_program *program, uint8_t index)
{
	const uint8_t *at = program->constants + program->constant_offsets[index] + 1;
	uint64_t bits = (uint64_t)read_u32(at) | ((uint64_t)read_u32(at + 4) << 32);
	return (int64_t)bits;
}

uint32_t mcuscript_constant_f32_bits(const mcuscript_program *program, uint8_t index)
{
	return read_u32(program->constants + program->constant_offsets[index] + 1);
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
