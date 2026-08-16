# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0
"""The differential test: the two backends, on the same program.

Every program has two lowerings and must have both, and they must
produce identical results. This is where that stops being a claim.

The same container goes to the VM and to the C backend; the C is
compiled against the same host description and prints through the same
code; and the test asserts that the two outputs are **byte-identical**
— not that each matches an expected string. Writing expectations down
would test the expectations. Comparing the backends tests the promise.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from mcuscript.asm import assemble
from mcuscript.cbackend import generate, mangle, symbols
from mcuscript.container import ImportKind
from mcuscript.opcodes import ValType

REPO = Path(__file__).resolve().parents[2]
RUNTIME = REPO / "runtime"

PROFILE = ".profile 1 0.0\n"


@dataclass(frozen=True)
class Run:
    output: str
    code: int


@pytest.fixture(scope="session")
def vm(tmp_path_factory) -> Path:
    if shutil.which("cmake") is None:
        pytest.skip("cmake is not installed")
    build = tmp_path_factory.mktemp("vm")
    subprocess.run(
        ["cmake", "-S", str(RUNTIME), "-B", str(build), "-DCMAKE_BUILD_TYPE=Debug"],
        check=True,
        capture_output=True,
    )
    subprocess.run(["cmake", "--build", str(build)], check=True, capture_output=True)
    return build / "tests" / "mcuscript-run"


@pytest.fixture(scope="session")
def cc() -> str:
    for candidate in ("cc", "gcc", "clang"):
        found = shutil.which(candidate)
        if found:
            return found
    pytest.skip("no C compiler")


def _shim(container, entry_name: str) -> str:
    """The extern functions the generated code expects, onto the same
    world the VM runner uses, plus a `main` that prints the same lines.

    The generated program needs no runtime; this needs the name strings
    and the host file, and nothing else."""
    names = symbols(container)
    entry_symbol = dict(names.entries)[entry_name]
    returns = next(f.return_type for f in container.functions if f.name == entry_name)
    kind = {
        ValType.VOID: "MCUSCRIPT_VOID",
        ValType.I32: "MCUSCRIPT_I32",
        ValType.BOOL: "MCUSCRIPT_BOOL",
    }[returns]

    lines = [
        "/* Test scaffolding, generated per container. */",
        '#include "hostfile.h"',
        '#include "mcuscript.h"',
        "",
    ]
    for imp in container.imports:
        symbol = mangle(imp.name)
        if imp.kind == ImportKind.FUNCTION:
            lines += [
                f"bool mcuscript_call__{symbol}(const mcuscript_value *arguments,",
                f"{' ' * (len(symbol) + 22)}mcuscript_value *result)",
                "{",
                f'\treturn hostfile_call_by_name("{imp.name}", arguments, result);',
                "}",
            ]
            continue
        if imp.access & 0x01:
            lines += [
                f"mcuscript_value mcuscript_read__{symbol}(void)",
                "{",
                f'\treturn hostfile_read_by_name("{imp.name}");',
                "}",
            ]
        if imp.access & 0x02:
            lines += [
                f"void mcuscript_write__{symbol}(mcuscript_value value)",
                "{",
                f'\thostfile_write_by_name("{imp.name}", value);',
                "}",
            ]
    lines += [
        "",
        f"extern bool {entry_symbol}(mcuscript_value *result, mcuscript_fault *fault);",
        "",
        "int main(int argc, char **argv)",
        "{",
        "\tif (argc < 2 || !hostfile_load(argv[1]))",
        "\t\treturn 2;",
        "\tmcuscript_value result = mcuscript_absent(MCUSCRIPT_UNAVAILABLE);",
        "\tmcuscript_fault fault = MCUSCRIPT_NO_FAULT;",
        f"\tif (!{entry_symbol}(&result, &fault)) {{",
        "\t\thostfile_print_fault(fault);",
        "\t\treturn 3;",
        "\t}",
        f"\thostfile_print_result({kind}, result);",
        "\thostfile_print_done();",
        "\treturn 0;",
        "}",
    ]
    return "\n".join(lines) + "\n"


def both(vm: Path, cc: str, tmp_path: Path, source: str, host: str) -> tuple[Run, Run]:
    container = assemble(source)
    entry = next(f.name for f in container.functions if f.invocable)

    blob = tmp_path / "program.mcs"
    blob.write_bytes(container.encode())
    host_file = tmp_path / "host.txt"
    host_file.write_text(host, encoding="utf-8")

    interpreted = subprocess.run(
        [str(vm), str(blob), str(host_file)],
        capture_output=True,
        text=True,
        check=False,
    )

    (tmp_path / "program.c").write_text(generate(container), encoding="utf-8")
    (tmp_path / "shim.c").write_text(_shim(container, entry), encoding="utf-8")
    binary = tmp_path / "compiled"
    build = subprocess.run(
        [
            cc,
            "-std=c99",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            f"-I{RUNTIME / 'include'}",
            f"-I{RUNTIME / 'tests'}",
            str(tmp_path / "program.c"),
            str(tmp_path / "shim.c"),
            str(RUNTIME / "tests" / "hostfile.c"),
            str(RUNTIME / "src" / "names.c"),
            "-o",
            str(binary),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert build.returncode == 0, (
        build.stderr + "\n" + (tmp_path / "program.c").read_text()
    )
    compiled = subprocess.run(
        [str(binary), str(host_file)], capture_output=True, text=True, check=False
    )
    return (
        Run(interpreted.stdout, interpreted.returncode),
        Run(compiled.stdout, compiled.returncode),
    )


def agree(vm, cc, tmp_path, source: str, host: str = "") -> Run:
    interpreted, compiled = both(vm, cc, tmp_path, source, host)
    assert interpreted.output == compiled.output, (
        f"the backends disagree\n"
        f"  interpreted: {interpreted.output!r}\n"
        f"  compiled:    {compiled.output!r}"
    )
    assert interpreted.code == compiled.code
    return interpreted


# -- arithmetic -----------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        "  const.i32.s8 2\n  const.i32.s8 3\n  add.i32\n  ret_v\n",
        "  const.i32.s8 2\n  const.i32.s8 3\n  sub.i32\n  ret_v\n",
        "  const.i32.s8 -7\n  const.i32.s8 2\n  div.i32\n  ret_v\n",
        "  const.i32.s8 -7\n  const.i32.s8 2\n  rem.i32\n  ret_v\n",
        "  const.i32.s8 7\n  const.i32.s8 0\n  div.i32\n  ret_v\n",
        "  const.i32.s8 7\n  const.i32.s8 0\n  rem.i32\n  ret_v\n",
        "  const.i32.s8 100\n  const.i32.s8 100\n  mul.i32\n  ret_v\n",
        "  const.i32.s8 5\n  neg.i32\n  ret_v\n",
        "  const.i32.s8 5\n  dup\n  mul.i32\n  ret_v\n",
    ],
)
def test_arithmetic_agrees(vm, cc, tmp_path, body):
    agree(vm, cc, tmp_path, PROFILE + ".entry go -> i32\n" + body)


@pytest.mark.parametrize("value", ["2147483647", "-2147483648"])
def test_the_extremes_agree(vm, cc, tmp_path, value):
    """`INT32_MIN` is the one that catches a lazy backend twice over: it
    has no negative literal in C, and dividing it by -1 is the case §1.5
    calls `invalid`."""
    source = (
        PROFILE
        + f".const edge i32 {value}\n"
        + ".entry go -> i32\n"
        + "  const.i32 edge\n  const.i32.s8 -1\n  div.i32\n  ret_v\n"
    )
    agree(vm, cc, tmp_path, source)


def test_wrapping_agrees(vm, cc, tmp_path):
    source = (
        PROFILE
        + ".const big i32 2147483647\n"
        + ".entry go -> i32\n"
        + "  const.i32 big\n  const.i32.s8 1\n  add.i32\n  ret_v\n"
    )
    result = agree(vm, cc, tmp_path, source)
    assert "-2147483648" in result.output


@pytest.mark.parametrize(
    "comparison", ["eq.i32", "ne.i32", "lt.i32", "le.i32", "gt.i32", "ge.i32"]
)
@pytest.mark.parametrize(("a", "b"), [(1, 2), (2, 2), (3, 2), (-1, 1)])
def test_every_comparison_agrees(vm, cc, tmp_path, comparison, a, b):
    source = (
        PROFILE
        + ".entry go -> bool\n"
        + f"  const.i32.s8 {a}\n  const.i32.s8 {b}\n  {comparison}\n  ret_v\n"
    )
    agree(vm, cc, tmp_path, source)


def test_not_agrees(vm, cc, tmp_path):
    agree(
        vm, cc, tmp_path, PROFILE + ".entry go -> bool\n  const.true\n  not\n  ret_v\n"
    )


# -- validity -------------------------------------------------------------


ABSENT_HOST = "entity read i32 a dim 1 {}\nentity read i32 b dim 1 {}\n"


@pytest.mark.parametrize("a", ["= 5", "= unavailable", "= invalid"])
@pytest.mark.parametrize("b", ["= 7", "= unavailable", "= invalid"])
def test_validity_propagation_agrees(vm, cc, tmp_path, a, b):
    source = (
        PROFILE
        + ".entity read i32 a dim 1\n.entity read i32 b dim 1\n"
        + ".entry go -> i32\n  load.h a\n  load.h b\n  add.i32\n  ret_v\n"
    )
    agree(vm, cc, tmp_path, source, ABSENT_HOST.format(a, b))


@pytest.mark.parametrize("a", ["= 5", "= unavailable", "= invalid"])
@pytest.mark.parametrize("b", ["= 7", "= unavailable", "= invalid"])
def test_else_agrees(vm, cc, tmp_path, a, b):
    source = (
        PROFILE
        + ".entity read i32 a dim 1\n.entity read i32 b dim 1\n"
        + ".entry go -> i32\n  load.h a\n  load.h b\n  else\n  ret_v\n"
    )
    agree(vm, cc, tmp_path, source, ABSENT_HOST.format(a, b))


@pytest.mark.parametrize("predicate", ["is_valid", "is_unavailable", "is_invalid"])
@pytest.mark.parametrize("state", ["= 5", "= unavailable", "= invalid"])
def test_the_predicates_agree(vm, cc, tmp_path, predicate, state):
    source = (
        PROFILE
        + ".entity read i32 a dim 1\n"
        + f".entry go -> bool\n  load.h a\n  {predicate}\n  ret_v\n"
    )
    agree(vm, cc, tmp_path, source, f"entity read i32 a dim 1 {state}\n")


def test_a_fault_agrees_including_the_exit_code(vm, cc, tmp_path):
    source = (
        PROFILE
        + ".entity read i32 a dim 1\n"
        + ".entry go -> i32\n"
        + "  load.h a\n  const.i32.s8 1\n  gt.i32\n  jmp_if_false L\n"
        + "  const.i32.s8 1\n  ret_v\nL:\n  const.i32.s8 0\n  ret_v\n"
    )
    result = agree(vm, cc, tmp_path, source, "entity read i32 a dim 1\n")
    assert result.output == "fault absent_condition\n"
    assert result.code == 3


def test_an_unwritten_local_agrees(vm, cc, tmp_path):
    agree(
        vm,
        cc,
        tmp_path,
        PROFILE + ".entry go -> i32\n  .local scratch i32\n  load.l scratch\n  ret_v\n",
    )


def test_locals_round_trip_the_same_way(vm, cc, tmp_path):
    source = (
        PROFILE
        + ".entity read i32 a dim 1\n"
        + ".entry go -> i32\n"
        + "  .local held i32\n"
        + "  load.h a\n  store.l held\n"
        + "  load.l held\n  load.l held\n  add.i32\n  ret_v\n"
    )
    for state in ("= 21", "= unavailable", "= invalid"):
        agree(vm, cc, tmp_path, source, f"entity read i32 a dim 1 {state}\n")


# -- the host boundary ----------------------------------------------------


def test_writes_agree_in_content_and_order(vm, cc, tmp_path):
    source = (
        PROFILE
        + ".entity read i32 a dim 1\n"
        + ".entity write i32 first dim 2\n"
        + ".entity write i32 second dim 2\n"
        + ".entry go\n"
        + "  load.h a\n  store.h first\n"
        + "  const.i32.s8 7\n  store.h second\n  ret\n"
    )
    result = agree(
        vm,
        cc,
        tmp_path,
        source,
        "entity read i32 a dim 1 = invalid\n"
        "entity write i32 first dim 2\nentity write i32 second dim 2\n",
    )
    assert result.output.splitlines()[0].startswith("write first")
    assert result.output.splitlines()[1].startswith("write second")


def test_reading_back_a_write_agrees(vm, cc, tmp_path):
    source = (
        PROFILE
        + ".entity rw i32 memory dim 1\n"
        + ".entry go -> i32\n"
        + "  const.i32.s8 42\n  store.h memory\n  load.h memory\n  ret_v\n"
    )
    agree(vm, cc, tmp_path, source, "entity rw i32 memory dim 1\n")


def test_a_host_call_agrees(vm, cc, tmp_path):
    source = (
        PROFILE
        + ".hostfn i32 reading i32\n"
        + ".entry go -> i32\n  const.i32.s8 3\n  call.h reading\n  ret_v\n"
    )
    agree(vm, cc, tmp_path, source, "function i32 reading i32 = 41\n")


def test_a_host_fault_agrees(vm, cc, tmp_path):
    source = (
        PROFILE + ".hostfn i32 reading\n.entry go -> i32\n  call.h reading\n  ret_v\n"
    )
    result = agree(vm, cc, tmp_path, source, "function i32 reading = fault\n")
    assert result.output == "fault host_fault\n"


# -- control flow ---------------------------------------------------------

WORKED_EXAMPLE = (
    PROFILE
    + ".entity read i32 temp dim 1\n"
    + ".entity write i32 fan.speed dim 2\n"
    + ".entry on_temp\n"
    + "  load.h temp\n  const.i32.s16 280\n  gt.i32\n  jmp_if_false L1\n"
    + "  const.i32.s8 3\n  jmp end\n"
    + "L1:\n  load.h temp\n  const.i32.s16 250\n  gt.i32\n  jmp_if_false L2\n"
    + "  const.i32.s8 2\n  jmp end\n"
    + "L2:\n  const.i32.s8 0\n"
    + "end:\n  store.h fan.speed\n  ret\n"
)


@pytest.mark.parametrize("temperature", ["= 291", "= 280", "= 250", "= 100", ""])
def test_the_worked_example_agrees_on_every_arm(vm, cc, tmp_path, temperature):
    agree(
        vm,
        cc,
        tmp_path,
        WORKED_EXAMPLE,
        f"entity read i32 temp dim 1 {temperature}\nentity write i32 fan.speed dim 2\n",
    )


def test_a_join_after_two_arms_agrees(vm, cc, tmp_path):
    source = (
        PROFILE
        + ".entity read i32 a dim 1\n"
        + ".entry go -> i32\n"
        + "  load.h a\n  const.i32.s8 0\n  gt.i32\n  jmp_if_true positive\n"
        + "  const.i32.s8 -1\n  jmp join\n"
        + "positive:\n  const.i32.s8 1\n"
        + "join:\n  const.i32.s8 10\n  mul.i32\n  ret_v\n"
    )
    for state in ("= 5", "= -5", "= 0"):
        agree(vm, cc, tmp_path, source, f"entity read i32 a dim 1 {state}\n")


# -- the generated source itself -------------------------------------------


def test_the_generated_c_states_its_own_floating_point_requirement():
    """§1.5: `a*b + c` contracts to a fused multiply-add under
    `-std=gnu11` and not under `-std=c11`, on the same compiler. The
    generated translation unit says so itself rather than trusting the
    build."""
    text = generate(assemble(PROFILE + ".entry go\n  ret\n"))
    assert "#pragma STDC FP_CONTRACT OFF" in text


def test_a_name_collision_is_refused_rather_than_emitted():
    from mcuscript.cbackend import UnsupportedProgram

    container = assemble(
        PROFILE
        + ".entity read i32 fan.speed dim 1\n"
        + ".entity read i32 fan_speed dim 1\n"
        + ".entry go\n  ret\n"
    )
    with pytest.raises(UnsupportedProgram, match="mangle"):
        generate(container)
