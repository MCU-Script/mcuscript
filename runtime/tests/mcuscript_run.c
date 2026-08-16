/*
 * SPDX-FileCopyrightText: 2026 The MCUScript Contributors
 * SPDX-License-Identifier: Apache-2.0
 *
 * A reference embedder for the VM, and the program the test suite
 * drives.
 *
 *     mcuscript-run <container> <host-file> [<entry>]
 *
 * It loads a container against the host described in a text file
 * (hostfile.h), invokes an entry point and prints what happened. The
 * generated C answers in the same protocol through the same code, and
 * comparing the two is the differential test.
 */

#include <stdio.h>

#include "hostfile.h"
#include "mcuscript.h"

#define MAX_FILE (64 * 1024)

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

	if (!hostfile_load(argv[2]))
		return 2;

	static mcuscript_program program;
	mcuscript_diagnostic diagnostic;
	/* The profile the test corpus compiles against. A real embedder
	 * carries the one its firmware was built with. */
	if (!mcuscript_load(&program, container, length, hostfile_host(), 1, 0,
			    &diagnostic)) {
		printf("refused %s at %lu", mcuscript_refusal_name(diagnostic.refusal),
		       (unsigned long)diagnostic.where);
		if (diagnostic.name.bytes != NULL)
			printf(" %.*s", (int)diagnostic.name.length, diagnostic.name.bytes);
		printf("\n");
		return 1;
	}

	int entry = -1;
	if (argc > 3) {
		entry = mcuscript_find_entry(&program, argv[3]);
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
		hostfile_print_fault(fault);
		return 3;
	}
	hostfile_print_result(program.functions[entry].return_type, result);
	hostfile_print_done();
	return 0;
}
