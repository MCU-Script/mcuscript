/*
 * SPDX-FileCopyrightText: 2026 The MCUScript Contributors
 * SPDX-License-Identifier: Apache-2.0
 *
 * The constructors an embedder answers a `read` or an `invoke` with.
 *
 * There is one per data type a dimension may be held in, and that is
 * the property worth a test: the set was incomplete until a profile
 * declared a clock in an `i64` and there was no way to return one
 * except by reaching into the union. Nothing here is clever — it is
 * here so that the next type added to `mcuscript_type` is noticed.
 */

#include <stdio.h>
#include <string.h>

#include "mcuscript.h"

static int failures;

static void check(const char *what, bool held)
{
	if (!held) {
		printf("FAIL %s\n", what);
		failures++;
		return;
	}
	printf("ok   %s\n", what);
}

int main(void)
{
	mcuscript_value i32 = mcuscript_i32(-2147483647 - 1);
	check("an i32 keeps its value", i32.as.i32 == -2147483647 - 1);
	check("an i32 is valid", i32.validity == MCUSCRIPT_VALID);

	/* The case the set was missing: a clock counting milliseconds from
	 * 1970 does not fit in 32 bits and is exactly what an import
	 * returns. */
	mcuscript_value i64 = mcuscript_i64(INT64_C(1787198571000));
	check("an i64 keeps its value", i64.as.i64 == INT64_C(1787198571000));
	check("an i64 is valid", i64.validity == MCUSCRIPT_VALID);

	mcuscript_value f32 = mcuscript_f32(0.5f);
	check("an f32 keeps its value", f32.as.f32 == 0.5f);
	check("an f32 is valid", f32.validity == MCUSCRIPT_VALID);

	mcuscript_value yes = mcuscript_bool(true);
	check("a bool keeps its value", yes.as.boolean);
	check("a bool is valid", yes.validity == MCUSCRIPT_VALID);

	/* Absence carries no number, and says so in every width. */
	mcuscript_value gone = mcuscript_absent(MCUSCRIPT_UNAVAILABLE);
	check("an absent value is not valid", gone.validity == MCUSCRIPT_UNAVAILABLE);
	check("an absent value reads as zero", gone.as.i64 == 0);

	printf(failures == 0 ? "\nall passed\n" : "\n%d failed\n", failures);
	return failures == 0 ? 0 : 1;
}
