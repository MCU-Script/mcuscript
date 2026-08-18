# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0
"""The error names in the code are the error names in the specification.

A loader that can only say "invalid" is not a loader anybody can debug
against, which is why §4.6 names every refusal. Names drift the moment
nothing compares them, so this compares them: the specification's tables
are the list, and the enum must match it exactly — in both directions.
"""

from __future__ import annotations

import re
from pathlib import Path

from mcuscript.errors import Fault, Refusal

SPEC = Path(__file__).resolve().parents[2] / "spec"


def _names(chapter: str, section: str) -> set[str]:
    """Every `\\`name\\`` in the leftmost column of a table row, within one
    section — the record layouts elsewhere in the chapter have field
    names in that column too."""
    text = (SPEC / chapter).read_text(encoding="utf-8")
    start = text.index(f"\n## {section}")
    end = text.find("\n## ", start + 1)
    body = text[start : end if end != -1 else len(text)]
    return set(re.findall(r"^\|\s*`([a-z_]+)`\s*\|", body, re.MULTILINE))


def test_refusals_match_chapter_four():
    specified = _names("04-linking.md", "4.6 Errors")
    implemented = {r.value for r in Refusal}
    assert specified - implemented == set(), "specified but not implemented"
    assert implemented - specified == set(), "implemented but not specified"


def test_faults_match_chapter_five():
    specified = _names("05-execution.md", "5.5 Faults")
    implemented = {f.value for f in Fault}
    assert specified == implemented


def test_there_are_exactly_four_faults():
    # §5.5 says so in words, and the sentence is load-bearing: everything
    # else that could have been a fault is a value instead. The number
    # moved once, when `loop` stopped being reserved, and the point of
    # pinning it is that the next one has to be argued for as well.
    assert len(Fault) == 4
