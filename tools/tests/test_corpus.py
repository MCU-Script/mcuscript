# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0
"""The conformance corpus, run against both loaders.

This is what the two implementations were built separately *for*. Until
now they were tested separately too: the host verifier against its own
expectations, the runtime against its own, and nothing anywhere asked
whether the two answer the same question the same way. A corpus of
containers with one expected verdict each is that question.

Four properties are checked, and the middle two are the ones that keep
the corpus from decaying into decoration:

1. both loaders give the manifest's verdict;
2. the committed bytes are still the bytes the definitions produce, so
   a change to the container format shows up as a reviewable diff
   instead of as a corpus that quietly tests something else;
3. every refusal the specification names has at least one container —
   a name no container can produce is a name nobody has checked;
4. each case's stage is the §4.6 heading its refusal actually appears
   under, so the corpus cannot disagree with the document about whose
   job a verdict is.
"""

from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

import pytest

from mcuscript import corpus
from mcuscript.container import Container
from mcuscript.errors import Refusal, Refused
from mcuscript.verify import verify

REPO = Path(__file__).resolve().parents[2]
CORPUS = REPO / "spec" / "corpus"
SPEC = REPO / "spec"

MANIFEST = tomllib.loads((CORPUS / "corpus.toml").read_text(encoding="utf-8"))
ENTRIES = MANIFEST["case"]
IDS = [entry["name"] for entry in ENTRIES]


def load_on_the_host(blob: bytes) -> str:
    """§2.7's order, as far as a host toolchain can go.

    It stops before linking: resolving names against a registry is the
    embedder's, at load, and a host tool has no registry to resolve
    against. That is why a `linking` case must be *accepted* here.
    """
    try:
        container = Container.decode(blob)
        container.check_profile(
            corpus.PROFILE_ID, corpus.PROFILE_MAJOR, corpus.PROFILE_MINOR
        )
        verify(container)
    except Refused as refused:
        return str(refused.refusal)
    return ""


# -- the corpus is what the definitions say it is -------------------------


def test_the_committed_bytes_are_the_ones_the_definitions_produce():
    """Otherwise the corpus is a snapshot of a format nobody uses.

    Regenerating is `python tools/build_corpus.py`, and the diff it
    makes is the point: a container format changes rarely and on
    purpose, so it should be visible in review rather than absorbed by
    a fixture that rebuilds itself.
    """
    for case in corpus.cases():
        committed = (CORPUS / case.filename).read_bytes()
        assert committed == case.blob, (
            f"{case.filename} on disk is not what corpus.py produces — "
            "run `python tools/build_corpus.py`"
        )
    assert (CORPUS / "corpus.toml").read_text(encoding="utf-8") == corpus.manifest()


def test_the_manifest_and_the_directory_agree():
    on_disk = {p.name for p in CORPUS.glob("*.mcs")}
    named = {entry["file"] for entry in ENTRIES}
    assert on_disk == named, "a container in the directory that nothing claims"


def test_every_refusal_the_specification_names_has_a_container():
    """A refusal that has never been produced is not a tested refusal.

    Writing this found one: `import_limit` was in §4.6 and neither
    implementation raised it, because the two things it could have meant
    are `unknown_import` and "this build is too small" — and the second
    is deliberately outside the taxonomy, since it refuses a container
    the specification calls well-formed.
    """
    covered = {entry["refusal"] for entry in ENTRIES} - {""}
    missing = {r.value for r in Refusal} - covered
    assert missing == set(), f"specified but no container produces it: {missing}"
    assert covered - {r.value for r in Refusal} == set()


def _headings() -> dict[str, set[str]]:
    """refusal name -> the §4.6 subsections it is listed under.

    A set rather than one value, because two names are listed twice and
    the duplication is the truthful thing: a container can contradict
    itself about an import, and it can contradict the registry. Same
    mistake, same name, different occasion — and only the second needs
    an embedder, which is exactly what a corpus entry has to know.
    """
    text = (SPEC / "04-linking.md").read_text(encoding="utf-8")
    section = text[text.index("\n## 4.6 Errors") :]
    section = section[: section.index("\n## 4.7")]
    out: dict[str, set[str]] = {}
    heading = ""
    for line in section.splitlines():
        if line.startswith("### "):
            heading = line[4:].strip().lower().split()[0]
            continue
        row = re.match(r"^\|\s*`([a-z_]+)`\s*\|", line)
        if row and heading:
            out.setdefault(row.group(1), set()).add(heading)
    return out


def test_each_case_is_filed_under_a_heading_the_specification_uses():
    headings = _headings()
    assert headings, "no error tables parsed — has §4.6's shape changed?"
    for entry in ENTRIES:
        if not entry["refusal"]:
            assert entry["stage"] == "ok"
            continue
        where = headings[entry["refusal"]]
        assert entry["stage"] in where, (
            f"{entry['name']}: the manifest files {entry['refusal']} under "
            f"{entry['stage']}, the specification lists it under "
            f"{', '.join(sorted(where))}"
        )


def test_every_stage_is_one_the_manifest_defines():
    assert {entry["stage"] for entry in ENTRIES} <= set(corpus.STAGES)


# -- the verdicts ---------------------------------------------------------


@pytest.mark.parametrize("entry", ENTRIES, ids=IDS)
def test_the_host_verifier_gives_the_expected_verdict(entry):
    blob = (CORPUS / entry["file"]).read_bytes()
    # A linking refusal is not this verifier's to give, so the container
    # must come through it clean.
    expected = "" if entry["stage"] == "linking" else entry["refusal"]
    assert load_on_the_host(blob) == expected, entry["description"]


#: The cases the C runtime answers for, from the manifest's own
#: `runtime` field. It does not verify (ADR 0006), so a container that
#: is merely a *bad program* is not its business — it will load one and
#: run it, and what happens then is undefined, which is not a thing to
#: assert about. What it does answer for is identity, bytes it cannot
#: parse, and the `ok` cases, which are the promise itself.
RUNTIME_ENTRIES = [e for e in ENTRIES if e["runtime"]]
RUNTIME_IDS = [e["name"] for e in RUNTIME_ENTRIES]


@pytest.mark.parametrize("entry", RUNTIME_ENTRIES, ids=RUNTIME_IDS)
def test_the_runtime_gives_the_expected_verdict(vm, tmp_path, entry):
    host = CORPUS / entry["host"] if "host" in entry else tmp_path / "empty.host"
    if "host" not in entry:
        host.write_text("", encoding="utf-8")
    process = subprocess.run(
        [str(vm), str(CORPUS / entry["file"]), str(host)],
        capture_output=True,
        text=True,
        check=False,
        # A container this suite hands the runtime is one the runtime is
        # answerable for, so a hang is a defect and not undefined
        # behaviour. The bound is here so that it fails as one.
        timeout=30,
    )
    first = process.stdout.split("\n", 1)[0].split()
    refusal = first[1] if first[:1] == ["refused"] else ""
    assert refusal == entry["refusal"], (
        f"{entry['description']}\n  output: {process.stdout!r}"
    )


def test_the_cases_a_runtime_does_not_owe_are_the_ones_it_cannot_answer():
    """The exclusion above is load-bearing, so it is stated as a test.

    If it silently became empty — the field dropped, the filter inverted
    — the suite would go back to feeding the runtime containers whose
    behaviour is undefined, and would hang rather than fail.

    Every excluded case must be one where the container is a *bad
    program* rather than unreadable bytes: the whole `verification`
    stage, plus the three `container` cases that are judgements about a
    program rather than a table a loader cannot step through.
    """
    excluded = [e for e in ENTRIES if not e["runtime"]]
    assert excluded, "nothing excluded; has the manifest changed?"
    assert {e["stage"] for e in excluded} <= {"verification", "container"}
    assert {e["name"] for e in excluded if e["stage"] == "container"} == {
        "entry-takes-parameters",
        "records-out-of-code-order",
        "duplicate-import",
    }
    assert all(e["stage"] != "verification" or not e["runtime"] for e in ENTRIES)
