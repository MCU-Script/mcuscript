/*
 * SPDX-FileCopyrightText: 2026 The MCUScript Contributors
 * SPDX-License-Identifier: Apache-2.0
 *
 * The opcode numbers of specification §3.
 *
 * Each entry carries its mnemonic in a trailing comment, and a test
 * parses this file and compares it against
 * tools/src/mcuscript/opcodes.py — the Python table is the single source
 * of truth, and an instruction added to one and not the other fails the
 * build. The C side stays hand-written rather than generated because
 * the runtime must be buildable with nothing but a C compiler.
 */

#ifndef MCUSCRIPT_OPCODES_H
#define MCUSCRIPT_OPCODES_H

/* Group bits in the container header (§2.5). */
#define MCUSCRIPT_GROUP_CORE (1u << 0)
#define MCUSCRIPT_GROUP_I64 (1u << 1)
#define MCUSCRIPT_GROUP_FLOAT (1u << 2)
#define MCUSCRIPT_GROUP_CALL (1u << 3)
#define MCUSCRIPT_GROUP_BITS (1u << 4)
#define MCUSCRIPT_GROUP_LOOP (1u << 5)

/* What this build implements. Everything else is refused at load, by
 * name, before anything runs. */
#define MCUSCRIPT_GROUPS_IMPLEMENTED (MCUSCRIPT_GROUP_CORE)

enum {
	/* constants */
	OP_CONST_I32_S8 = 0x01,  /* const.i32.s8 */
	OP_CONST_I32_S16 = 0x02, /* const.i32.s16 */
	OP_CONST_I32 = 0x03,     /* const.i32 */
	OP_CONST_TRUE = 0x04,    /* const.true */
	OP_CONST_FALSE = 0x05,   /* const.false */
	/* locals */
	OP_LOAD_L = 0x06,  /* load.l */
	OP_STORE_L = 0x07, /* store.l */
	/* host access */
	OP_LOAD_H = 0x08,  /* load.h */
	OP_STORE_H = 0x09, /* store.h */
	OP_CALL_H = 0x0A,  /* call.h */
	/* stack */
	OP_DROP = 0x0B, /* drop */
	OP_DUP = 0x0C,  /* dup */
	/* i32 arithmetic */
	OP_ADD_I32 = 0x10, /* add.i32 */
	OP_SUB_I32 = 0x11, /* sub.i32 */
	OP_MUL_I32 = 0x12, /* mul.i32 */
	OP_DIV_I32 = 0x13, /* div.i32 */
	OP_REM_I32 = 0x14, /* rem.i32 */
	OP_NEG_I32 = 0x15, /* neg.i32 */
	/* i32 comparison */
	OP_EQ_I32 = 0x18, /* eq.i32 */
	OP_NE_I32 = 0x19, /* ne.i32 */
	OP_LT_I32 = 0x1A, /* lt.i32 */
	OP_LE_I32 = 0x1B, /* le.i32 */
	OP_GT_I32 = 0x1C, /* gt.i32 */
	OP_GE_I32 = 0x1D, /* ge.i32 */
	/* bool */
	OP_NOT = 0x1E, /* not */
	/* branches and return */
	OP_JMP = 0x20,          /* jmp */
	OP_JMP_IF_FALSE = 0x21, /* jmp_if_false */
	OP_JMP_IF_TRUE = 0x22,  /* jmp_if_true */
	OP_RET = 0x23,          /* ret */
	OP_RET_V = 0x24,        /* ret_v */
	/* validity */
	OP_ELSE = 0x28,           /* else */
	OP_IS_VALID = 0x29,       /* is_valid */
	OP_IS_UNAVAILABLE = 0x2A, /* is_unavailable */
	OP_IS_INVALID = 0x2B      /* is_invalid */
};

#endif /* MCUSCRIPT_OPCODES_H */
