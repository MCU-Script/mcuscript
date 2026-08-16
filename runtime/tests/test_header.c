/*
 * SPDX-FileCopyrightText: 2026 The MCUScript Contributors
 * SPDX-License-Identifier: Apache-2.0
 *
 * The refusals a loader owes before it has understood anything: what it
 * does with a buffer that is too short, does not start with the magic,
 * or claims a length it does not have. These need no valid container to
 * mutate, so they are checked here in C alone — `ctest` on its own has
 * to mean something.
 *
 * Everything past the header is checked from Python, against containers
 * the assembler built and a test mutated, because that is where a
 * refusal is worth comparing between the two verifiers.
 */

#include <stdio.h>
#include <string.h>

#include "mcuscript.h"

static int failures;

static void check(const char *what, mcuscript_refusal expected, const uint8_t *bytes,
		  size_t length)
{
	mcuscript_program program;
	mcuscript_diagnostic diagnostic;
	mcuscript_host host = { 0 };

	bool loaded = mcuscript_load(&program, bytes, length, &host, 0, 0, &diagnostic);
	if (loaded) {
		printf("FAIL %s: loaded, expected %s\n", what,
		       mcuscript_refusal_name(expected));
		failures++;
		return;
	}
	if (diagnostic.refusal != expected) {
		printf("FAIL %s: got %s, expected %s\n", what,
		       mcuscript_refusal_name(diagnostic.refusal),
		       mcuscript_refusal_name(expected));
		failures++;
		return;
	}
	printf("ok   %s -> %s\n", what, mcuscript_refusal_name(diagnostic.refusal));
}

int main(void)
{
	uint8_t empty[4] = { 0 };
	check("a buffer shorter than a header", MCUSCRIPT_LENGTH_MISMATCH, empty,
	      sizeof empty);

	uint8_t header[28];
	memset(header, 0, sizeof header);
	check("a header of zeroes", MCUSCRIPT_BAD_MAGIC, header, sizeof header);

	memcpy(header, "MCUS", 4);
	header[4] = 99; /* format_version */
	check("a newer format version", MCUSCRIPT_UNSUPPORTED_FORMAT_VERSION, header,
	      sizeof header);

	header[4] = 1;
	header[8] = 200; /* total_length */
	check("a length that is not the file's", MCUSCRIPT_LENGTH_MISMATCH, header,
	      sizeof header);

	header[8] = 28;
	header[6] = 1; /* reserved flags */
	check("a reserved flag bit", MCUSCRIPT_RESERVED_FIELD_SET, header, sizeof header);

	header[6] = 0;
	check("a wrong checksum", MCUSCRIPT_BAD_CHECKSUM, header, sizeof header);

	printf(failures == 0 ? "\nall passed\n" : "\n%d failed\n", failures);
	return failures == 0 ? 0 : 1;
}
