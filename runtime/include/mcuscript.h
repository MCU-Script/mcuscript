/*
 * SPDX-FileCopyrightText: 2026 The MCUScript Contributors
 * SPDX-License-Identifier: Apache-2.0
 *
 * The MCUScript runtime: the interface an embedder implements, and the
 * three things it can do — load a container, find an entry point, and
 * invoke one.
 *
 * The runtime never allocates. Every buffer it uses is one the embedder
 * passed in or one this header sized at compile time, because a device
 * that cannot allocate is the case this language exists for, and a
 * runtime with a malloc in it is a runtime that only works on the
 * machine it was tested on.
 */

#ifndef MCUSCRIPT_H
#define MCUSCRIPT_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ------------------------------------------------------------------
 * Build-time limits
 *
 * These size the fixed arrays below, so raising one costs RAM on every
 * device in the build. They are deliberately small: the programs this
 * language is for are formulas and threshold ladders, and a build that
 * needs more should say so rather than discover it.
 */

#ifndef MCUSCRIPT_MAX_IMPORTS
#define MCUSCRIPT_MAX_IMPORTS 32
#endif

#ifndef MCUSCRIPT_MAX_FUNCTIONS
#define MCUSCRIPT_MAX_FUNCTIONS 8
#endif

#ifndef MCUSCRIPT_MAX_CONSTANTS
#define MCUSCRIPT_MAX_CONSTANTS 32
#endif

/* Parameters a host function may take. */
#ifndef MCUSCRIPT_MAX_PARAMETERS
#define MCUSCRIPT_MAX_PARAMETERS 4
#endif

/* Slots for one invocation: every live frame's locals and operand
 * stack, summed along the deepest call chain (spec §5.3). One buffer
 * serves the whole device, because scripts run to completion and never
 * nest (spec §5.1). The loader computes what a container needs and
 * refuses one that needs more than this. */
#ifndef MCUSCRIPT_MAX_SLOTS
#define MCUSCRIPT_MAX_SLOTS 64
#endif

/* Frames live at once. This costs C stack during an invocation — the
 * return addresses the VM keeps — and nothing else. */
#ifndef MCUSCRIPT_MAX_CALL_DEPTH
#define MCUSCRIPT_MAX_CALL_DEPTH 8
#endif

/* Deepest operand stack the verifier will track. */
#ifndef MCUSCRIPT_MAX_STACK
#define MCUSCRIPT_MAX_STACK 32
#endif

/* Forward branches outstanding at once during verification. Transient:
 * this costs C stack during load and nothing afterwards. */
#ifndef MCUSCRIPT_MAX_PENDING_BRANCHES
#define MCUSCRIPT_MAX_PENDING_BRANCHES 8
#endif

/* ------------------------------------------------------------------
 * Instruction groups
 *
 * The bits of a container's `required_groups` (spec §2.5), and what
 * this build implements. Narrowing the mask removes the code as well
 * as the permission: the group's cases are not compiled, and a
 * container that needs the group is refused at load, by name, before
 * anything runs.
 *
 * Set it from the build system — `-DMCUSCRIPT_GROUPS_IMPLEMENTED=...`
 * — and the loader and the interpreter follow it together, because
 * both read this one macro.
 */
#define MCUSCRIPT_GROUP_CORE (1u << 0)
#define MCUSCRIPT_GROUP_I64 (1u << 1)
#define MCUSCRIPT_GROUP_FLOAT (1u << 2)
#define MCUSCRIPT_GROUP_CALL (1u << 3)
#define MCUSCRIPT_GROUP_BITS (1u << 4)
#define MCUSCRIPT_GROUP_LOOP (1u << 5)
#define MCUSCRIPT_GROUP_I64DIV (1u << 6)

#ifndef MCUSCRIPT_GROUPS_IMPLEMENTED
#define MCUSCRIPT_GROUPS_IMPLEMENTED                                          \
	(MCUSCRIPT_GROUP_CORE | MCUSCRIPT_GROUP_I64 | MCUSCRIPT_GROUP_FLOAT | \
	 MCUSCRIPT_GROUP_CALL | MCUSCRIPT_GROUP_BITS |                        \
	 MCUSCRIPT_GROUP_I64DIV)
#endif

/*
 * Use this, never the macro above. A mask arrives from a command line
 * as `-DMCUSCRIPT_GROUPS_IMPLEMENTED=A|B`, without parentheses, and `&`
 * binds tighter than `|` — so `MCUSCRIPT_GROUPS_IMPLEMENTED & BIT`
 * silently asks about the last group in the list rather than about the
 * set. Parenthesising once here is what keeps every other site right.
 */
#define MCUSCRIPT_GROUPS ((MCUSCRIPT_GROUPS_IMPLEMENTED))

#if !(MCUSCRIPT_GROUPS & MCUSCRIPT_GROUP_CORE)
#error "core is mandatory: a build without it implements no instruction"
#endif

/* `loop` is reserved and has no opcodes yet (spec §3.8). Claiming it
 * would accept a container this build cannot possibly run. */
#if MCUSCRIPT_GROUPS & MCUSCRIPT_GROUP_LOOP
#error "loop is reserved and empty: no build implements it"
#endif

/* `i64div` divides values only `i64` can put on the stack, so claiming
 * it alone accepts containers that cannot exist. Dropping `i64` drops
 * its division with it; dropping only the division is the useful half
 * of the choice, and the one worth its own group (§3.4). */
#if (MCUSCRIPT_GROUPS & MCUSCRIPT_GROUP_I64DIV) && \
	!(MCUSCRIPT_GROUPS & MCUSCRIPT_GROUP_I64)
#error "i64div needs i64: no instruction could produce its operands"
#endif

/* ------------------------------------------------------------------
 * Values
 */

typedef enum {
	MCUSCRIPT_VALID = 0,
	MCUSCRIPT_UNAVAILABLE = 1,
	MCUSCRIPT_INVALID = 2
} mcuscript_validity;

typedef enum {
	MCUSCRIPT_VOID = 0x00,
	MCUSCRIPT_I32 = 0x01,
	MCUSCRIPT_I64 = 0x02,
	MCUSCRIPT_F32 = 0x03,
	MCUSCRIPT_BOOL = 0x04
} mcuscript_type;

/*
 * A value as it crosses the host boundary: the number, and the state
 * that travels beside it. Inside the VM the two live in separate arrays
 * (spec §1.3) — here they are one struct because an interface should be
 * convenient, and because the state must not be droppable by accident.
 * An embedder that loses it cannot tell "the script computed zero" from
 * "the script knew nothing".
 */
typedef struct {
	union {
		int32_t i32;
		int64_t i64;
		float f32;
		bool boolean;
	} as;
	uint8_t validity;
} mcuscript_value;

static inline mcuscript_value mcuscript_i32(int32_t value)
{
	mcuscript_value out = { .as = { .i32 = value }, .validity = MCUSCRIPT_VALID };
	return out;
}

static inline mcuscript_value mcuscript_bool(bool value)
{
	mcuscript_value out = { .as = { .boolean = value }, .validity = MCUSCRIPT_VALID };
	return out;
}

static inline mcuscript_value mcuscript_absent(mcuscript_validity state)
{
	mcuscript_value out = { .as = { .i64 = 0 }, .validity = (uint8_t)state };
	return out;
}

/* ------------------------------------------------------------------
 * Refusals and faults
 *
 * A refusal happens at load and names what was wrong (spec §4.6). A
 * fault happens during execution and there are three (spec §5.5).
 */

typedef enum {
	MCUSCRIPT_OK = 0,

	MCUSCRIPT_BAD_MAGIC,
	MCUSCRIPT_UNSUPPORTED_FORMAT_VERSION,
	MCUSCRIPT_LENGTH_MISMATCH,
	MCUSCRIPT_BAD_CHECKSUM,
	MCUSCRIPT_MALFORMED_SECTION,
	MCUSCRIPT_UNKNOWN_CRITICAL_SECTION,
	MCUSCRIPT_MISSING_SECTION,
	MCUSCRIPT_DUPLICATE_SECTION,
	MCUSCRIPT_RESERVED_FIELD_SET,
	MCUSCRIPT_ENTRY_TAKES_PARAMETERS,

	MCUSCRIPT_PROFILE_MISMATCH,
	MCUSCRIPT_UNSUPPORTED_GROUP,

	MCUSCRIPT_UNDEFINED_OPCODE,
	MCUSCRIPT_TRUNCATED_INSTRUCTION,
	MCUSCRIPT_BAD_BRANCH_TARGET,
	MCUSCRIPT_BACKWARD_BRANCH,
	MCUSCRIPT_UNREACHABLE_CODE,
	MCUSCRIPT_TYPE_MISMATCH,
	MCUSCRIPT_STACK_UNDERFLOW,
	MCUSCRIPT_INCONSISTENT_JOIN,
	MCUSCRIPT_UNBALANCED_RETURN,
	MCUSCRIPT_STACK_DEPTH_MISMATCH,
	MCUSCRIPT_CALL_DEPTH_MISMATCH,
	MCUSCRIPT_UNCAPPED_RECURSION,
	MCUSCRIPT_RECURSION_CAP_MISMATCH,
	MCUSCRIPT_INDEX_OUT_OF_RANGE,

	MCUSCRIPT_UNKNOWN_IMPORT,
	MCUSCRIPT_KIND_MISMATCH,
	MCUSCRIPT_IMPORT_TYPE_MISMATCH,
	MCUSCRIPT_DIMENSION_MISMATCH,
	MCUSCRIPT_ACCESS_DENIED,
	MCUSCRIPT_SIGNATURE_MISMATCH,
	MCUSCRIPT_DUPLICATE_IMPORT,

	/* Not a refusal the specification names: this build's compile-time
	 * limits are too small for the container. It is separate on purpose
	 * — the container is not at fault and the fix is a rebuild. */
	MCUSCRIPT_BUILD_LIMIT
} mcuscript_refusal;

typedef enum {
	MCUSCRIPT_NO_FAULT = 0,
	MCUSCRIPT_ABSENT_CONDITION,
	MCUSCRIPT_RECURSION_LIMIT,
	MCUSCRIPT_HOST_FAULT
} mcuscript_fault;

/* A name inside a container: not NUL-terminated, because the container
 * stores names length-prefixed and copying them would need a buffer. */
typedef struct {
	const char *bytes;
	uint8_t length;
} mcuscript_str;

/*
 * Where a refusal happened. `where` is an offset into CODE for a
 * verification refusal and a table index otherwise; `name` is filled in
 * when the refusal is about something named. A loader that can only say
 * "invalid" is not one anybody can debug against.
 */
typedef struct {
	mcuscript_refusal refusal;
	uint32_t where;
	mcuscript_str name;
} mcuscript_diagnostic;

const char *mcuscript_refusal_name(mcuscript_refusal refusal);
const char *mcuscript_fault_name(mcuscript_fault fault);

/* ------------------------------------------------------------------
 * The host
 */

#define MCUSCRIPT_KIND_ENTITY 0x01
#define MCUSCRIPT_KIND_FUNCTION 0x02

#define MCUSCRIPT_ACCESS_NONE 0x00
#define MCUSCRIPT_ACCESS_READ 0x01
#define MCUSCRIPT_ACCESS_WRITE 0x02
#define MCUSCRIPT_ACCESS_BOTH 0x03

/* One thing a script may reach: an entity it reads or writes, or a
 * function it calls. The embedder declares these; the loader resolves
 * the container's names against them once, at load, and nothing looks
 * at a name again. */
typedef struct {
	const char *name; /* NUL-terminated; the embedder owns it */
	uint8_t kind;
	uint8_t access;
	uint8_t type;
	uint16_t dimension;
	uint8_t parameter_count;
	const uint8_t *parameter_types;
} mcuscript_import;

typedef struct {
	const mcuscript_import *imports;
	uint8_t import_count;

	/* `index` is an index into `imports`, not into the container. */
	mcuscript_value (*read)(void *context, uint8_t index);
	void (*write)(void *context, uint8_t index, mcuscript_value value);
	/* Returns false to raise `host_fault`. */
	bool (*invoke)(void *context, uint8_t index,
		       const mcuscript_value *arguments, mcuscript_value *result);

	void *context;
} mcuscript_host;

/* ------------------------------------------------------------------
 * A loaded program
 *
 * The fields are public so an embedder can inspect what it loaded; they
 * are filled in by mcuscript_load and must not be written afterwards.
 * The struct points into the container, which must outlive it — the
 * runtime copies nothing.
 */

/* Flag bit 0 of an ENTR record: the host may invoke this by name. A
 * function without it is reachable only from other code in the same
 * container. */
#define MCUSCRIPT_ENTRY_INVOCABLE 0x01

/*
 * What running a function needs, and nothing else. `max_stack`,
 * `max_call_depth` and `local_types` are in the record and are not
 * here: they exist for a verifier to recompute (spec §2.6), and this
 * runtime does not verify — it reads past them. A conforming container
 * is one whose deepest call chain fits `MCUSCRIPT_MAX_SLOTS`, and that
 * is a property of the container rather than a number this struct
 * carries.
 */
typedef struct {
	mcuscript_str name;
	uint32_t code_offset;
	uint8_t flags;
	uint8_t return_type;
	uint8_t recursion_cap;
	/* Arguments the caller pushes; they are the first locals (§3.6). */
	uint8_t param_count;
	uint8_t local_count;
} mcuscript_function;

typedef struct {
	const uint8_t *code;
	uint32_t code_length;
	uint32_t required_groups;

	/* The tables stay in the container and are read through offset
	 * tables rather than copied out. On a device the container is in
	 * flash and a decoded copy would be RAM spent to save a shift. */
	const uint8_t *constants;
	uint16_t constant_offsets[MCUSCRIPT_MAX_CONSTANTS];
	uint8_t constant_count;

	const uint8_t *imports;
	uint16_t import_offsets[MCUSCRIPT_MAX_IMPORTS];
	uint8_t import_count;
	/* The string area after the records. Kept because finding it means
	 * walking every record, and linking needs it once per import. */
	const uint8_t *import_names;
	uint32_t import_names_length;
	/* container import index -> host import index, resolved at load */
	uint8_t import_map[MCUSCRIPT_MAX_IMPORTS];

	mcuscript_function functions[MCUSCRIPT_MAX_FUNCTIONS];
	uint8_t function_count;

	/* The call graph's condensation, read from the records rather than
	 * computed (§4.3). Two functions share a recursion counter exactly
	 * when they share a component (§5.4). A component is named by its
	 * lowest member, so the id is already a bounded index and
	 * `component_cap` is addressed by it; the cap is zero for a
	 * component that is not a cycle. */
	uint8_t component[MCUSCRIPT_MAX_FUNCTIONS];
	uint8_t component_cap[MCUSCRIPT_MAX_FUNCTIONS];

	const mcuscript_host *host;
} mcuscript_program;

/* The slots one invocation runs on: locals first, then the operand
 * stack. Values and their validity states live in separate arrays
 * (spec §1.3) so propagation is one `max` over two bytes and never a
 * branch. */
typedef struct {
	uint64_t values[MCUSCRIPT_MAX_SLOTS];
	uint8_t states[MCUSCRIPT_MAX_SLOTS];
} mcuscript_slots;

/* ------------------------------------------------------------------
 * The three operations
 */

/*
 * Parse and link a container.
 *
 * **This does not verify.** It establishes that the container is meant
 * for this build — magic, format version, profile pin, instruction
 * groups, checksum — and resolves the imports against `host`. It does
 * not establish that the container is *conforming* (spec §2.6), and
 * behaviour on a container that is not is undefined.
 *
 * That is the language's contract and not a shortcut: a program is
 * equally expressible as this container or as C compiled into the
 * firmware, nothing protects the C on its way to a device, and a
 * guarantee only one of the two paths can carry would be read as one
 * the language makes. If containers reach this function from somewhere
 * untrusted, verify them first or authenticate the path — see
 * `spec/02-container.md` §2.6.0 and ADR 0006.
 *
 * `bytes` must stay valid and unchanged for as long as `program` is
 * used. Returns true on success; on failure `diagnostic` says which
 * refusal and where.
 */
bool mcuscript_load(mcuscript_program *program, const uint8_t *bytes, size_t length,
		    const mcuscript_host *host, uint32_t profile_id,
		    uint16_t profile_major, mcuscript_diagnostic *diagnostic);

/* The index of a host-invocable entry point, or -1. */
int mcuscript_find_entry(const mcuscript_program *program, const char *name);

/*
 * Run one entry point to completion. `result` may be NULL for an entry
 * point that returns nothing. Returns true when the invocation
 * finished; false when it faulted, with `fault` saying which.
 */
bool mcuscript_invoke(const mcuscript_program *program, int entry,
		      mcuscript_slots *slots, mcuscript_value *result,
		      mcuscript_fault *fault);

#ifdef __cplusplus
}
#endif

#endif /* MCUSCRIPT_H */
