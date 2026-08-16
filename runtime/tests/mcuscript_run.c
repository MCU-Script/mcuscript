/*
 * SPDX-FileCopyrightText: 2026 The MCUScript Contributors
 * SPDX-License-Identifier: Apache-2.0
 *
 * A reference embedder, small enough to read in one sitting, and the
 * program the test suite drives.
 *
 * It exists to make the runtime observable from outside: it loads a
 * container against a host described in a text file, invokes an entry
 * point, and prints what happened in a line-oriented form. The C
 * backend will be driven through the same protocol, and comparing the
 * two outputs is the differential test the whole project rests on — so
 * this output format is a contract, not a convenience.
 *
 *     mcuscript-run <container> <host-file> [<entry>]
 *
 * Host file lines:
 *     entity read i32 temp dim 1 = 250
 *     entity write i32 fan.speed dim 2
 *     entity rw i32 memory
 *     function i32 clamp i32 i32 = 7
 *     function void log i32 = fault
 *
 * A value is a number, `true`, `false`, `unavailable` or `invalid`.
 *
 * Output:
 *     refused <name> at <where> [<subject>]
 *     write <name> <value> <validity>
 *     fault <name>
 *     result <type> <value> <validity>
 *     done
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "mcuscript.h"

#define MAX_ENTRIES 32
#define MAX_NAME 64
#define MAX_FILE (64 * 1024)

struct slot {
	char name[MAX_NAME];
	uint8_t parameter_types[MCUSCRIPT_MAX_PARAMETERS];
	mcuscript_value value;
	bool faults;
};

struct world {
	struct slot slots[MAX_ENTRIES];
	mcuscript_import imports[MAX_ENTRIES];
	uint8_t count;
};

static const char *validity_name(uint8_t validity)
{
	switch (validity) {
	case MCUSCRIPT_VALID:
		return "valid";
	case MCUSCRIPT_UNAVAILABLE:
		return "unavailable";
	default:
		return "invalid";
	}
}

static const char *type_name(uint8_t type)
{
	switch (type) {
	case MCUSCRIPT_I32:
		return "i32";
	case MCUSCRIPT_I64:
		return "i64";
	case MCUSCRIPT_F32:
		return "f32";
	case MCUSCRIPT_BOOL:
		return "bool";
	default:
		return "void";
	}
}

static void print_value(uint8_t type, mcuscript_value value)
{
	if (type == MCUSCRIPT_BOOL)
		printf("%s %s", value.as.boolean ? "true" : "false",
		       validity_name(value.validity));
	else
		printf("%ld %s", (long)value.as.i32, validity_name(value.validity));
}

/* -- the host callbacks -------------------------------------------- */

static mcuscript_value host_read(void *context, uint8_t index)
{
	struct world *world = context;
	return world->slots[index].value;
}

static void host_write(void *context, uint8_t index, mcuscript_value value)
{
	struct world *world = context;
	/* Applied immediately, and remembered so the script reads back what
	 * it wrote (§1.6). Buffering to a commit point would be equally
	 * conforming; this embedder chose the simpler policy (§5.7). */
	world->slots[index].value = value;
	printf("write %s ", world->slots[index].name);
	print_value(world->imports[index].type, value);
	printf("\n");
}

static bool host_invoke(void *context, uint8_t index, const mcuscript_value *arguments,
			mcuscript_value *result)
{
	struct world *world = context;
	if (world->slots[index].faults)
		return false;
	(void)arguments;
	*result = world->slots[index].value;
	return true;
}

/* -- reading the host file ------------------------------------------ */

static uint8_t parse_type(const char *token)
{
	if (strcmp(token, "i32") == 0)
		return MCUSCRIPT_I32;
	if (strcmp(token, "i64") == 0)
		return MCUSCRIPT_I64;
	if (strcmp(token, "f32") == 0)
		return MCUSCRIPT_F32;
	if (strcmp(token, "bool") == 0)
		return MCUSCRIPT_BOOL;
	return MCUSCRIPT_VOID;
}

static bool parse_value(const char *token, uint8_t type, mcuscript_value *out, bool *faults)
{
	*faults = false;
	if (strcmp(token, "fault") == 0) {
		*faults = true;
		*out = mcuscript_absent(MCUSCRIPT_UNAVAILABLE);
		return true;
	}
	if (strcmp(token, "unavailable") == 0) {
		*out = mcuscript_absent(MCUSCRIPT_UNAVAILABLE);
		return true;
	}
	if (strcmp(token, "invalid") == 0) {
		*out = mcuscript_absent(MCUSCRIPT_INVALID);
		return true;
	}
	if (strcmp(token, "true") == 0 || strcmp(token, "false") == 0) {
		*out = mcuscript_bool(strcmp(token, "true") == 0);
		return true;
	}
	char *end = NULL;
	long parsed = strtol(token, &end, 0);
	if (end == token || *end != '\0')
		return false;
	*out = (type == MCUSCRIPT_BOOL) ? mcuscript_bool(parsed != 0)
					: mcuscript_i32((int32_t)parsed);
	return true;
}

static bool read_host(const char *path, struct world *world)
{
	FILE *file = fopen(path, "r");
	if (file == NULL) {
		fprintf(stderr, "cannot open %s\n", path);
		return false;
	}
	char line[512];
	while (fgets(line, sizeof line, file) != NULL) {
		char *tokens[24];
		int count = 0;
		for (char *token = strtok(line, " \t\r\n"); token != NULL && count < 24;
		     token = strtok(NULL, " \t\r\n"))
			tokens[count++] = token;
		if (count == 0 || tokens[0][0] == '#')
			continue;
		if (world->count >= MAX_ENTRIES) {
			fprintf(stderr, "too many host entries\n");
			fclose(file);
			return false;
		}

		struct slot *slot = &world->slots[world->count];
		mcuscript_import *decl = &world->imports[world->count];
		memset(slot, 0, sizeof *slot);
		memset(decl, 0, sizeof *decl);
		slot->value = mcuscript_absent(MCUSCRIPT_UNAVAILABLE);

		int at = 0;
		bool entity = strcmp(tokens[at], "entity") == 0;
		at++;
		decl->kind = entity ? MCUSCRIPT_KIND_ENTITY : MCUSCRIPT_KIND_FUNCTION;
		if (entity) {
			const char *access = tokens[at++];
			decl->access = (strcmp(access, "read") == 0)    ? MCUSCRIPT_ACCESS_READ
				       : (strcmp(access, "write") == 0) ? MCUSCRIPT_ACCESS_WRITE
									: MCUSCRIPT_ACCESS_BOTH;
		}
		decl->type = parse_type(tokens[at++]);
		snprintf(slot->name, sizeof slot->name, "%s", tokens[at++]);
		decl->name = slot->name;

		while (at < count) {
			if (strcmp(tokens[at], "dim") == 0 && at + 1 < count) {
				decl->dimension = (uint16_t)strtoul(tokens[at + 1], NULL, 0);
				at += 2;
			} else if (strcmp(tokens[at], "=") == 0 && at + 1 < count) {
				if (!parse_value(tokens[at + 1], decl->type, &slot->value,
						 &slot->faults)) {
					fprintf(stderr, "bad value %s\n", tokens[at + 1]);
					fclose(file);
					return false;
				}
				at += 2;
			} else if (!entity) {
				if (decl->parameter_count >= MCUSCRIPT_MAX_PARAMETERS) {
					fprintf(stderr, "too many parameters\n");
					fclose(file);
					return false;
				}
				slot->parameter_types[decl->parameter_count++] =
					parse_type(tokens[at++]);
			} else {
				fprintf(stderr, "unexpected token %s\n", tokens[at]);
				fclose(file);
				return false;
			}
		}
		decl->parameter_types = slot->parameter_types;
		world->count++;
	}
	fclose(file);
	return true;
}

/* -- main ------------------------------------------------------------ */

int main(int argc, char **argv)
{
	if (argc < 3) {
		fprintf(stderr, "usage: mcuscript-run <container> <host> [<entry>]\n");
		return 2;
	}

	static uint8_t container[MAX_FILE];
	FILE *file = fopen(argv[1], "rb");
	if (file == NULL) {
		fprintf(stderr, "cannot open %s\n", argv[1]);
		return 2;
	}
	size_t length = fread(container, 1, sizeof container, file);
	fclose(file);

	static struct world world;
	if (!read_host(argv[2], &world))
		return 2;

	static mcuscript_host host;
	host.imports = world.imports;
	host.import_count = world.count;
	host.read = host_read;
	host.write = host_write;
	host.invoke = host_invoke;
	host.context = &world;

	static mcuscript_program program;
	mcuscript_diagnostic diagnostic;
	/* The profile the test corpus compiles against. A real embedder
	 * carries the one its firmware was built with. */
	if (!mcuscript_load(&program, container, length, &host, 1, 0, &diagnostic)) {
		printf("refused %s at %lu", mcuscript_refusal_name(diagnostic.refusal),
		       (unsigned long)diagnostic.where);
		if (diagnostic.name.bytes != NULL)
			printf(" %.*s", (int)diagnostic.name.length, diagnostic.name.bytes);
		printf("\n");
		return 1;
	}

	const char *wanted = (argc > 3) ? argv[3] : NULL;
	int entry = -1;
	if (wanted != NULL) {
		entry = mcuscript_find_entry(&program, wanted);
	} else {
		for (uint8_t i = 0; i < program.function_count; i++) {
			if (program.functions[i].flags & MCUSCRIPT_ENTRY_INVOCABLE) {
				entry = i;
				break;
			}
		}
	}
	if (entry < 0) {
		fprintf(stderr, "no such entry point\n");
		return 2;
	}

	static mcuscript_slots slots;
	mcuscript_value result = mcuscript_absent(MCUSCRIPT_UNAVAILABLE);
	mcuscript_fault fault = MCUSCRIPT_NO_FAULT;
	if (!mcuscript_invoke(&program, entry, &slots, &result, &fault)) {
		printf("fault %s\n", mcuscript_fault_name(fault));
		return 3;
	}
	uint8_t returns = program.functions[entry].return_type;
	if (returns != MCUSCRIPT_VOID) {
		printf("result %s ", type_name(returns));
		print_value(returns, result);
		printf("\n");
	}
	printf("done\n");
	return 0;
}
