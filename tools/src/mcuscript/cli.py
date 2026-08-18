# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0
"""The ``mcuscript`` command.

Four subcommands so far, and each one is a thing the specification says
somebody must be able to do: turn text into a container, turn a
container back into text, refuse a bad container by name, and say what
is inside a good one.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from . import SPEC_VERSION, __version__
from .asm import AsmError, assemble, disassemble
from .cbackend import UnsupportedProgram
from .container import Container, ImportKind
from .errors import Refused
from .opcodes import IMPLEMENTED_GROUPS, Group, ValType, group_names
from .verify import verify

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mcuscript",
        description="The MCUScript host toolchain.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"mcuscript {__version__} (specification {SPEC_VERSION})",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("asm", help="assemble text into a container")
    p.add_argument("source", type=Path)
    p.add_argument("-o", "--output", type=Path, required=True)
    p.set_defaults(run=_asm)

    p = sub.add_parser("dis", help="render a container as assembler source")
    p.add_argument("container", type=Path)
    p.set_defaults(run=_dis)

    p = sub.add_parser("verify", help="check a container as a loader would")
    p.add_argument("container", type=Path)
    p.set_defaults(run=_verify)

    p = sub.add_parser("cc", help="lower a container to C")
    p.add_argument("container", type=Path)
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        required=True,
        help="the .c file to write; a .h beside it gets the declarations",
    )
    p.set_defaults(run=_cc)

    p = sub.add_parser("info", help="describe a container")
    p.add_argument("container", type=Path)
    p.set_defaults(run=_info)

    p = sub.add_parser(
        "strip", help="drop the ancillary sections a device does not read"
    )
    p.add_argument("container", type=Path)
    p.add_argument("-o", "--output", type=Path, required=True)
    p.set_defaults(run=_strip)

    args = parser.parse_args(argv)
    try:
        return args.run(args)
    except AsmError as error:
        print(f"{args.source}:{error.line}: {error}", file=sys.stderr)
        return EXIT_USAGE
    except Refused as error:
        print(f"refused: {error}", file=sys.stderr)
        return EXIT_REFUSED
    except UnsupportedProgram as error:
        print(f"cannot lower: {error}", file=sys.stderr)
        return EXIT_USAGE
    except OSError as error:
        print(f"{error}", file=sys.stderr)
        return EXIT_USAGE


def _asm(args: argparse.Namespace) -> int:
    container = assemble(args.source.read_text(encoding="utf-8"))
    blob = container.encode()
    args.output.write_bytes(blob)
    print(f"{args.output}: {len(blob)} bytes, {len(container.functions)} function(s)")
    return EXIT_OK


def _dis(args: argparse.Namespace) -> int:
    print(disassemble(_load(args.container)), end="")
    return EXIT_OK


def _verify(args: argparse.Namespace) -> int:
    container = _load(args.container)
    facts = verify(container)
    for name, fact in facts.items():
        print(
            f"{name}: stack {fact.max_stack}, call depth {fact.max_call_depth}, "
            f"{fact.max_slots} slots"
            + (f", recursion cap {fact.recursion_cap}" if fact.recursion_cap else "")
        )
    return EXIT_OK


def _cc(args: argparse.Namespace) -> int:
    from .cbackend import generate, header

    container = _load(args.container)
    # The C backend consumes a *verified* container: it inherits the
    # types and depths rather than recomputing them, so refusing here is
    # not a courtesy, it is the precondition.
    verify(container, implemented=frozenset(Group))
    args.output.write_text(
        generate(container, source=args.container.name), encoding="utf-8"
    )
    declarations = args.output.with_suffix(".h")
    declarations.write_text(
        header(container, source=args.container.name), encoding="utf-8"
    )
    print(f"{args.output}\n{declarations}")
    return EXIT_OK


def _strip(args: argparse.Namespace) -> int:
    """Write the container a device should get.

    Everything critical stays; the ancillary sections go, and with them
    the import names (§4.4.2) and any debug information. That is where
    the hash form of the import table actually pays: the toolchain's
    container carries the names *and* their hashes and is therefore
    larger than the old one, and this is what turns that back into a
    saving.

    Do this before signing, not after — §2.3. A signature over the
    unstripped bytes does not cover what was stored.
    """
    container = _load(args.container)
    before = args.container.stat().st_size
    container.ancillary = []
    container.imports = [
        replace(i, name="", name_hash=i.hash) for i in container.imports
    ]
    blob = container.encode(required_groups=container.required_groups)
    args.output.write_bytes(blob)
    print(f"{before} -> {len(blob)} bytes ({before - len(blob)} dropped)")
    return EXIT_OK


def _info(args: argparse.Namespace) -> int:
    container = _load(args.container)
    print(f"format version   {container.format_version}")
    print(
        f"profile          {container.profile_id} "
        f"v{container.profile_major}.{container.profile_minor}"
    )
    print(
        "groups           "
        + (", ".join(group_names(container.required_groups)) or "none")
    )
    missing = [
        g
        for g in group_names(container.required_groups)
        if g not in {i.name.lower() for i in IMPLEMENTED_GROUPS}
    ]
    if missing:
        print(f"                 not implemented here: {', '.join(missing)}")
    print(f"code             {len(container.code)} bytes")
    print(f"constants        {len(container.constants)}")
    for imp in container.imports:
        kind = "entity" if imp.kind == ImportKind.ENTITY else "function"
        extra = f" dim {imp.dimension}" if imp.dimension else ""
        if imp.kind == ImportKind.FUNCTION:
            extra = "(" + ", ".join(str(t) for t in imp.param_types) + ")"
        print(f"import           {kind} {imp.type} {imp.name}{extra}")
    for fn in container.functions:
        kind = "entry" if fn.invocable else "fn"
        returns = "" if fn.return_type is ValType.VOID else f" -> {fn.return_type}"
        signature = (
            "(" + ", ".join(str(t) for t in fn.param_types) + ")"
            if fn.param_count
            else ""
        )
        print(
            f"{kind:16s} {fn.name}{signature}{returns} at {fn.code_offset}, "
            f"stack {fn.max_stack}, locals {len(fn.local_types)}"
        )
    for section in container.ancillary:
        print(f"ancillary        {section.type}, {len(section.data)} bytes")
    return EXIT_OK


def _load(path: Path) -> Container:
    return Container.decode(path.read_bytes())


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
