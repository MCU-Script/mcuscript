# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0
"""The C runtime, driven from Python.

The runtime is a separate implementation of the same specification, and
this is where the two meet: the assembler produces a container, the C
loader verifies it and the C VM runs it, and the expectations here are
written from the specification rather than from either implementation.

When the C backend lands, its output goes through the same protocol and
these become differential tests by comparison rather than by assertion.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from mcuscript.asm import assemble
from mcuscript.opcodes import Group

REPO = Path(__file__).resolve().parents[2]
RUNTIME = REPO / "runtime"
OPCODES_H = RUNTIME / "src" / "opcodes.h"
MCUSCRIPT_H = RUNTIME / "include" / "mcuscript.h"

PROFILE = ".profile 1 0.0\n"


# -- the opcode tables on both sides --------------------------------------


def test_the_c_opcode_table_matches_the_python_one():
    """One source of truth, checked rather than promised.

    The C header carries each mnemonic in a trailing comment precisely so
    this comparison is possible without generating the header — the
    runtime must stay buildable with nothing but a C compiler.
    """
    from mcuscript.opcodes import BY_NAME, GROUP_RANGES, Group

    text = OPCODES_H.read_text(encoding="utf-8")
    found = {
        mnemonic: int(code, 16)
        for code, mnemonic in re.findall(
            r"OP_[A-Z0-9_]+ = 0x([0-9A-F]{2}),?\s*/\* ([a-z0-9._]+) \*/", text
        )
    }
    assert found, "no opcode rows parsed — has the header's shape changed?"

    from mcuscript.opcodes import IMPLEMENTED_GROUPS

    implemented = {
        name: op.code for name, op in BY_NAME.items() if op.group in IMPLEMENTED_GROUPS
    }
    assert found == implemented

    # The group bits are a build-time knob an embedder sets, so they
    # live in the installed header rather than beside the opcodes.
    public = MCUSCRIPT_H.read_text(encoding="utf-8")
    for group in Group:
        macro = f"#define MCUSCRIPT_GROUP_{group.name} (1u << {group.value})"
        assert macro in public, f"the public header is missing {macro}"

    # The ranges are the second table that has to agree, and the C side
    # needs them for its own reason: §2.6 point 1 asks which group an
    # opcode is in, which is a question about the container, not the build.
    ranges = {
        (name, bound): int(value, 16)
        for name, bound, value in re.findall(
            r"#define MCUSCRIPT_RANGE_([A-Z0-9]+)_(LO|HI) 0x([0-9A-F]{2})", text
        )
    }
    assert ranges == {
        (group.name, bound): value
        for group, (lo, hi) in GROUP_RANGES.items()
        for bound, value in (("LO", lo), ("HI", hi))
    }


# -- building the runtime -------------------------------------------------


@pytest.fixture(scope="session")
def runner(tmp_path_factory) -> Path:
    if shutil.which("cmake") is None:
        pytest.skip("cmake is not installed")
    build = tmp_path_factory.mktemp("runtime")
    subprocess.run(
        ["cmake", "-S", str(RUNTIME), "-B", str(build), "-DCMAKE_BUILD_TYPE=Debug"],
        check=True,
        capture_output=True,
    )
    subprocess.run(["cmake", "--build", str(build)], check=True, capture_output=True)
    return build / "tests" / "mcuscript-run"


class Result:
    def __init__(self, process: subprocess.CompletedProcess) -> None:
        self.code = process.returncode
        self.lines = process.stdout.split()
        self.out = process.stdout
        self.writes = {
            line.split()[1]: (line.split()[2], line.split()[3])
            for line in process.stdout.splitlines()
            if line.startswith("write ")
        }
        self.result = next(
            (
                tuple(line.split()[1:])
                for line in process.stdout.splitlines()
                if line.startswith("result ")
            ),
            None,
        )
        self.fault = next(
            (
                line.split()[1]
                for line in process.stdout.splitlines()
                if line.startswith("fault ")
            ),
            None,
        )
        self.refusal = next(
            (
                line.split()[1]
                for line in process.stdout.splitlines()
                if line.startswith("refused ")
            ),
            None,
        )
        self.refusal_subject = next(
            (
                line.split()[4] if len(line.split()) > 4 else None
                for line in process.stdout.splitlines()
                if line.startswith("refused ")
            ),
            None,
        )


def run(runner: Path, tmp_path: Path, source: str, host: str, *, blob=None) -> Result:
    container = tmp_path / "program.mcs"
    container.write_bytes(blob if blob is not None else assemble(source).encode())
    host_file = tmp_path / "host.txt"
    host_file.write_text(host, encoding="utf-8")
    process = subprocess.run(
        [str(runner), str(container), str(host_file)],
        capture_output=True,
        text=True,
        check=False,
    )
    return Result(process)


# -- arithmetic and the value model ---------------------------------------


def value(runner, tmp_path, body: str, host: str = "", returns: str = "i32"):
    source = PROFILE + host_directives(host) + f".entry go -> {returns}\n" + body
    return run(runner, tmp_path, source, host)


def host_directives(host: str) -> str:
    """The same entities, expressed as assembler directives, so the
    container and the runner's host agree by construction."""
    out = []
    for line in host.splitlines():
        tokens = line.split()
        if not tokens or tokens[0].startswith("#"):
            continue
        if tokens[0] == "entity":
            dimension = ""
            if "dim" in tokens:
                dimension = f" dim {tokens[tokens.index('dim') + 1]}"
            out.append(f".entity {tokens[1]} {tokens[2]} {tokens[3]}{dimension}\n")
        else:
            types = [t for t in tokens[3:] if t in ("i32", "i64", "f32", "bool")]
            out.append(f".hostfn {tokens[1]} {tokens[2]} {' '.join(types)}\n")
    return "".join(out)


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (
            "  const.i32.s8 2\n  const.i32.s8 3\n  add.i32\n  ret_v\n",
            ("i32", "5", "valid"),
        ),
        (
            "  const.i32.s8 2\n  const.i32.s8 3\n  sub.i32\n  ret_v\n",
            ("i32", "-1", "valid"),
        ),
        (
            "  const.i32.s8 7\n  const.i32.s8 2\n  div.i32\n  ret_v\n",
            ("i32", "3", "valid"),
        ),
        (
            "  const.i32.s8 -7\n  const.i32.s8 2\n  div.i32\n  ret_v\n",
            ("i32", "-3", "valid"),
        ),
        (
            "  const.i32.s8 -7\n  const.i32.s8 2\n  rem.i32\n  ret_v\n",
            ("i32", "-1", "valid"),
        ),
        ("  const.i32.s8 5\n  neg.i32\n  ret_v\n", ("i32", "-5", "valid")),
    ],
)
def test_integer_arithmetic(runner, tmp_path, body, expected):
    assert value(runner, tmp_path, body).result == expected


def test_division_by_zero_is_a_value_not_a_fault(runner, tmp_path):
    # §5.5: a value can be handled by the script that has the context;
    # a fault can only be reported to somebody who does not.
    result = value(
        runner, tmp_path, "  const.i32.s8 1\n  const.i32.s8 0\n  div.i32\n  ret_v\n"
    )
    assert result.result[2] == "invalid"
    assert result.fault is None


def test_truncation_is_toward_zero_and_the_remainder_takes_the_dividend(
    runner, tmp_path
):
    quotient = value(
        runner, tmp_path, "  const.i32.s8 -7\n  const.i32.s8 2\n  div.i32\n  ret_v\n"
    )
    remainder = value(
        runner, tmp_path, "  const.i32.s8 -7\n  const.i32.s8 2\n  rem.i32\n  ret_v\n"
    )
    # (a/b)*b + a%b == a
    assert int(quotient.result[1]) * 2 + int(remainder.result[1]) == -7


def test_overflow_wraps(runner, tmp_path):
    source = (
        PROFILE
        + ".const big i32 2147483647\n"
        + ".entry go -> i32\n"
        + "  const.i32 big\n  const.i32.s8 1\n  add.i32\n  ret_v\n"
    )
    assert run(runner, tmp_path, source, "").result == ("i32", "-2147483648", "valid")


# -- validity -------------------------------------------------------------


HOST_TEMP = "entity read i32 temp dim 1 = 250\n"


def test_an_absent_reading_propagates_through_arithmetic(runner, tmp_path):
    result = value(
        runner,
        tmp_path,
        "  load.h temp\n  const.i32.s8 1\n  add.i32\n  ret_v\n",
        "entity read i32 temp dim 1\n",
    )
    assert result.result[2] == "unavailable"


def test_invalid_outranks_unavailable(runner, tmp_path):
    result = value(
        runner,
        tmp_path,
        "  load.h a\n  load.h b\n  add.i32\n  ret_v\n",
        "entity read i32 a dim 1 = unavailable\nentity read i32 b dim 1 = invalid\n",
    )
    assert result.result[2] == "invalid"


def test_a_branch_on_an_absent_condition_faults(runner, tmp_path):
    result = value(
        runner,
        tmp_path,
        "  load.h temp\n  const.i32.s8 1\n  gt.i32\n  jmp_if_false L\n"
        "  const.i32.s8 1\n  ret_v\nL:\n  const.i32.s8 0\n  ret_v\n",
        "entity read i32 temp dim 1\n",
    )
    assert result.fault == "absent_condition"


def test_else_supplies_a_fallback_for_both_absent_states(runner, tmp_path):
    for state in ("unavailable", "invalid"):
        result = value(
            runner,
            tmp_path,
            "  load.h temp\n  const.i32.s8 20\n  else\n  ret_v\n",
            f"entity read i32 temp dim 1 = {state}\n",
        )
        assert result.result == ("i32", "20", "valid"), state


def test_a_fallback_that_is_itself_absent_does_not_become_valid(runner, tmp_path):
    result = value(
        runner,
        tmp_path,
        "  load.h a\n  load.h b\n  else\n  ret_v\n",
        "entity read i32 a dim 1 = unavailable\nentity read i32 b dim 1 = invalid\n",
    )
    assert result.result[2] == "invalid"


def test_else_keeps_a_valid_value(runner, tmp_path):
    result = value(
        runner,
        tmp_path,
        "  load.h temp\n  const.i32.s8 20\n  else\n  ret_v\n",
        HOST_TEMP,
    )
    assert result.result == ("i32", "250", "valid")


@pytest.mark.parametrize(
    ("predicate", "state", "expected"),
    [
        ("is_valid", "= 5", "true"),
        ("is_valid", "= unavailable", "false"),
        ("is_unavailable", "= unavailable", "true"),
        ("is_unavailable", "= invalid", "false"),
        ("is_invalid", "= invalid", "true"),
        ("is_invalid", "= 5", "false"),
    ],
)
def test_the_predicates_inspect_a_state_without_propagating_it(
    runner, tmp_path, predicate, state, expected
):
    result = value(
        runner,
        tmp_path,
        f"  load.h a\n  {predicate}\n  ret_v\n",
        f"entity read i32 a dim 1 {state}\n",
        returns="bool",
    )
    # Always a valid bool: this is what makes the fault of §1.3.1
    # avoidable by a script that wants to handle absence itself.
    assert result.result == ("bool", expected, "valid")


def test_a_local_that_was_never_written_reads_as_unavailable(runner, tmp_path):
    source = (
        PROFILE + ".entry go -> i32\n  .local scratch i32\n  load.l scratch\n  ret_v\n"
    )
    assert run(runner, tmp_path, source, "").result == ("i32", "0", "unavailable")


# -- the host boundary ----------------------------------------------------


def test_a_script_reads_back_what_it_wrote(runner, tmp_path):
    # §1.6: independent of when the write becomes visible outside.
    source = (
        PROFILE
        + ".entity rw i32 memory dim 1\n"
        + ".entry go -> i32\n"
        + "  const.i32.s8 42\n  store.h memory\n  load.h memory\n  ret_v\n"
    )
    result = run(runner, tmp_path, source, "entity rw i32 memory dim 1\n")
    assert result.result == ("i32", "42", "valid")


def test_a_write_carries_the_validity_state_to_the_host(runner, tmp_path):
    source = (
        PROFILE
        + ".entity read i32 temp dim 1\n"
        + ".entity write i32 out dim 1\n"
        + ".entry go\n  load.h temp\n  store.h out\n  ret\n"
    )
    result = run(
        runner,
        tmp_path,
        source,
        "entity read i32 temp dim 1\nentity write i32 out dim 1\n",
    )
    # An embedder that dropped the state could not tell "the script
    # computed zero" from "the script knew nothing".
    assert result.writes["out"] == ("0", "unavailable")


def test_a_host_function_is_called_and_its_result_used(runner, tmp_path):
    source = (
        PROFILE
        + ".hostfn i32 reading\n"
        + ".entry go -> i32\n  call.h reading\n  const.i32.s8 1\n  add.i32\n  ret_v\n"
    )
    result = run(runner, tmp_path, source, "function i32 reading = 41\n")
    assert result.result == ("i32", "42", "valid")


def test_a_host_function_that_signals_failure_faults(runner, tmp_path):
    source = (
        PROFILE + ".hostfn i32 reading\n.entry go -> i32\n  call.h reading\n  ret_v\n"
    )
    result = run(runner, tmp_path, source, "function i32 reading = fault\n")
    assert result.fault == "host_fault"


# -- refusals -------------------------------------------------------------


def test_the_c_loader_recomputes_the_declared_stack_depth(runner, tmp_path):
    from dataclasses import replace

    container = assemble(PROFILE + ".entry go\n  const.true\n  drop\n  ret\n")
    container.functions = [replace(container.functions[0], max_stack=99)]
    result = run(runner, tmp_path, "", "", blob=container.encode())
    assert result.refusal == "stack_depth_mismatch"


def test_a_container_for_another_profile_is_refused(runner, tmp_path):
    result = run(runner, tmp_path, ".profile 2 0.0\n.entry go\n  ret\n", "")
    assert result.refusal == "profile_mismatch"


def test_a_group_this_build_does_not_implement_is_refused(runner, tmp_path):
    """Every group that has instructions is implemented now, so this is
    tested the way §2.5 actually specifies it: against the **header**.

    That is not a weaker test, it is the real one. The check exists so a
    build without float says no at load rather than meeting a float
    opcode at run time — and the thing it reads is `required_groups`,
    not the code. `loop` is reserved with no instructions at all, which
    makes it the only group a container can claim to need here."""
    from mcuscript.opcodes import Group

    container = assemble(PROFILE + ".entry go\n  ret\n")
    blob = container.encode(required_groups=Group.CORE.mask | Group.LOOP.mask)
    result = run(runner, tmp_path, "", "", blob=blob)
    assert result.refusal == "unsupported_group"
    # `where` carries the mask of the groups this build lacks — bit 5.
    assert result.out.split()[3] == "32"


# -- a build that drops a group --------------------------------------------
#
# The three tests below are the modularity claim of ADR 0002 §1.3, which
# until now was a claim: the group bits gated the *permission* and no
# `#if` read them, so narrowing the mask refused containers and saved
# nothing.


@pytest.fixture(scope="session")
def core_only_runner(tmp_path_factory) -> Path:
    """The runtime built with `core` and nothing else."""
    if shutil.which("cmake") is None:
        pytest.skip("cmake is not installed")
    build = tmp_path_factory.mktemp("core-only")
    subprocess.run(
        [
            "cmake",
            "-S",
            str(RUNTIME),
            "-B",
            str(build),
            "-DCMAKE_BUILD_TYPE=Release",
            "-DCMAKE_C_FLAGS=-Os -DMCUSCRIPT_GROUPS_IMPLEMENTED=MCUSCRIPT_GROUP_CORE",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(["cmake", "--build", str(build)], check=True, capture_output=True)
    return build / "tests" / "mcuscript-run"


@pytest.fixture(scope="session")
def optimised_runner(tmp_path_factory) -> Path:
    """The full runtime, built the same way, so sizes are comparable."""
    if shutil.which("cmake") is None:
        pytest.skip("cmake is not installed")
    build = tmp_path_factory.mktemp("optimised")
    subprocess.run(
        [
            "cmake",
            "-S",
            str(RUNTIME),
            "-B",
            str(build),
            "-DCMAKE_BUILD_TYPE=Release",
            "-DCMAKE_C_FLAGS=-Os",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(["cmake", "--build", str(build)], check=True, capture_output=True)
    return build / "tests" / "mcuscript-run"


def test_a_core_only_build_still_runs_a_core_program(core_only_runner, tmp_path):
    source = (
        PROFILE
        + ".entry go -> i32\n  const.i32.s8 20\n  const.i32.s8 22\n  add.i32\n  ret_v\n"
    )
    result = run(core_only_runner, tmp_path, source, "")
    assert result.result == ("i32", "42", "valid")


def test_a_core_only_build_refuses_a_container_needing_a_dropped_group(
    core_only_runner, tmp_path
):
    """By name, at load, before the code is looked at (§2.5)."""
    source = (
        PROFILE
        + ".const seven i64 7\n"
        + ".entry go -> i64\n  const.i64 seven\n  const.i64 seven\n  add.i64\n  ret_v\n"
    )
    result = run(core_only_runner, tmp_path, source, "")
    assert result.refusal == "unsupported_group"
    assert result.out.split()[3] == "2"  # the i64 bit, and only it


def test_dropping_the_groups_drops_their_code(core_only_runner, optimised_runner):
    """The claim is that the code goes, not just the permission.

    Strictly smaller rather than smaller by some figure: a threshold
    would be a compiler's number rather than this project's. The
    measured savings are in ADR 0004, from
    `python tools/measure_footprint.py`, which cross-compiles for the
    targets that make the number mean something.
    """
    narrowed = core_only_runner.stat().st_size
    complete = optimised_runner.stat().st_size
    assert narrowed < complete, (
        f"core-only build is {narrowed} bytes and the full build is "
        f"{complete} — narrowing the group mask removed no code"
    )


I64_NO_DIVISION = (
    "MCUSCRIPT_GROUP_CORE|MCUSCRIPT_GROUP_I64|"
    "MCUSCRIPT_GROUP_FLOAT|MCUSCRIPT_GROUP_CALL|MCUSCRIPT_GROUP_BITS"
)

#: The same set as a number. CMake puts `CMAKE_C_FLAGS` through a shell,
#: which reads `A|B` as a pipe, so the macro-name spelling cannot travel
#: that way. Computed from the Python table rather than written out, so
#: it cannot drift from it; the macro-name spelling is what
#: `test_every_group_set_compiles_clean_when_optimised` exercises, and
#: it invokes the compiler directly.
I64_NO_DIVISION_MASK = sum(
    g.mask for g in (Group.CORE, Group.I64, Group.FLOAT, Group.CALL, Group.BITS)
)


@pytest.fixture(scope="session")
def no_i64_division_runner(tmp_path_factory) -> Path:
    """Everything except `i64div` — the configuration §3.4 is for."""
    if shutil.which("cmake") is None:
        pytest.skip("cmake is not installed")
    build = tmp_path_factory.mktemp("no-i64-division")
    subprocess.run(
        [
            "cmake",
            "-S",
            str(RUNTIME),
            "-B",
            str(build),
            "-DCMAKE_BUILD_TYPE=Release",
            "-DCMAKE_C_FLAGS=-Os "
            f"-DMCUSCRIPT_GROUPS_IMPLEMENTED={I64_NO_DIVISION_MASK}u",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(["cmake", "--build", str(build)], check=True, capture_output=True)
    return build / "tests" / "mcuscript-run"


def test_dropping_i64_division_keeps_the_rest_of_i64(no_i64_division_runner, tmp_path):
    """The split is only worth having if the arithmetic survives it."""
    source = (
        PROFILE
        + ".const big i64 5000000000\n"
        + ".entry go -> i64\n  const.i64 big\n  const.i64 big\n  add.i64\n  ret_v\n"
    )
    result = run(no_i64_division_runner, tmp_path, source, "")
    assert result.result == ("i64", "10000000000", "valid")


def test_dropping_i64_division_refuses_a_container_that_divides(
    no_i64_division_runner, tmp_path
):
    """At load, by group, and not as an undefined opcode mid-stream."""
    source = (
        PROFILE
        + ".const big i64 5000000000\n"
        + ".entry go -> i64\n  const.i64 big\n  const.i64 big\n  div.i64\n  ret_v\n"
    )
    result = run(no_i64_division_runner, tmp_path, source, "")
    assert result.refusal == "unsupported_group"
    assert result.out.split()[3] == "64"  # the i64div bit, and only it


GROUP_SETS = {
    "full": "",  # the header's own default
    "core": "MCUSCRIPT_GROUP_CORE",
    "core+float": "MCUSCRIPT_GROUP_CORE|MCUSCRIPT_GROUP_FLOAT",
    "no-call": (
        "MCUSCRIPT_GROUP_CORE|MCUSCRIPT_GROUP_I64|"
        "MCUSCRIPT_GROUP_FLOAT|MCUSCRIPT_GROUP_BITS"
    ),
    "no-i64-division": I64_NO_DIVISION,
}

WARNINGS = [
    "-std=c99",
    "-Wall",
    "-Wextra",
    "-Werror",
    "-Wconversion",
    "-Wsign-conversion",
    "-Wshadow",
    "-Wstrict-prototypes",
    "-Wmissing-prototypes",
    "-Wcast-qual",
    "-Wpointer-arith",
    "-ffp-contract=off",
]


def compilers() -> list[str]:
    """Both of the ones the project claims to support, where present."""
    found = [path for name in ("gcc", "clang") if (path := shutil.which(name))]
    return found or ["cc"]


@pytest.mark.parametrize("compiler", compilers(), ids=lambda p: Path(p).name)
@pytest.mark.parametrize("groups", list(GROUP_SETS), ids=list(GROUP_SETS))
@pytest.mark.parametrize("level", ["-Os", "-O2"])
def test_every_group_set_compiles_clean_when_optimised(
    tmp_path, groups, level, compiler
):
    """Warnings are errors, and that had only ever been tried at -O0.

    The CMake test build sets no optimisation, so a device build — which
    is always optimised — was outside the policy the project states. At
    -O2 the loader did not compile. Two axes because a group set that
    only compiles at one level is a group set nobody can ship, and the
    `|` in the masks is deliberate: an unparenthesised mask arriving from
    a command line is how a guard silently asks the wrong question.
    """
    define = GROUP_SETS[groups]
    flags = [
        *WARNINGS,
        level,
        f"-I{RUNTIME / 'include'}",
        f"-I{RUNTIME / 'src'}",
    ]
    if define:
        flags.append(f"-DMCUSCRIPT_GROUPS_IMPLEMENTED={define}")
    for source in ("load.c", "vm.c", "names.c"):
        command = [compiler, *flags, "-c", str(RUNTIME / "src" / source)]
        command += ["-o", str(tmp_path / "out.o")]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        assert result.returncode == 0, (
            f"{source} at {level}, {groups}, {Path(compiler).name}:\n{result.stderr}"
        )


def test_an_import_the_host_does_not_offer_is_refused_by_name(runner, tmp_path):
    source = PROFILE + ".entity read i32 nowhere dim 1\n.entry go\n  ret\n"
    result = run(runner, tmp_path, source, "entity read i32 elsewhere dim 1\n")
    assert result.refusal == "unknown_import"
    assert result.refusal_subject == "nowhere"


def test_a_dimension_the_host_disagrees_with_is_refused(runner, tmp_path):
    # The header catches a wholesale profile change; this catches the one
    # entity that moved (§4.4).
    source = PROFILE + ".entity read i32 temp dim 1\n.entry go\n  ret\n"
    result = run(runner, tmp_path, source, "entity read i32 temp dim 9\n")
    assert result.refusal == "dimension_mismatch"


def test_writing_an_entity_the_host_declares_read_only_is_refused(runner, tmp_path):
    source = (
        PROFILE
        + ".entity rw i32 temp dim 1\n"
        + ".entry go\n  const.i32.s8 1\n  store.h temp\n  ret\n"
    )
    result = run(runner, tmp_path, source, "entity read i32 temp dim 1\n")
    assert result.refusal == "access_denied"


def test_a_flipped_bit_is_refused_before_anything_runs(runner, tmp_path):
    blob = bytearray(assemble(PROFILE + ".entry go\n  ret\n").encode())
    blob[-1] ^= 0xFF
    result = run(runner, tmp_path, "", "", blob=bytes(blob))
    assert result.refusal == "bad_checksum"


# -- refusals the call graph produces -------------------------------------
#
# The host verifier refuses these too, and by the same names — but it
# does so with Tarjan's algorithm over a worklist, and this one with a
# reachability matrix in fixed memory. Two methods over one
# specification is only worth something if both are asked.


def _handmade(functions, code: bytes, **fields) -> bytes:
    from mcuscript.container import Container
    from mcuscript.opcodes import Group

    container = Container(
        code=code,
        functions=functions,
        required_groups=Group.CORE.mask | Group.CALL.mask,
        profile_id=1,
        **fields,
    )
    return container.encode(required_groups=container.required_groups)


def test_the_c_loader_refuses_an_uncapped_cycle(runner, tmp_path):
    from mcuscript.container import Function

    blob = _handmade([Function("go", 0, max_call_depth=0)], b"\x80\x00\x23")
    result = run(runner, tmp_path, "", "", blob=blob)
    assert result.refusal == "uncapped_recursion"


def test_the_c_loader_refuses_a_cap_on_a_function_in_no_cycle(runner, tmp_path):
    from mcuscript.container import Function

    blob = _handmade([Function("go", 0, recursion_cap=5)], b"\x23")
    result = run(runner, tmp_path, "", "", blob=blob)
    assert result.refusal == "recursion_cap_mismatch"


def test_the_c_loader_refuses_a_function_no_entry_point_reaches(runner, tmp_path):
    from mcuscript.container import Function

    blob = _handmade(
        [Function("go", 0), Function("orphan", 1, invocable=False)], b"\x23\x23"
    )
    result = run(runner, tmp_path, "", "", blob=blob)
    assert result.refusal == "unreachable_code"
    assert result.refusal_subject == "orphan"


def test_the_c_loader_refuses_a_call_to_a_function_that_is_not_there(runner, tmp_path):
    from mcuscript.container import Function

    blob = _handmade([Function("go", 0)], b"\x80\x07\x23")
    result = run(runner, tmp_path, "", "", blob=blob)
    assert result.refusal == "index_out_of_range"


def test_the_c_loader_refuses_an_entry_point_with_parameters(runner, tmp_path):
    from mcuscript.container import Function
    from mcuscript.opcodes import ValType

    blob = _handmade(
        [Function("go", 0, local_types=(ValType.I32,), param_count=1)], b"\x23"
    )
    result = run(runner, tmp_path, "", "", blob=blob)
    assert result.refusal == "entry_takes_parameters"


def test_the_c_loader_refuses_two_functions_with_one_name(runner, tmp_path):
    from mcuscript.container import Function

    blob = _handmade(
        [Function("go", 0), Function("go", 1, invocable=False)], b"\x23\x23"
    )
    result = run(runner, tmp_path, "", "", blob=blob)
    # A VM addresses functions by index and would not care; a C backend
    # would emit one symbol twice (§4.3).
    assert result.refusal == "malformed_section"


def test_a_cap_deeper_than_this_build_allows_is_refused(runner, tmp_path):
    # MCUSCRIPT_MAX_CALL_DEPTH is 8 by default, and `go` plus nine
    # frames of `down` is ten. This is not a malformed container — it is
    # one this build cannot run, and the two are different refusals on
    # purpose, because the fix is a rebuild and not a recompile.
    container = assemble(
        PROFILE + ".entry go\n  call down\n  ret\n"
        ".fn down\n  .cap 9\n  call down\n  ret\n"
    )
    result = run(runner, tmp_path, "", "", blob=container.encode())
    assert result.refusal == "build_limit"
    assert result.out.split()[3] == "10"


def test_a_chain_that_needs_more_slots_than_this_build_has_is_refused(runner, tmp_path):
    # Eight frames fit; their slots do not. Seven frames of ten slots is
    # 70 against MCUSCRIPT_MAX_SLOTS of 64 — and the buffer is one for
    # the whole device, so what has to fit is the chain and not the
    # widest frame in it.
    locals_ = "".join(f"  .local s{i} i32\n" for i in range(10))
    container = assemble(
        PROFILE + ".entry go\n  call down\n  ret\n"
        ".fn down\n  .cap 7\n" + locals_ + "  call down\n  ret\n"
    )
    result = run(runner, tmp_path, "", "", blob=container.encode())
    assert result.refusal == "build_limit"
    assert result.out.split()[3] == "70"


def test_the_c_loader_recomputes_the_declared_call_depth(runner, tmp_path):
    from dataclasses import replace

    container = assemble(
        PROFILE + ".entry go\n  call helper\n  ret\n.fn helper\n  ret\n"
    )
    container.functions = [
        replace(container.functions[0], max_call_depth=4),
        container.functions[1],
    ]
    result = run(runner, tmp_path, "", "", blob=container.encode())
    assert result.refusal == "call_depth_mismatch"


# -- the specification's worked example -----------------------------------

WORKED_EXAMPLE = (
    ".profile 1 0.0\n"
    ".entity read i32 temp dim 1\n"
    ".entity write i32 fan.speed dim 2\n"
    ".entry on_temp\n"
    "  load.h temp\n  const.i32.s16 280\n  gt.i32\n  jmp_if_false L1\n"
    "  const.i32.s8 3\n  jmp end\n"
    "L1:\n  load.h temp\n  const.i32.s16 250\n  gt.i32\n  jmp_if_false L2\n"
    "  const.i32.s8 2\n  jmp end\n"
    "L2:\n  const.i32.s8 0\n"
    "end:\n  store.h fan.speed\n  ret\n"
)

WORKED_HOST = "entity read i32 temp dim 1{}\nentity write i32 fan.speed dim 2\n"


@pytest.mark.parametrize(
    ("temperature", "speed"),
    [(291, "3"), (281, "3"), (280, "2"), (262, "2"), (180, "0")],
)
def test_the_worked_example_switches_the_fan(runner, tmp_path, temperature, speed):
    result = run(
        runner, tmp_path, WORKED_EXAMPLE, WORKED_HOST.format(f" = {temperature}")
    )
    assert result.writes["fan.speed"] == (speed, "valid")


def test_the_worked_example_does_not_switch_the_fan_off_on_an_unread_sensor(
    runner, tmp_path
):
    # §3.9 says this in words; here it is, happening.
    result = run(runner, tmp_path, WORKED_EXAMPLE, WORKED_HOST.format(""))
    assert result.fault == "absent_condition"
    assert result.writes == {}
