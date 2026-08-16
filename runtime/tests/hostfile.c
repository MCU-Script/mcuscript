/*
 * SPDX-FileCopyrightText: 2026 The MCUScript Contributors
 * SPDX-License-Identifier: Apache-2.0
 *
 * See hostfile.h. This embedder applies writes immediately and
 * remembers them, so a script reads back what it wrote (§1.6).
 * Buffering to a commit point would be equally conforming and is what
 * §5.7 recommends for a real device; the simpler policy is chosen here
 * because a test should show what the script did, in order.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "hostfile.h"

#define MAX_ENTRIES 32
#define MAX_NAME 64

struct slot {
	char name[MAX_NAME];
	uint8_t parameter_types[MCUSCRIPT_MAX_PARAMETERS];
	mcuscript_value value;
	bool faults;
};

static struct slot slots[MAX_ENTRIES];
static mcuscript_import declarations[MAX_ENTRIES];
static uint8_t entries;
static mcuscript_host host;

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
	switch (type) {
	case MCUSCRIPT_BOOL:
		printf("%s", value.as.boolean ? "true" : "false");
		break;
	case MCUSCRIPT_I64:
		printf("%lld", (long long)value.as.i64);
		break;
	case MCUSCRIPT_F32: {
		/* The bit pattern first, because that is what "the two
		 * backends agree" has to mean for a float: %.9g round-trips
		 * binary32, but a decimal rendering is a second thing that
		 * could differ. The decimal is for a human, in brackets. */
		uint32_t bits;
		memcpy(&bits, &value.as.f32, sizeof bits);
		printf("0x%08lx(%.9g)", (unsigned long)bits, (double)value.as.f32);
		break;
	}
	default:
		printf("%ld", (long)value.as.i32);
		break;
	}
	printf(" %s", validity_name(value.validity));
}

/* -- the callbacks -------------------------------------------------- */

static mcuscript_value read_at(void *context, uint8_t index)
{
	(void)context;
	return slots[index].value;
}

static void write_at(void *context, uint8_t index, mcuscript_value value)
{
	(void)context;
	slots[index].value = value;
	printf("write %s ", slots[index].name);
	print_value(declarations[index].type, value);
	printf("\n");
}

static bool invoke_at(void *context, uint8_t index, const mcuscript_value *arguments,
		      mcuscript_value *result)
{
	(void)context;
	(void)arguments;
	if (slots[index].faults)
		return false;
	*result = slots[index].value;
	return true;
}

static int index_of(const char *name)
{
	for (uint8_t i = 0; i < entries; i++)
		if (strcmp(slots[i].name, name) == 0)
			return i;
	fprintf(stderr, "the host file declares no '%s'\n", name);
	exit(2);
}

mcuscript_value hostfile_read_by_name(const char *name)
{
	return read_at(NULL, (uint8_t)index_of(name));
}

void hostfile_write_by_name(const char *name, mcuscript_value value)
{
	write_at(NULL, (uint8_t)index_of(name), value);
}

bool hostfile_call_by_name(const char *name, const mcuscript_value *arguments,
			   mcuscript_value *result)
{
	return invoke_at(NULL, (uint8_t)index_of(name), arguments, result);
}

const mcuscript_host *hostfile_host(void)
{
	host.imports = declarations;
	host.import_count = entries;
	host.read = read_at;
	host.write = write_at;
	host.invoke = invoke_at;
	host.context = NULL;
	return &host;
}

/* -- output --------------------------------------------------------- */

void hostfile_print_result(uint8_t type, mcuscript_value value)
{
	if (type == MCUSCRIPT_VOID)
		return;
	printf("result %s ", type_name(type));
	print_value(type, value);
	printf("\n");
}

void hostfile_print_fault(mcuscript_fault fault)
{
	printf("fault %s\n", mcuscript_fault_name(fault));
}

void hostfile_print_done(void)
{
	printf("done\n");
}

/* -- parsing -------------------------------------------------------- */

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

static bool parse_value(const char *token, uint8_t type, mcuscript_value *out,
			bool *faults)
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
	if (type == MCUSCRIPT_F32) {
		out->as.i64 = 0;
		out->validity = MCUSCRIPT_VALID;
		if (token[0] == '0' && (token[1] == 'x' || token[1] == 'X')) {
			/* An exact bit pattern, so a test can name a specific
			 * NaN or the smallest subnormal without going through
			 * a decimal that might not round back. */
			uint32_t bits = (uint32_t)strtoul(token + 2, &end, 16);
			memcpy(&out->as.f32, &bits, sizeof bits);
		} else {
			out->as.f32 = strtof(token, &end);
		}
		return end != token && *end == '\0';
	}
	long long parsed = strtoll(token, &end, 0);
	if (end == token || *end != '\0')
		return false;
	out->as.i64 = 0;
	out->validity = MCUSCRIPT_VALID;
	if (type == MCUSCRIPT_BOOL)
		out->as.boolean = parsed != 0;
	else if (type == MCUSCRIPT_I64)
		out->as.i64 = (int64_t)parsed;
	else
		out->as.i32 = (int32_t)parsed;
	return true;
}

bool hostfile_load(const char *path)
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
		if (entries >= MAX_ENTRIES) {
			fprintf(stderr, "too many host entries\n");
			fclose(file);
			return false;
		}

		struct slot *slot = &slots[entries];
		mcuscript_import *decl = &declarations[entries];
		memset(slot, 0, sizeof *slot);
		memset(decl, 0, sizeof *decl);
		slot->value = mcuscript_absent(MCUSCRIPT_UNAVAILABLE);

		int at = 0;
		bool entity = strcmp(tokens[at], "entity") == 0;
		at++;
		decl->kind = entity ? MCUSCRIPT_KIND_ENTITY : MCUSCRIPT_KIND_FUNCTION;
		if (entity) {
			const char *access = tokens[at++];
			decl->access = (strcmp(access, "read") == 0) ? MCUSCRIPT_ACCESS_READ
				       : (strcmp(access, "write") == 0)
					       ? MCUSCRIPT_ACCESS_WRITE
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
		entries++;
	}
	fclose(file);
	return true;
}
