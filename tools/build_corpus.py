#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0
"""Write the conformance corpus in spec/corpus/.

Run this when the container format changes, and read the diff: the
corpus is committed bytes on purpose, so a format change is meant to be
visible in review rather than absorbed by a fixture that rebuilds
itself. `tools/tests/test_corpus.py` fails until it has been run.

Not part of the installed distribution — it is a project tool, not
something a user of the toolchain needs.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from mcuscript import corpus  # noqa: E402

if __name__ == "__main__":
    directory = Path(__file__).resolve().parents[1] / "spec" / "corpus"
    written = corpus.write(directory)
    print(f"{len(written)} files in {directory}")
