# The MCUScript host toolchain

Everything that runs on a developer's machine rather than on a device:
the container reader and writer, the assembler, the verifier, the C
backend, and — when it arrives — the compiler. The VM that executes a
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
mcuscript verify program.mcs                   # is it a conforming container?
mcuscript strip program.mcs -o device.mcs      # drop what a device does not read
mcuscript cc program.mcs -o program.c          # container → C, the second backend
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
| `verify.py` | A conforming verifier (spec §2.6.0) — after ADR 0006 the only one this project ships, and the compiler's second opinion on its own output |
| `asm.py` | Assembler and disassembler |
| `cbackend.py` | The second backend: a container, lowered to plain C |
| `corpus.py` | The conformance corpus's definitions; `../build_corpus.py` writes it |
| `cli.py` | The `mcuscript` command |

## Tests

```sh
.venv/bin/python -m pytest tools/tests -q
```

Three of them are not tests of the code but of the **specification**:
the opcode table, the refusal names and the fault names are compared
against the specification's own tables, so a change to one that is not a
change to the other fails the build.

`test_corpus.py` is the one that binds the two *loaders* — for as long
as there are two; ADR 0006 removes the C one's verifier. It runs
[`spec/corpus/`](../spec/corpus/) — containers with the verdict each
must get — past the Python verifier and the C runtime, and it also
checks that the committed bytes are still the ones
`src/mcuscript/corpus.py` produces. When they are not, regenerate with
`python tools/build_corpus.py` and read the diff: a container format
changes on purpose, so it should be visible in review.

`test_differential.py`, `test_float_agreement.py` and `test_call.py`
are the ones that matter most. They run the same container through the
VM and through the compiled C output and assert the two produce
**byte-identical** output — not that each matches a written
expectation, which would only test the expectation. They need `cmake`
and a C compiler and skip without them.

Two of their assertions are deliberately not comparisons, and each says
why in place: the float suite has the only test in this repository that
asserts the backends **disagree** (under a non-conforming build flag,
so the requirement cannot quietly stop mattering), and the call suite
invokes the compiled program twice in one process, because the VM has
no static recursion counter to get wrong and the generated C does.
