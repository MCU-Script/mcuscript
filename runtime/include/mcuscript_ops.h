/*
 * SPDX-FileCopyrightText: 2026 The MCUScript Contributors
 * SPDX-License-Identifier: Apache-2.0
 *
 * The arithmetic and validity primitives, shared by both backends.
 *
 * The interpreter includes this header and so does every generated C
 * translation unit, which means division by zero, integer wrapping and
 * the propagation of an absent value cannot differ between them — they
 * are not two implementations that agree, they are one implementation
 * used twice.
 *
 * That is a deliberate trade. It makes the differential test weaker for
 * arithmetic, because a shared bug is invisible to it, and it makes the
 * product stronger, because the class of divergence the test was
 * looking for cannot occur. Everything the test still covers —
 * evaluation order, stack discipline, control flow, what reaches the
 * host and when — is where two independently written backends actually
 * differ. Should a toolchain ever appear that cannot take this header,
 * the test gets its teeth back and this note explains why it needs
 * them.
 *
 * Everything here is `static inline` and free of state, so a
 * translation unit that includes it links against nothing.
 */

#ifndef MCUSCRIPT_OPS_H
#define MCUSCRIPT_OPS_H

#include <stdbool.h>
#include <stdint.h>
#include <string.h>

/* Validity ordinals, repeated here so a generated translation unit can
 * include this header alone. They must match mcuscript.h. */
#define MCUSCRIPT_OPS_VALID 0
#define MCUSCRIPT_OPS_UNAVAILABLE 1
#define MCUSCRIPT_OPS_INVALID 2

/*
 * Propagation is the maximum of the operands' ordinals (§1.3): a defect
 * outranks a wait, because a defect is the more informative thing to
 * report. Branchless, so neither backend pays for it and neither can
 * drift.
 */
static inline uint8_t mcuscript_op_worse(uint8_t a, uint8_t b)
{
	return a > b ? a : b;
}

/*
 * A slot is eight bytes and untagged (§1.2). These two are how a
 * narrower value gets in and out of one, and both backends use them so
 * neither can invent its own sign extension.
 */
static inline int32_t mcuscript_op_as_i32(uint64_t slot)
{
	return (int32_t)(uint32_t)slot;
}

static inline uint64_t mcuscript_op_from_i32(int32_t value)
{
	return (uint64_t)(uint32_t)value;
}

/*
 * Signed overflow is undefined in C, so every wrapping operation is
 * computed in the unsigned type of the same width and converted back
 * (§1.5). Not defensive style — the only way the two backends can be
 * made to agree, because a C compiler is entitled to assume the
 * undefined case never happens and will optimise on that assumption.
 */
static inline int32_t mcuscript_op_add_i32(int32_t a, int32_t b)
{
	return (int32_t)((uint32_t)a + (uint32_t)b);
}

static inline int32_t mcuscript_op_sub_i32(int32_t a, int32_t b)
{
	return (int32_t)((uint32_t)a - (uint32_t)b);
}

static inline int32_t mcuscript_op_mul_i32(int32_t a, int32_t b)
{
	return (int32_t)((uint32_t)a * (uint32_t)b);
}

static inline int32_t mcuscript_op_neg_i32(int32_t a)
{
	return (int32_t)(0u - (uint32_t)a);
}

/*
 * Division and remainder produce a *value*, never a fault: a division by
 * zero is overwhelmingly a sensor that happened to read zero, and a
 * value the script can handle with `else` beats a dead script (§5.5).
 *
 * `state` is the propagated state of the operands on the way in and the
 * result's state on the way out.
 */
static inline int32_t mcuscript_op_div_i32(int32_t a, int32_t b, uint8_t *state)
{
	if (b == 0) {
		*state = MCUSCRIPT_OPS_INVALID;
		return 0;
	}
	if (a == INT32_MIN && b == -1) {
		/* The mathematical result is not representable. */
		*state = MCUSCRIPT_OPS_INVALID;
		return 0;
	}
	return a / b;
}

static inline int32_t mcuscript_op_rem_i32(int32_t a, int32_t b, uint8_t *state)
{
	if (b == 0) {
		*state = MCUSCRIPT_OPS_INVALID;
		return 0;
	}
	if (a == INT32_MIN && b == -1) {
		/* Defined, and zero — unlike the quotient (§1.5). */
		return 0;
	}
	return a % b;
}

/* ------------------------------------------------------------------
 * i64
 */

static inline int64_t mcuscript_op_as_i64(uint64_t slot)
{
	return (int64_t)slot;
}

static inline uint64_t mcuscript_op_from_i64(int64_t value)
{
	return (uint64_t)value;
}

static inline int64_t mcuscript_op_add_i64(int64_t a, int64_t b)
{
	return (int64_t)((uint64_t)a + (uint64_t)b);
}

static inline int64_t mcuscript_op_sub_i64(int64_t a, int64_t b)
{
	return (int64_t)((uint64_t)a - (uint64_t)b);
}

static inline int64_t mcuscript_op_mul_i64(int64_t a, int64_t b)
{
	return (int64_t)((uint64_t)a * (uint64_t)b);
}

static inline int64_t mcuscript_op_neg_i64(int64_t a)
{
	return (int64_t)(0u - (uint64_t)a);
}

static inline int64_t mcuscript_op_div_i64(int64_t a, int64_t b, uint8_t *state)
{
	if (b == 0 || (a == INT64_MIN && b == -1)) {
		*state = MCUSCRIPT_OPS_INVALID;
		return 0;
	}
	return a / b;
}

static inline int64_t mcuscript_op_rem_i64(int64_t a, int64_t b, uint8_t *state)
{
	if (b == 0) {
		*state = MCUSCRIPT_OPS_INVALID;
		return 0;
	}
	if (a == INT64_MIN && b == -1)
		return 0;
	return a % b;
}

/* ------------------------------------------------------------------
 * f32
 *
 * A slot holds the *bit pattern*, never a wider value, so every
 * operation ends in a store that narrows to binary32 at the same point
 * in both backends. An FPU that evaluates in a wider format internally
 * (x87, FLT_EVAL_METHOD == 2) therefore cannot let one backend keep an
 * intermediate the other has already rounded.
 *
 * The arithmetic itself needs no help. IEEE-754 defines +, -, * and /
 * as the correctly rounded result of the exact mathematical operation,
 * so there is exactly one right answer and every conforming
 * implementation produces it.
 *
 * **The store is not enough on its own, and that was measured rather
 * than assumed.** With -ffp-contract=fast a compiler contracts across
 * the store as happily as within an expression: on x86-64 with -mfma,
 * `a*b + c` for 1e20, 1e20, -inf gives NaN interpreted and -inf
 * compiled — not a last-digit difference, a different kind of number.
 * GCC's default is `fast` under -std=gnu* and `on` under -std=c*, so
 * the same source diverges or does not depending on a flag nobody
 * thinks about.
 *
 * A conforming build therefore passes **-ffp-contract=off** and never
 * -ffast-math, which additionally flushes subnormals to zero (measured:
 * the smallest normal times 0.5 becomes 0x00000000 compiled and stays
 * 0x00400000 interpreted).
 */

#if defined(__FAST_MATH__)
#error "MCUScript requires IEEE-754 arithmetic: -ffast-math is not a conforming build"
#endif

static inline float mcuscript_op_as_f32(uint64_t slot)
{
	uint32_t bits = (uint32_t)slot;
	float value;
	/* memcpy, not a union and not a pointer cast: the others are
	 * aliasing violations, and every compiler turns this into
	 * nothing. */
	memcpy(&value, &bits, sizeof value);
	return value;
}

static inline uint64_t mcuscript_op_from_f32(float value)
{
	uint32_t bits;
	memcpy(&bits, &value, sizeof bits);
	return (uint64_t)bits;
}

static inline float mcuscript_op_add_f32(float a, float b)
{
	return a + b;
}

static inline float mcuscript_op_sub_f32(float a, float b)
{
	return a - b;
}

static inline float mcuscript_op_mul_f32(float a, float b)
{
	return a * b;
}

/* Division by zero follows IEEE-754 and yields an infinity, unlike
 * integer division — IEEE has a defined answer and integers do not
 * (§3.5). A NaN is a *valid* NaN value, not the `invalid` state. */
static inline float mcuscript_op_div_f32(float a, float b)
{
	return a / b;
}

static inline float mcuscript_op_neg_f32(float a)
{
	return -a;
}

static inline float mcuscript_op_convert_i32_f32(int32_t value)
{
	return (float)value;
}

/*
 * C leaves an out-of-range float-to-integer conversion undefined, so a
 * backend that emitted a bare cast would diverge from the other on
 * exactly the input a faulty sensor produces (§3.5). The range test is
 * written so that NaN fails it: NaN compares false against everything.
 */
static inline int32_t mcuscript_op_trunc_f32_i32(float value, uint8_t *state)
{
	if (!(value >= -2147483648.0f && value < 2147483648.0f)) {
		*state = MCUSCRIPT_OPS_INVALID;
		return 0;
	}
	return (int32_t)value;
}

#endif /* MCUSCRIPT_OPS_H */
