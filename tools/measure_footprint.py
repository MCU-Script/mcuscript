#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0
"""What the runtime costs on a device, per target and per group set.

ADR 0002 §8 carried "no flash/RAM budget has ever been measured for the
engine on any target" as an open question, and ADR 0002 §1.3 rests the
modularity requirement on a number nobody had. This produces both.

It cross-compiles the runtime — it does not run it. Flash and static RAM
are exact from the object files; the stack figure is GCC's own
`-fstack-usage`, summed over every function, which is a safe upper bound
because the runtime does not recurse. What a real image costs on top of
this is the embedder's host table and the slot buffer, both sized by the
macros in `runtime/include/mcuscript.h` and both reported here.

    python tools/measure_footprint.py                    # a table
    python tools/measure_footprint.py --cc /path/to/gcc  # a specific one

Not part of the installed distribution — it is a project tool, not
something a user of the toolchain needs.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RUNTIME = REPO / "runtime"
SOURCES = ("load", "vm", "names")

#: A cross compiler, in the order worth trying. Anything ARM-EABI does.
CANDIDATES = ("arm-none-eabi-gcc", "arm-zephyr-eabi-gcc")

#: Targets that make the number mean something: the floor, the part most
#: of the field ships, and the one MCUScript's first embedder builds for.
TARGETS: dict[str, tuple[str, ...]] = {
    "cortex-m0+": ("-mcpu=cortex-m0plus", "-mthumb", "-mfloat-abi=soft"),
    "cortex-m4f": (
        "-mcpu=cortex-m4",
        "-mthumb",
        "-mfloat-abi=hard",
        "-mfpu=fpv4-sp-d16",
    ),
    "cortex-m33": (
        "-mcpu=cortex-m33",
        "-mthumb",
        "-mfloat-abi=hard",
        "-mfpu=fpv5-sp-d16",
    ),
}

CORE = "MCUSCRIPT_GROUP_CORE"
I64 = "MCUSCRIPT_GROUP_I64"
FLOAT = "MCUSCRIPT_GROUP_FLOAT"
CALL = "MCUSCRIPT_GROUP_CALL"
BITS = "MCUSCRIPT_GROUP_BITS"
I64DIV = "MCUSCRIPT_GROUP_I64DIV"

#: Group sets worth a column. `expressions` is the configuration ADR
#: 0002 §1.3 describes — "a device that only evaluates expressions
#: should link only an expression evaluator" — and `expressions+float`
#: is that device once its sensors report temperatures.
CONFIGS: dict[str, tuple[str, ...]] = {
    "full": (CORE, I64, FLOAT, CALL, BITS, I64DIV),
    "no i64": (CORE, FLOAT, CALL, BITS),
    "no i64 division": (CORE, I64, FLOAT, CALL, BITS),
    "no float": (CORE, I64, CALL, BITS, I64DIV),
    "no call": (CORE, I64, FLOAT, BITS, I64DIV),
    "no bits": (CORE, I64, FLOAT, CALL, I64DIV),
    "expressions+float": (CORE, FLOAT),
    "expressions": (CORE,),
}

WARNINGS = (
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
)

BASE = (
    "-std=c99",
    "-Os",
    "-ffunction-sections",
    "-fdata-sections",
    "-ffp-contract=off",
    f"-I{RUNTIME / 'include'}",
    f"-I{RUNTIME / 'src'}",
)

#: Sizes an embedder pays that are not in the runtime's own sections: it
#: declares the program and the slot buffer, and both are sized by the
#: macros rather than by the container.
PROBE = """
#include "mcuscript.h"
char mcuscript_probe_program[sizeof(mcuscript_program)];
char mcuscript_probe_slots[sizeof(mcuscript_slots)];
"""

#: The smallest honest embedder: load a container, run an entry point,
#: report a code on failure. It brings its own `<string.h>` so that what
#: gets linked is the runtime and the compiler's support library, and
#: not a C library the target may not have.
#:
#: Linking is the whole point of this file. Object files show the code
#: this project writes; they do not show `__udivmoddi4`, `__aeabi_idiv`
#: or the soft-float helpers, which the *compiler* emits calls to and
#: the linker pulls in — and on a Cortex-M0+ those outweigh several of
#: the groups. A per-object figure understates a real device by a third.
EMBEDDER = """
#include "mcuscript.h"
void *memset(void *d, int c, size_t n);
void *memcpy(void *d, const void *s, size_t n);
int memcmp(const void *x, const void *y, size_t n);
size_t strlen(const char *s);
void *memset(void *d, int c, size_t n)
{ unsigned char *p = d; while (n--) *p++ = (unsigned char)c; return d; }
void *memcpy(void *d, const void *s, size_t n)
{ unsigned char *a = d; const unsigned char *b = s; while (n--) *a++ = *b++; return d; }
int memcmp(const void *x, const void *y, size_t n)
{ const unsigned char *a = x, *b = y;
  while (n--) { if (*a != *b) return *a - *b; a++; b++; } return 0; }
size_t strlen(const char *s)
{ const char *p = s; while (*p) p++; return (size_t)(p - s); }

extern const uint8_t IMAGE[64];
extern const mcuscript_host HOST;
static mcuscript_program program;
static mcuscript_slots slots;
volatile int sink;

void mcuscript_measure_entry(void);
void mcuscript_measure_entry(void)
{
\tmcuscript_diagnostic diagnostic;
\tmcuscript_fault fault;
\tmcuscript_value value;
\tif (!mcuscript_load(&program, IMAGE, sizeof IMAGE, &HOST, 1, 1, &diagnostic)) {
\t\tsink = (int)diagnostic.refusal;
\t\treturn;
\t}
\tif (!mcuscript_invoke(&program, mcuscript_find_entry(&program, "go"), &slots,
\t\t\t      &value, &fault))
\t\tsink = (int)fault;
}
"""

#: Symbols the measurement provides itself, subtracted from the linked
#: total so the figure is the runtime's and not this file's.
EMBEDDER_OWN = ("memset", "memcpy", "memcmp", "strlen", "mcuscript_measure_entry")


@dataclass(frozen=True, slots=True)
class Measurement:
    flash: dict[str, int]  # per translation unit
    linked: int  # a real image, support library included
    static_ram: int
    stack: dict[str, int]  # per translation unit, and they never nest
    program: int
    slots: int

    @property
    def total_flash(self) -> int:
        return sum(self.flash.values())


class Toolchain:
    """A cross compiler and the two binutils that sit beside it."""

    def __init__(self, cc: str) -> None:
        self.cc = cc
        stem = Path(cc).name
        prefix = stem[: -len("gcc")] if stem.endswith("gcc") else ""
        self.size = self._beside(cc, prefix + "size")
        self.nm = self._beside(cc, prefix + "nm")

    @staticmethod
    def _beside(cc: str, name: str) -> str:
        candidate = Path(cc).resolve().parent / name
        if candidate.exists():
            return str(candidate)
        found = shutil.which(name)
        if found is None:
            raise SystemExit(f"{name} not found beside {cc} or on PATH")
        return found

    def version(self) -> str:
        out = subprocess.run(
            [self.cc, "-dumpversion"], capture_output=True, text=True, check=True
        )
        return f"{Path(self.cc).name} {out.stdout.strip()}"


def find_compiler(explicit: str | None) -> Toolchain:
    if explicit:
        return Toolchain(explicit)
    for name in CANDIDATES:
        found = shutil.which(name)
        if found:
            return Toolchain(found)
    raise SystemExit(
        "no ARM cross compiler found. Install one of "
        f"{', '.join(CANDIDATES)}, or pass --cc."
    )


def sections(tools: Toolchain, obj: Path) -> tuple[int, int]:
    """(flash, static RAM) of one object, from its section sizes.

    Berkeley `size` puts read-only data in `text`, which is the right
    split for a device: both live in flash.
    """
    out = subprocess.run(
        [tools.size, str(obj)], capture_output=True, text=True, check=True
    )
    text, data, bss = (int(n) for n in out.stdout.splitlines()[1].split()[:3])
    return text, data + bss


def stack_usage(directory: Path) -> dict[str, int]:
    """An upper bound per translation unit, from GCC's own figures.

    Every frame in the unit, summed. Bound rather than exact — the
    deepest chain is shorter than that — but a safe one, because no
    function can appear twice in a chain: the runtime does not recurse,
    which is the same property the loader proves about the *container*,
    applied to the C that runs it. It is also close, since each unit is
    one large function and a handful of small helpers.

    Per unit rather than in total, because the two paths never nest.
    `mcuscript_load` has long returned when `mcuscript_invoke` is
    called, so a device needs the larger of the two and not their sum.
    """
    bounds = {}
    for su in sorted(directory.glob("*.su")):
        bounds[su.stem.removesuffix(".c")] = sum(
            int(fields[1])
            for line in su.read_text(encoding="utf-8").splitlines()
            if len(fields := line.split("\t")) >= 2
        )
    return bounds


def symbol_sizes(tools: Toolchain, path: Path) -> dict[str, int]:
    out = subprocess.run(
        [tools.nm, "--print-size", "--radix=d", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    sizes = {}
    for line in out.stdout.splitlines():
        fields = line.split()
        if len(fields) == 4:
            sizes[fields[3]] = int(fields[1])
    return sizes


def link(tools: Toolchain, flags: list[str], keep: Path) -> int:
    """Text of a real image, minus what this file contributed to it.

    `--gc-sections` is what makes the figure honest in the other
    direction too: an embedder that never asks for a refusal's name does
    not link `names.c`, and the number says so.
    """
    embedder = keep / "embedder.c"
    embedder.write_text(EMBEDDER, encoding="utf-8")
    image = keep / "image.elf"
    subprocess.run(
        [
            tools.cc,
            *flags,
            "-nostdlib",
            "-nostartfiles",
            "-Wl,--gc-sections",
            "-Wl,-e,mcuscript_measure_entry",
            "-Wl,--defsym,IMAGE=0",
            "-Wl,--defsym,HOST=0",
            *(str(RUNTIME / "src" / f"{name}.c") for name in SOURCES),
            str(embedder),
            "-lgcc",
            "-o",
            str(image),
        ],
        check=True,
    )
    text, _ = sections(tools, image)
    sizes = symbol_sizes(tools, image)
    return text - sum(sizes.get(name, 0) for name in EMBEDDER_OWN)


def measure(tools: Toolchain, target: str, config: str, keep: Path) -> Measurement:
    flags = [
        *BASE,
        *WARNINGS,
        *TARGETS[target],
        "-DMCUSCRIPT_GROUPS_IMPLEMENTED=" + "|".join(CONFIGS[config]),
    ]
    flash: dict[str, int] = {}
    static_ram = 0
    for name in SOURCES:
        obj = keep / f"{name}.o"
        subprocess.run(
            [
                tools.cc,
                *flags,
                "-fstack-usage",
                "-c",
                str(RUNTIME / "src" / f"{name}.c"),
            ],
            cwd=keep,
            check=True,
        )
        text, ram = sections(tools, obj)
        flash[name] = text
        static_ram += ram

    probe = keep / "probe.c"
    probe.write_text(PROBE, encoding="utf-8")
    subprocess.run(
        [tools.cc, *flags, "-c", str(probe), "-o", str(keep / "probe.o")], check=True
    )
    sizes = symbol_sizes(tools, keep / "probe.o")

    return Measurement(
        linked=link(tools, flags, keep),
        flash=flash,
        static_ram=static_ram,
        stack=stack_usage(keep),
        program=sizes["mcuscript_probe_program"],
        slots=sizes["mcuscript_probe_slots"],
    )


def table(rows: list[list[str]], align: str) -> str:
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    out = []
    for index, row in enumerate(rows):
        cells = [
            cell.rjust(widths[i]) if align[i] == "r" else cell.ljust(widths[i])
            for i, cell in enumerate(row)
        ]
        out.append("| " + " | ".join(cells) + " |")
        if index == 0:
            out.append(
                "|"
                + "|".join(
                    ("-" * (widths[i] + 1)) + (":" if align[i] == "r" else "-")
                    for i in range(len(row))
                )
                + "|"
            )
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", help="the cross compiler to measure with")
    args = parser.parse_args()

    tools = find_compiler(args.cc)
    print(f"<!-- {tools.version()}, -Os -->\n")

    results: dict[tuple[str, str], Measurement] = {}
    with tempfile.TemporaryDirectory() as raw:
        for target in TARGETS:
            for config in CONFIGS:
                work = Path(raw) / f"{target}-{config}".replace(" ", "-").replace(
                    "+", "p"
                )
                work.mkdir()
                results[target, config] = measure(tools, target, config, work)

    print(
        "**Flash, bytes.** A linked image: loader, verifier, interpreter and\n"
        "the compiler's support library, with unreferenced code discarded.\n"
    )
    rows = [["group set", *TARGETS]]
    for config in CONFIGS:
        rows.append([config, *(f"{results[t, config].linked:,}" for t in TARGETS)])
    print(table(rows, "l" + "r" * len(TARGETS)))

    reference = "cortex-m33"
    print(f"\n**What each group costs**, on {reference}: full minus that group.\n")
    full = results[reference, "full"].linked
    rows = [["group", "bytes", "of the full build"]]
    for config in ("no i64", "no i64 division", "no float", "no call", "no bits"):
        cost = full - results[reference, config].linked
        rows.append(
            [config.removeprefix("no "), f"{cost:,}", f"{100 * cost / full:.0f} %"]
        )
    core = results[reference, "expressions"].linked
    rows.append(["core (mandatory)", f"{core:,}", f"{100 * core / full:.0f} %"])
    print(table(rows, "lrr"))

    print(
        f"\n**This project's own code**, on {reference}, per translation unit —\n"
        "object files, so no support library and no discarding. The gap to the\n"
        "table above is what the *compiler* adds and what `names.c` costs the\n"
        "embedders who report a refusal in words.\n"
    )
    rows = [["", *(name + ".c" for name in SOURCES), "total", "linked"]]
    for config in ("full", "expressions+float", "expressions"):
        m = results[reference, config]
        rows.append(
            [
                config,
                *(f"{m.flash[n]:,}" for n in SOURCES),
                f"{m.total_flash:,}",
                f"{m.linked:,}",
            ]
        )
    print(table(rows, "l" + "r" * (len(SOURCES) + 2)))

    print("\n**RAM, bytes.** None of it is static; every figure is the embedder's.\n")
    rows = [
        [
            "target",
            "static",
            "mcuscript_program",
            "mcuscript_slots",
            "stack: load",
            "stack: invoke",
        ]
    ]
    for target in TARGETS:
        m = results[target, "full"]
        rows.append(
            [
                target,
                str(m.static_ram),
                f"{m.program:,}",
                str(m.slots),
                f"{m.stack['load']:,}",
                f"{m.stack['vm']:,}",
            ]
        )
    print(table(rows, "lrrrrr"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
