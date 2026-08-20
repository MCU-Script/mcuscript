# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0
"""Reading the two documents a compilation is given — §7.

A compiler needs a world before it can read a script: which dimensions
exist, and what the script may reach outside itself. Chapter 6 says both
belong to somebody else, and chapter 7 fixes the form they arrive in —
two TOML files, each named by a path, neither of them searched for.

Everything here is strict on purpose, and the strictness is the point
rather than a style. **An unknown key is an error**: a reader that
skipped what it did not recognise would read `ofset = -16000` as a unit
with no offset, accept the file, and compile every temperature in the
world 32 degrees wrong. **A factor is never a float**: TOML's floats are
binary, `0.001` is not one of them, and §6.3.10 decides at compile time
whether a conversion is exact — an approximate answer there is a wrong
answer, not a close one.

The diagnostics carry the file and the key rather than a line number.
`tomllib` reports positions for syntax errors and nothing for values,
and a key path names the place better than a line does in a format where
one table may be written three ways.
"""

from __future__ import annotations

import os
import tomllib
from fractions import Fraction
from pathlib import Path
from typing import Any

from .container import fnv1a32
from .lexer import KEYWORDS, SUFFIX_SYMBOLS, TYPE_NAMES, is_identifier, split_datetime
from .opcodes import ValType
from .profile import Clock, Dimension, Profile, Unit, civil_seconds
from .profile import EMPTY as NO_PROFILE
from .registry import Entity, HostFunction, Quantity, Registry, nearest
from .registry import EMPTY as NO_REGISTRY

#: §7.4. A flag beats the variable; nothing else is consulted.
PROFILE_VARIABLE = "MCUSCRIPT_PROFILE"
REGISTRY_VARIABLE = "MCUSCRIPT_REGISTRY"

#: The format version both documents carry. One reader, one number.
FORMAT = 1

_TYPES = {str(code): code for code in (ValType.I32, ValType.I64, ValType.F32)}
_QUANTITIES = {**_TYPES, str(ValType.BOOL): ValType.BOOL}

_ACCESS = {
    "read": (True, False),
    "write": (False, True),
    "readwrite": (True, True),
}


class WorldError(Exception):
    """A profile or a registry cannot be read, and why.

    Shaped like `Diagnostic` (§6.7) without a span: a message that names
    what is wrong, and notes that say what to do. A file is not a script
    and has no line to underline, so the place is a key path.
    """

    def __init__(
        self, path: Path, where: str, message: str, notes: tuple[str, ...] = ()
    ) -> None:
        self.path = path
        self.where = where
        self.message = message
        self.notes = notes
        head = f"{path}: {message}" if not where else f"{path}: {where}: {message}"
        super().__init__("\n".join([head, *(f"  {note}" for note in notes)]))


def _quoted(key: str) -> str:
    """A key as it is written in the file, so a diagnostic can be copied."""
    return f'"{key}"' if not is_identifier(key) else key


class _Doc:
    """One file being read, and where the reader currently stands."""

    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            self.data = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as bad:
            raise WorldError(path, "", f"this is not readable TOML — {bad}") from bad
        except UnicodeDecodeError as bad:
            raise WorldError(path, "", "this file is not UTF-8 text") from bad

    def fail(self, where: str, message: str, *notes: str) -> WorldError:
        return WorldError(self.path, where, message, notes)

    def root(self) -> _Table:
        return _Table(self, "", self.data)


class _Table:
    """A TOML table that hands out its keys once each and refuses leftovers.

    The keys a caller asks for are exactly the keys chapter 7 defines, so
    `done()` can suggest a spelling without a second list to maintain.
    """

    def __init__(self, doc: _Doc, where: str, data: dict[str, Any]) -> None:
        self.doc = doc
        self.where = where
        self.left = dict(data)
        self.asked: list[str] = []

    def at(self, key: str) -> str:
        return f"{self.where}.{_quoted(key)}" if self.where else _quoted(key)

    def _take(self, key: str) -> Any:
        self.asked.append(key)
        return self.left.pop(key, None)

    def _missing(self, key: str) -> WorldError:
        return self.doc.fail(self.where, f"`{key}` is missing")

    def _wrong(self, key: str, value: Any, wanted: str) -> WorldError:
        return self.doc.fail(self.at(key), f"this is {_kind(value)}, and {wanted}")

    def string(self, key: str) -> str:
        value = self.optional(key)
        if value is None:
            raise self._missing(key)
        return value

    def optional(self, key: str) -> str | None:
        """A string, or `None` where the key is absent — never where it is
        present and empty, which is a mistake and is refused downstream."""
        value = self._take(key)
        if value is None:
            return None
        if not isinstance(value, str):
            raise self._wrong(key, value, "a string was wanted")
        return value

    def strings(self, key: str) -> list[str]:
        value = self._take(key)
        if value is None:
            return []
        ok = isinstance(value, list) and all(isinstance(item, str) for item in value)
        if not ok:
            raise self._wrong(key, value, "a list of quantities was wanted")
        return value

    def integer(self, key: str, low: int, high: int) -> int:
        value = self._take(key)
        if value is None:
            raise self._missing(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise self._wrong(key, value, "a whole number was wanted")
        if not low <= value <= high:
            raise self.doc.fail(self.at(key), f"{value} is outside {low} to {high}")
        return value

    def flag(self, key: str) -> bool:
        value = self._take(key)
        if value is None:
            return False
        if not isinstance(value, bool):
            raise self._wrong(key, value, "`true` or `false` was wanted")
        return value

    def exact(self, key: str, default: Fraction | None = None) -> Fraction:
        """A number that has to be exact, so never a float (§7.2.3)."""
        value = self._take(key)
        if value is None:
            if default is not None:
                return default
            raise self._missing(key)
        return _exact(self.doc, self.at(key), value)

    def mapping(self, key: str) -> tuple[str, dict[str, Any]]:
        """A table whose keys are the file's own words, not this chapter's."""
        value = self._take(key)
        if value is None:
            return self.at(key), {}
        if not isinstance(value, dict):
            raise self._wrong(key, value, "a table was wanted")
        return self.at(key), value

    def table(self, key: str, required: bool = False) -> _Table | None:
        value = self._take(key)
        if value is None:
            if required:
                raise self._missing(key)
            return None
        if not isinstance(value, dict):
            raise self._wrong(key, value, "a table was wanted")
        return _Table(self.doc, self.at(key), value)

    def done(self) -> None:
        for key in self.left:
            notes = []
            close = nearest(key, tuple(self.asked))
            if close:
                notes.append(f"Did you mean `{close[0]}`?")
            raise self.doc.fail(self.at(key), "this key means nothing here", *notes)


def _kind(value: Any) -> str:
    """What a TOML value is, in the words a person would use."""
    if isinstance(value, bool):
        return "`true` or `false`"
    if isinstance(value, float):
        return "a decimal number"
    if isinstance(value, int):
        return "a whole number"
    if isinstance(value, str):
        return "a string"
    if isinstance(value, dict):
        return "a table"
    if isinstance(value, list):
        return "a list"
    return "not a value this reader knows"  # pragma: no cover - TOML has no others


def _exact(doc: _Doc, where: str, value: Any) -> Fraction:
    """A factor or an offset, exactly (§7.2.3)."""
    if isinstance(value, bool):
        raise doc.fail(where, "this is `true` or `false`, and a number was wanted")
    if isinstance(value, float):
        written = repr(value)
        raise doc.fail(
            where,
            f"{written} is a decimal number, and this one has to be exact",
            f'Write it as text: "{written}". A decimal in this file is a '
            "binary fraction, and most of the factors a profile is made of "
            "are not binary fractions.",
        )
    if isinstance(value, int):
        return Fraction(value)
    if not isinstance(value, str):
        raise doc.fail(where, f"this is {_kind(value)}, and a number was wanted")
    try:
        return Fraction(value)
    except (ValueError, ZeroDivisionError) as bad:
        raise doc.fail(
            where,
            f'"{value}" is not a number',
            "A whole number, a decimal such as \"0.001\", or a ratio such "
            'as "500/9".',
        ) from bad


# -- the profile -------------------------------------------------------------


def read_profile(path: str | Path) -> Profile:
    """One profile file, checked as §7.2 says and no further."""
    doc = _Doc(Path(path))
    root = doc.root()
    _format(doc, root)

    head = root.table("profile", required=True)
    assert head is not None
    name = head.string("name")
    identifier = head.integer("id", 1, 0xFFFF_FFFF)
    version = _version(doc, head, "version")
    head.done()

    dimensions = []
    where, table = root.mapping("dimension")
    for word, body in table.items():
        dimensions.append(_dimension(doc, f"{where}.{_quoted(word)}", word, body))
    root.done()

    try:
        return Profile(name, version, tuple(dimensions), id=identifier)
    except ValueError as bad:
        # Everything the model checks is checked above with a better
        # sentence; this catches the one that needs the whole file.
        raise doc.fail("", str(bad)) from bad


def _format(doc: _Doc, root: _Table) -> None:
    version = root.integer("format", 0, 0xFFFF)
    if version != FORMAT:
        raise doc.fail(
            "format",
            f"this file says format {version}, and this reader knows {FORMAT}",
        )


def _version(doc: _Doc, table: _Table, key: str) -> str:
    text = table.string(key)
    parts = text.split(".")
    ok = len(parts) == 2 and all(part.isdigit() and len(part) < 6 for part in parts)
    if not ok or not all(int(part) <= 0xFFFF for part in parts):
        raise doc.fail(
            table.at(key),
            f'"{text}" is not a version',
            "Two whole numbers with a dot between them, each at most "
            '65535 — "0.1".',
        )
    return text


def _dimension(doc: _Doc, where: str, word: str, body: Any) -> Dimension:
    if not isinstance(body, dict):
        raise doc.fail(where, f"this is {_kind(body)}, and a table was wanted")
    if not is_identifier(word) or word in KEYWORDS:
        raise doc.fail(
            where,
            f"`{word}` cannot be a dimension's name",
            "A name is a letter or `_` followed by letters, digits and "
            "`_`, and is not one of the language's words.",
        )
    if word in TYPE_NAMES:
        raise doc.fail(
            where,
            f"`{word}` is a type, so a dimension cannot be called that",
            "A registry writes a dimension's name or a type's in the same "
            "place, and one word cannot be both.",
        )

    table = _Table(doc, where, body)
    identifier = table.integer("id", 1, 0xFFFF)
    type_name = table.string("type")
    if type_name not in _TYPES:
        known = ", ".join(f"`{name}`" for name in _TYPES)
        raise doc.fail(
            table.at("type"),
            f"`{type_name}` is not a type a dimension may be held in",
            f"One of {known}. A quantity that is a yes-or-no has no units "
            "to convert.",
        )
    base_unit = _label(doc, table.at("base_unit"), table.string("base_unit"))
    units = _units(doc, table)
    cyclic = table.flag("cyclic")
    scale = table.flag("scale")
    clock = _clock(doc, table)
    table.done()

    try:
        return Dimension(
            identifier,
            word,
            _TYPES[type_name],
            base_unit,
            units,
            cyclic=cyclic,
            scale=scale,
            clock=clock,
        )
    except ValueError as bad:
        raise doc.fail(where, str(bad)) from bad


def _label(doc: _Doc, where: str, text: str) -> str:
    """A base unit is a word for diagnostics, and is held to less.

    §6.5.4 says a script never names the base unit — a profile need not
    even spell it — so the character rule below would be a restriction
    on nothing. What it has to be is one printable word, because it ends
    up in the middle of a sentence: *this profile counts temperature in
    whole `c°C`*. A profile that wants its base unit writable declares it
    under `units` as well, and there the rule does apply.
    """
    if not text or any(char.isspace() or not char.isprintable() for char in text):
        raise doc.fail(where, f'"{text}" cannot be a base unit', "One word.")
    return text


def _spelling(doc: _Doc, where: str, text: str) -> str:
    """A unit spelling is the lexer's rule and not a profile's (§6.1.5)."""
    ok = bool(text) and all(
        char.isalpha() or char in SUFFIX_SYMBOLS for char in text
    )
    if not ok:
        raise doc.fail(
            where,
            f'"{text}" cannot be a unit',
            "A unit is letters, `%`, `‰` and `°`, and nothing else — that "
            "is what keeps a suffix from colliding with an operator.",
        )
    return text


def _units(doc: _Doc, dimension: _Table) -> tuple[Unit, ...]:
    where, table = dimension.mapping("units")
    units = []
    for spelling, value in table.items():
        at = f"{where}.{_quoted(spelling)}"
        _spelling(doc, at, spelling)
        if isinstance(value, dict):
            body = _Table(doc, at, value)
            factor = body.exact("factor")
            offset = body.exact("offset", Fraction(0))
            body.done()
        else:
            factor = _exact(doc, at, value)
            offset = Fraction(0)
        if factor <= 0:
            raise doc.fail(
                at,
                f"a unit cannot be {factor} of a base unit",
                "A factor is what one of this unit is worth, so it is "
                "greater than zero.",
            )
        units.append(Unit(spelling, factor, offset))
    return tuple(units)


def _clock(doc: _Doc, dimension: _Table) -> Clock | None:
    table = dimension.table("calendar")
    if table is None:
        return None
    second = table.exact("second")
    if second <= 0:
        raise doc.fail(table.at("second"), f"a second cannot be {second} base units")
    text = table.optional("epoch")
    table.done()
    if text is None:
        return Clock(second)
    day, time = split_datetime(text)
    if not day:
        raise doc.fail(
            table.at("epoch"),
            f'"{text}" is a time of day, and an epoch is a day',
            "A dimension that leaves `epoch` out is the one that takes the "
            "times of day; it counts from midnight.",
        )
    try:
        return Clock(second, civil_seconds(day, time))
    except ValueError as bad:
        raise doc.fail(table.at("epoch"), f'"{text}" is not a moment — {bad}') from bad


# -- the registry ------------------------------------------------------------


def read_registry(path: str | Path, profile: Profile) -> Registry:
    """One registry file, against the profile it claims (§7.3)."""
    doc = _Doc(Path(path))
    root = doc.root()
    _format(doc, root)
    _pin(doc, root, profile)

    entities = []
    where, table = root.mapping("entity")
    for word, body in table.items():
        entities.append(_entity(doc, f"{where}.{_quoted(word)}", word, body, profile))

    functions = []
    where, table = root.mapping("function")
    for word, body in table.items():
        functions.append(_function(doc, f"{where}.{_quoted(word)}", word, body, profile))
    root.done()

    _unique(doc, entities, functions)
    return Registry(tuple(entities), tuple(functions))


def _pin(doc: _Doc, root: _Table, profile: Profile) -> None:
    """§7.3.1: a registry is written against one profile and says which."""
    head = root.table("profile", required=True)
    assert head is not None
    identifier = head.integer("id", 0, 0xFFFF_FFFF)
    version = _version(doc, head, "version")
    head.done()

    major, _, minor = version.partition(".")
    if identifier != profile.id or int(major) != profile.major:
        raise doc.fail(
            "profile",
            f"this registry was written against profile {identifier} "
            f"{version}, and the profile given is {profile.id} "
            f"{profile.version}",
            "What a dimension means — its base unit, how fine it is held "
            "— is the profile's, so a registry belongs to one.",
        )
    if int(minor) > profile.minor:
        raise doc.fail(
            "profile",
            f"this registry needs profile {identifier} {version}, and the "
            f"profile given is {profile.version}",
        )


def _name(doc: _Doc, where: str, word: str) -> str:
    """A name a script can write, and nothing else (§7.3.2).

    A part after a dot may be one of the language's words and the first
    part may not, which is the grammar's rule and not a concession:
    nothing but a name can stand after a `.`, and `fan.on` is the most
    ordinary line anyone will write.
    """
    first, *rest = word.split(".")
    ok = is_identifier(first) and first not in KEYWORDS
    if not ok or not all(is_identifier(part) for part in rest):
        raise doc.fail(
            where,
            f"`{word}` is not a name a script can write",
            "One or more names joined by dots, each a letter or `_` "
            "followed by letters, digits and `_`. Only the first may not "
            "be one of the language's words.",
        )
    return word


def _quantity(doc: _Doc, where: str, text: str, profile: Profile) -> Quantity:
    """A dimension's name or a type's — one key, because a dimension is a type."""
    dimension = profile.find_dimension(text)
    if dimension is not None:
        return Quantity(dimension.type, dimension)
    if text in _QUANTITIES:
        return Quantity(_QUANTITIES[text])
    known = tuple(sorted({d.name for d in profile.dimensions} | set(_QUANTITIES)))
    notes = []
    close = nearest(text, known)
    if close:
        notes.append("Did you mean " + " or ".join(f"`{c}`" for c in close) + "?")
    elif not profile.dimensions:
        notes.append(f"The profile `{profile.name}` declares no dimensions.")
    raise doc.fail(where, f"`{text}` is not a dimension or a type", *notes)


def _entity(
    doc: _Doc, where: str, word: str, body: Any, profile: Profile
) -> Entity:
    if not isinstance(body, dict):
        raise doc.fail(where, f"this is {_kind(body)}, and a table was wanted")
    _name(doc, where, word)
    table = _Table(doc, where, body)
    quantity = _quantity(doc, table.at("quantity"), table.string("quantity"), profile)
    written = table.optional("access")
    access = "read" if written is None else written
    if access not in _ACCESS:
        raise doc.fail(
            table.at("access"),
            f'"{access}" is not an access',
            'One of "read", "write", "readwrite".',
        )
    table.done()
    readable, writable = _ACCESS[access]
    return Entity(word, quantity, readable=readable, writable=writable)


def _function(
    doc: _Doc, where: str, word: str, body: Any, profile: Profile
) -> HostFunction:
    if not isinstance(body, dict):
        raise doc.fail(where, f"this is {_kind(body)}, and a table was wanted")
    _name(doc, where, word)
    table = _Table(doc, where, body)

    params = tuple(
        _quantity(doc, f"{table.at('params')}[{index}]", text, profile)
        for index, text in enumerate(table.strings("params"))
    )
    if len(params) > 0xFF:
        raise doc.fail(table.at("params"), "a function takes at most 255 arguments")

    text = table.optional("returns")
    returns = _quantity(doc, table.at("returns"), text, profile) if text else None
    table.done()
    return HostFunction(word, params, returns)


def _unique(doc: _Doc, entities: list[Entity], functions: list[HostFunction]) -> None:
    """One name, one entry — and one hash, which is §4.4.1's obligation."""
    names = [entry.name for entry in (*entities, *functions)]
    if len(names) > 0xFF:
        raise doc.fail(
            "",
            f"this registry declares {len(names)} names, and a host's table "
            "holds 255",
        )
    seen: dict[str, str] = {}
    for entry in (*entities, *functions):
        if entry.name in seen:
            raise doc.fail(
                f"{seen[entry.name]}.{_quoted(entry.name)}",
                f"`{entry.name}` is declared twice",
            )
        seen[entry.name] = entry.kind
    hashes: dict[int, str] = {}
    for name in names:
        digest = fnv1a32(name)
        if digest in hashes:
            raise doc.fail(
                "",
                f"`{name}` and `{hashes[digest]}` have the same name hash",
                "A container carries the hash and not the name, so a "
                "loader could not tell them apart. Rename one.",
            )
        hashes[digest] = name


# -- what a command was given ------------------------------------------------


def path_from(flag: str | None, variable: str) -> Path | None:
    """§7.4: the flag, then the variable, then nothing. Nothing is searched for."""
    if flag:
        return Path(flag)
    value = os.environ.get(variable)
    return Path(value) if value else None


def given(profile: str | None, registry: str | None) -> tuple[Profile, Registry]:
    """The world a compilation runs in, from two paths that may be absent.

    With neither, this is a compilation against a world that declares
    nothing — legal per §6.5.4, and the reason a suffix or a host name is
    refused by name rather than compiled wrongly.
    """
    profile_path = path_from(profile, PROFILE_VARIABLE)
    registry_path = path_from(registry, REGISTRY_VARIABLE)
    world = read_profile(profile_path) if profile_path else NO_PROFILE
    if registry_path is None:
        return world, NO_REGISTRY
    if profile_path is None:
        raise WorldError(
            registry_path,
            "",
            "this registry names a profile, and none was given",
            (
                "Pass --profile, or set MCUSCRIPT_PROFILE. What a "
                "dimension means is the profile's.",
            ),
        )
    return world, read_registry(registry_path, world)
