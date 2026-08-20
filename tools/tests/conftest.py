# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0
"""Fixtures shared by the test modules that need a built runtime.

The runtime is built once per session and both the interpreter tests and
the differential tests use the same binary — building it twice would be
slow and would let the two suites disagree about which runtime they are
talking about.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

RUNTIME = Path(__file__).resolve().parents[2] / "runtime"

#: §7.4 lets two variables name a profile and a registry, and §7.5 one
#: more name a header. A test run inherits the shell it was started
#: from, and none of these tests mean to.
WORLD_VARIABLES = ("MCUSCRIPT_PROFILE", "MCUSCRIPT_REGISTRY", "MCUSCRIPT_EMIT_C")


@pytest.fixture(autouse=True)
def _no_world_from_the_environment(monkeypatch):
    for variable in WORLD_VARIABLES:
        monkeypatch.delenv(variable, raising=False)


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
