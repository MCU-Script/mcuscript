# The MCUScript host toolchain

Everything that runs on a developer's machine rather than on a device:
the container reader and writer, the assembler, the verifier, and — as
they arrive — the compiler and the C backend. The VM that executes a
container is C and lives in `runtime/`.

The split is not cosmetic. A host tool may allocate, may take a second,
and may say a paragraph about what went wrong; a device runtime may do
none of those things. Keeping them in different languages keeps the
distinction honest.

## Install

```sh
python -m venv .venv
.venv/bin/pip install -e "tools[dev]"
```

There are **no runtime dependencies**, deliberately: this is the
reference implementation of a specification, and someone reproducing it
should not have to reproduce a dependency tree first.

## Use

```sh
mcuscript asm program.mcs-asm -o program.mcs   # text  → container
mcuscript dis program.mcs                      # container → text
mcuscript verify program.mcs                   # check it as a loader would
mcuscript info program.mcs                     # what is inside
```

There is no compiler and no surface syntax yet, so programs are written
in the assembler's own syntax — see the module docstring in
[`src/mcuscript/asm.py`](src/mcuscript/asm.py). That is on purpose: it
lets the container format, the verifier, the VM and the C backend be
built and tested against each other before anybody argues about how an
`if` should look.

## Layout

| Module | Role |
|---|---|
| `opcodes.py` | The instruction table — one source of truth, read by everything else |
| `errors.py` | Every refusal and fault the specification names |
| `container.py` | The binary format: header, sections, the three tables |
| `verify.py` | The load-time verifier of spec §2.6 |
| `asm.py` | Assembler and disassembler |
| `cli.py` | The `mcuscript` command |

## Tests

```sh
.venv/bin/python -m pytest tools/tests -q
```

Three of them are not tests of the code but of the **specification**:
the opcode table, the refusal names and the fault names are compared
against the specification's own tables, so a change to one that is not a
change to the other fails the build.
