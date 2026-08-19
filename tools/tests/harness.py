# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0
"""The harness the differential tests run on.

Every program has two lowerings and must have both, and they must
produce identical results. This is where that stops being a claim.

The same container goes to the VM and to the C backend; the C is
compiled against the same host description and prints through the same
code; and the test asserts that the two outputs are **byte-identical**
— not that each matches an expected string. Writing expectations down
would test the expectations. Comparing the backends tests the promise.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from mcuscript.asm import assemble
from mcuscript.cbackend import generate, mangle, symbols
from mcuscript.container import Container, ImportKind
from mcuscript.opcodes import ValType

REPO = Path(__file__).resolve().parents[2]
RUNTIME = REPO / "runtime"

PROFILE = ".profile 1 0.0\n"


@dataclass(frozen=True)
class Run:
    output: str
    code: int


def _shim(container, entry_name: str, repeat: int = 1) -> str:
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
        ValType.I64: "MCUSCRIPT_I64",
        ValType.F32: "MCUSCRIPT_F32",
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
        "\tint code = 0;",
        f"\tfor (int round = 0; round < {repeat}; round++) {{",
        "\t\tmcuscript_value result = mcuscript_absent(MCUSCRIPT_UNAVAILABLE);",
        "\t\tmcuscript_fault fault = MCUSCRIPT_NO_FAULT;",
        f"\t\tif (!{entry_symbol}(&result, &fault)) {{",
        "\t\t\thostfile_print_fault(fault);",
        "\t\t\tcode = 3;",
        "\t\t\tcontinue;",
        "\t\t}",
        f"\t\thostfile_print_result({kind}, result);",
        "\t\thostfile_print_done();",
        "\t\tcode = 0;",
        "\t}",
        "\treturn code;",
        "}",
    ]
    return "\n".join(lines) + "\n"


#: What a conforming build passes. Measured, not assumed: with
#: -ffp-contract=fast (GCC's default under -std=gnu*) and FMA hardware,
#: the two backends disagree — see test_the_required_build_flags_are_not
#: _decoration in test_float_agreement.py.
CONFORMING_FLAGS = ["-std=c99", "-O2", "-ffp-contract=off"]


class Compiled:
    """A container lowered, compiled once, runnable many times.

    Compiling per test case cost seven minutes for the float matrix.
    The container is fixed and only the host file varies, so the binary
    is built once and fed a different world each time.
    """

    def __init__(self, binary: Path, blob: Path, vm: Path, workdir: Path) -> None:
        self.binary = binary
        self.blob = blob
        self.vm = vm
        self.workdir = workdir
        self.round = 0

    def _host_file(self, host: str) -> Path:
        self.round += 1
        path = self.workdir / f"host{self.round}.txt"
        path.write_text(host, encoding="utf-8")
        return path

    def __call__(self, host: str) -> tuple[Run, Run]:
        host_file = self._host_file(host)
        interpreted = subprocess.run(
            [str(self.vm), str(self.blob), str(host_file)],
            capture_output=True,
            text=True,
            check=False,
        )
        compiled = subprocess.run(
            [str(self.binary), str(host_file)],
            capture_output=True,
            text=True,
            check=False,
        )
        return (
            Run(interpreted.stdout, interpreted.returncode),
            Run(compiled.stdout, compiled.returncode),
        )

    def agree(self, host: str = "") -> Run:
        return _same(*self(host))

    def compiled_only(self, host: str = "") -> Run:
        """The compiled side alone.

        For the one property the comparison cannot see: the generated C
        keeps its recursion counters in static storage, so what a second
        invocation finds is a question the VM — whose counters are frame
        locals — does not have.
        """
        compiled = subprocess.run(
            [str(self.binary), str(self._host_file(host))],
            capture_output=True,
            text=True,
            check=False,
        )
        return Run(compiled.stdout, compiled.returncode)


def compile_once(
    vm: Path,
    cc: str,
    tmp_path: Path,
    source: str | Container,
    *,
    flags: list[str] | None = None,
    repeat: int = 1,
) -> Compiled:
    """Lower, compile and stage a container for both backends.

    Takes assembler text or a `Container`, because since the compiler
    exists there are two ways to get one and the differential test is
    the same test either way.
    """
    container = assemble(source) if isinstance(source, str) else source
    entry = next(f.name for f in container.functions if f.invocable)

    blob = tmp_path / "program.mcs"
    blob.write_bytes(container.encode())
    (tmp_path / "program.c").write_text(generate(container), encoding="utf-8")
    (tmp_path / "shim.c").write_text(_shim(container, entry, repeat), encoding="utf-8")
    binary = tmp_path / "compiled"
    build = subprocess.run(
        [
            cc,
            *(
                flags
                if flags is not None
                else [*CONFORMING_FLAGS, "-Wall", "-Wextra", "-Werror"]
            ),
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
    return Compiled(binary, blob, vm, tmp_path)


def both(
    vm: Path, cc: str, tmp_path: Path, source: str | Container, host: str
) -> tuple[Run, Run]:
    return compile_once(vm, cc, tmp_path, source)(host)


def _same(interpreted: Run, compiled: Run) -> Run:
    assert interpreted.output == compiled.output, (
        f"the backends disagree\n"
        f"  interpreted: {interpreted.output!r}\n"
        f"  compiled:    {compiled.output!r}"
    )
    assert interpreted.code == compiled.code
    return interpreted


def agree(vm, cc, tmp_path, source: str | Container, host: str = "") -> Run:
    return _same(*both(vm, cc, tmp_path, source, host))
