# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0
"""Reading a profile and a registry — §7.

Two kinds of test. The first says that a good file becomes the model the
rest of the front end works against; there is only one of those, because
`homeprofile.py` is that test run by every other module in this
directory. The rest are refusals, one per row of §7.2.5 and §7.3.4,
because a format whose reader is strict is only as good as the list of
things it is strict about.
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import pytest
from homeprofile import HOME

from mcuscript import hostheader
from mcuscript.opcodes import ValType
from mcuscript.world import (
    PROFILE_VARIABLE,
    REGISTRY_VARIABLE,
    WorldError,
    given,
    path_from,
    read_profile,
    read_registry,
)

MINIMAL = """
format = 1

[profile]
name = "small"
id = 7
version = "1.2"

[dimension.temperature]
id = 1
type = "i32"
base_unit = "c°C"

[dimension.temperature.units]
"c°C" = 1
"°C" = 100
"""

REGISTRY = """
format = 1

[profile]
id = 7
version = "1.2"

[entity."sensor.temp"]
quantity = "temperature"
"""


def write(tmp_path: Path, text: str, name: str = "profile.toml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def refused(tmp_path: Path, text: str) -> str:
    with pytest.raises(WorldError) as caught:
        read_profile(write(tmp_path, text))
    return str(caught.value)


def refused_registry(tmp_path: Path, text: str, profile=None) -> str:
    with pytest.raises(WorldError) as caught:
        read_registry(
            write(tmp_path, text, "registry.toml"),
            profile if profile is not None else read_profile(write(tmp_path, MINIMAL)),
        )
    return str(caught.value)


# -- what a good file becomes ------------------------------------------------


def test_a_profile_becomes_the_table_the_front_end_reads(tmp_path):
    profile = read_profile(write(tmp_path, MINIMAL))
    assert (profile.name, profile.id, profile.version) == ("small", 7, "1.2")
    assert (profile.major, profile.minor) == (1, 2)
    dimension = profile.find_dimension("temperature")
    assert dimension is not None
    assert (dimension.id, dimension.type, dimension.base_unit) == (
        1,
        ValType.I32,
        "c°C",
    )
    assert profile.find_unit("°C") == (dimension, dimension.unit("°C"))


def test_the_home_fixture_is_the_format_read_for_real():
    """Every other test in this directory compiles against a file."""
    assert HOME.id == 1
    assert HOME.find_unit("°F")[1].offset == Fraction(-16000, 9)
    assert HOME.instant is not None and HOME.time_of_day is not None


# -- §7.2.1 the header -------------------------------------------------------


def test_a_file_without_a_format_is_refused(tmp_path):
    assert "`format` is missing" in refused(tmp_path, MINIMAL.replace("format = 1", ""))


def test_a_format_this_reader_does_not_know_is_refused(tmp_path):
    text = refused(tmp_path, MINIMAL.replace("format = 1", "format = 2"))
    assert "format 2" in text and "knows 1" in text


def test_the_dimensionless_profile_id_is_not_available(tmp_path):
    assert "outside 1 to" in refused(tmp_path, MINIMAL.replace("id = 7", "id = 0", 1))


def test_a_version_that_is_not_two_numbers_is_refused(tmp_path):
    assert "not a version" in refused(
        tmp_path, MINIMAL.replace('version = "1.2"', 'version = "1.2.3"')
    )


def test_a_key_that_means_nothing_is_refused_rather_than_skipped(tmp_path):
    text = refused(tmp_path, MINIMAL.replace("id = 1\n", "id = 1\nidd = 2\n"))
    assert "means nothing here" in text and "Did you mean `id`?" in text


def test_a_file_that_is_not_toml_says_so(tmp_path):
    assert "not readable TOML" in refused(tmp_path, "format = = 1\n")


# -- §7.2.2 a dimension ------------------------------------------------------


def test_a_dimension_may_not_be_called_after_a_type(tmp_path):
    text = refused(tmp_path, MINIMAL.replace("dimension.temperature", "dimension.i32"))
    assert "`i32` is a type" in text


def test_a_dimension_may_not_be_called_after_a_keyword(tmp_path):
    assert "cannot be a dimension's name" in refused(
        tmp_path, MINIMAL.replace("dimension.temperature", "dimension.match")
    )


def test_the_dimensionless_dimension_id_is_not_available(tmp_path):
    assert "outside 1 to 65535" in refused(
        tmp_path, MINIMAL.replace("id = 1", "id = 0")
    )


def test_two_dimensions_may_not_share_an_id(tmp_path):
    """A container records an import's dimension as that number (§4.4)."""
    assert "both dimension 1" in refused(
        tmp_path,
        MINIMAL
        + """
[dimension.humidity]
id = 1
type = "i32"
base_unit = "pct"
""",
    )


def test_a_dimension_is_not_held_in_a_yes_or_no(tmp_path):
    assert "not a type a dimension may be held in" in refused(
        tmp_path, MINIMAL.replace('type = "i32"', 'type = "bool"')
    )


def test_a_base_unit_is_one_word(tmp_path):
    assert "cannot be a base unit" in refused(
        tmp_path, MINIMAL.replace('base_unit = "c°C"', 'base_unit = "hundredths of °C"')
    )


def test_a_base_unit_need_not_be_a_unit_a_script_can_write(tmp_path):
    """§6.5.4: a script never names it, so `_` in it costs nothing."""
    profile = read_profile(
        write(tmp_path, MINIMAL.replace('base_unit = "c°C"', 'base_unit = "ms_utc"'))
    )
    assert profile.find_dimension("temperature").base_unit == "ms_utc"


# -- §7.2.3 units ------------------------------------------------------------


def test_a_unit_is_spelled_in_the_lexers_alphabet(tmp_path):
    assert "cannot be a unit" in refused(
        tmp_path, MINIMAL.replace('"°C" = 100', '"deg_c" = 100')
    )


def test_one_spelling_belongs_to_one_dimension(tmp_path):
    assert "belongs to both" in refused(
        tmp_path,
        MINIMAL
        + """
[dimension.outside]
id = 2
type = "i32"
base_unit = "c°C"

[dimension.outside.units]
"°C" = 100
""",
    )


def test_a_factor_written_as_a_decimal_number_is_refused(tmp_path):
    text = refused(tmp_path, MINIMAL.replace('"°C" = 100', '"°C" = 100.0'))
    assert "has to be exact" in text and 'Write it as text: "100.0"' in text


def test_a_factor_may_be_a_ratio_or_a_decimal_string(tmp_path):
    profile = read_profile(
        write(
            tmp_path,
            MINIMAL.replace('"°C" = 100', '"°F" = { factor = "500/9", offset = "0.5" }'),
        )
    )
    unit = profile.find_unit("°F")[1]
    assert (unit.factor, unit.offset) == (Fraction(500, 9), Fraction(1, 2))


def test_a_factor_that_is_not_a_number_says_what_one_looks_like(tmp_path):
    text = refused(tmp_path, MINIMAL.replace('"°C" = 100', '"°C" = "a hundred"'))
    assert "is not a number" in text and '"500/9"' in text


def test_a_unit_cannot_be_worth_nothing(tmp_path):
    assert "cannot be 0" in refused(tmp_path, MINIMAL.replace('"°C" = 100', '"°C" = 0'))


def test_a_unit_cannot_be_worth_less_than_nothing(tmp_path):
    assert "cannot be -1" in refused(
        tmp_path, MINIMAL.replace('"°C" = 100', '"°C" = -1')
    )


# -- §7.2.4 the marks --------------------------------------------------------


CLOCK = """
[dimension.instant]
id = 9
type = "i64"
base_unit = "ms_utc"
calendar = { epoch = "1970-01-01 00:00:00", second = 1000 }
"""


def test_an_epoch_is_a_moment_and_the_second_is_a_factor(tmp_path):
    profile = read_profile(write(tmp_path, MINIMAL + CLOCK))
    clock = profile.instant.clock
    assert (clock.epoch, clock.second) == (0, Fraction(1000))
    assert profile.time_of_day is None


def test_an_epoch_before_1970_is_negative(tmp_path):
    profile = read_profile(
        write(tmp_path, MINIMAL + CLOCK.replace("1970-01-01", "1969-12-31"))
    )
    assert profile.instant.clock.epoch == -86400


def test_a_dimension_without_an_epoch_takes_the_times_of_day(tmp_path):
    profile = read_profile(
        write(
            tmp_path,
            MINIMAL
            + CLOCK.replace('epoch = "1970-01-01 00:00:00", ', ""),
        )
    )
    assert profile.time_of_day is not None and profile.instant is None


def test_an_epoch_that_is_only_a_time_is_refused(tmp_path):
    assert "an epoch is a day" in refused(
        tmp_path, MINIMAL + CLOCK.replace('"1970-01-01 00:00:00"', '"13:25"')
    )


def test_an_epoch_that_is_not_a_day_says_which_field(tmp_path):
    assert "there is no month 13" in refused(
        tmp_path, MINIMAL + CLOCK.replace("1970-01-01", "1970-13-01")
    )


def test_two_dimensions_cannot_both_take_a_date(tmp_path):
    text = MINIMAL + CLOCK + CLOCK.replace("instant", "other").replace("id = 9", "id = 10")
    assert "two dimensions take a date" in refused(tmp_path, text)


def test_a_ratio_is_not_a_calendar(tmp_path):
    assert "not a calendar" in refused(
        tmp_path, MINIMAL + CLOCK + "scale = true\n"
    )


def test_a_ratio_does_not_wrap(tmp_path):
    assert "does not wrap" in refused(
        tmp_path, MINIMAL.replace('type = "i32"', 'type = "i32"\ncyclic = true\nscale = true')
    )


# -- §7.3 the registry -------------------------------------------------------


def test_a_registry_becomes_what_a_script_may_reach(tmp_path):
    profile = read_profile(write(tmp_path, MINIMAL))
    registry = read_registry(write(tmp_path, REGISTRY, "registry.toml"), profile)
    entity = registry.find("sensor.temp")
    assert entity.quantity.dimension is profile.find_dimension("temperature")
    assert (entity.readable, entity.writable) == (True, False)


def test_a_registry_for_another_profile_is_refused(tmp_path):
    assert "written against profile 8" in refused_registry(
        tmp_path, REGISTRY.replace("id = 7", "id = 8")
    )


def test_a_registry_for_another_major_version_is_refused(tmp_path):
    assert "written against profile 7 2.0" in refused_registry(
        tmp_path, REGISTRY.replace('version = "1.2"', 'version = "2.0"')
    )


def test_a_registry_newer_than_the_profile_is_refused(tmp_path):
    assert "needs profile 7 1.3" in refused_registry(
        tmp_path, REGISTRY.replace('version = "1.2"', 'version = "1.3"')
    )


def test_a_registry_older_than_the_profile_is_read(tmp_path):
    """A profile that only added dimensions did not move the world."""
    profile = read_profile(write(tmp_path, MINIMAL.replace('version = "1.2"', 'version = "1.9"')))
    registry = read_registry(write(tmp_path, REGISTRY, "registry.toml"), profile)
    assert registry.names == ("sensor.temp",)


def test_a_name_a_script_cannot_write_is_refused(tmp_path):
    assert "is not a name a script can write" in refused_registry(
        tmp_path, REGISTRY.replace("sensor.temp", "sensor temp")
    )


def test_a_name_may_not_begin_with_one_of_the_languages_words(tmp_path):
    assert "is not a name a script can write" in refused_registry(
        tmp_path, REGISTRY.replace("sensor.temp", "match.temp")
    )


def test_a_part_after_a_dot_may_be_one_of_them(tmp_path):
    """`fan.on()` is the most ordinary line anyone will write."""
    profile = read_profile(write(tmp_path, MINIMAL))
    registry = read_registry(
        write(tmp_path, REGISTRY.replace("sensor.temp", "fan.on"), "registry.toml"),
        profile,
    )
    assert registry.find("fan.on") is not None


def test_a_quantity_that_is_neither_says_what_is_near(tmp_path):
    text = refused_registry(
        tmp_path, REGISTRY.replace('quantity = "temperature"', 'quantity = "temprature"')
    )
    assert "is not a dimension or a type" in text and "temperature" in text


def test_an_access_that_is_not_one_of_the_three_is_refused(tmp_path):
    assert "is not an access" in refused_registry(
        tmp_path, REGISTRY + 'access = "sometimes"\n'
    )


def test_one_name_is_declared_once(tmp_path):
    assert "declared twice" in refused_registry(
        tmp_path,
        REGISTRY + '\n[function."sensor.temp"]\n',
    )


def test_two_names_with_one_hash_are_refused(tmp_path):
    """§4.4.1's obligation on the embedder, checkable here and nowhere else."""
    text = refused_registry(
        tmp_path,
        REGISTRY
        + """
[entity."sensor.mlbvs"]
quantity = "i32"

[entity."sensor.sacxa"]
quantity = "i32"
""",
    )
    assert "same name hash" in text and "Rename one" in text


def test_a_function_carries_its_parameters(tmp_path):
    profile = read_profile(write(tmp_path, MINIMAL))
    registry = read_registry(
        write(
            tmp_path,
            REGISTRY
            + """
[function."math.log"]
params = ["f32"]
returns = "f32"
""",
            "registry.toml",
        ),
        profile,
    )
    function = registry.find("math.log")
    assert function.params[0].type is ValType.F32
    assert function.returns.type is ValType.F32


def test_a_host_table_holds_255_names(tmp_path):
    entries = "\n".join(
        f'[entity.e{index}]\nquantity = "i32"\n' for index in range(256)
    )
    assert "and a host's table holds 255" in refused_registry(
        tmp_path, REGISTRY + "\n" + entries
    )


# -- §7.4 how a command is given them ----------------------------------------


def test_a_flag_beats_the_variable(monkeypatch):
    monkeypatch.setenv(PROFILE_VARIABLE, "from-the-environment.toml")
    assert path_from("from-the-flag.toml", PROFILE_VARIABLE) == Path(
        "from-the-flag.toml"
    )
    assert path_from(None, PROFILE_VARIABLE) == Path("from-the-environment.toml")


def test_neither_is_a_world_that_declares_nothing(monkeypatch):
    monkeypatch.delenv(PROFILE_VARIABLE, raising=False)
    monkeypatch.delenv(REGISTRY_VARIABLE, raising=False)
    profile, registry = given(None, None)
    assert profile.dimensions == () and registry.names == ()


def test_a_registry_without_a_profile_is_refused(tmp_path, monkeypatch):
    monkeypatch.delenv(PROFILE_VARIABLE, raising=False)
    path = write(tmp_path, REGISTRY, "registry.toml")
    with pytest.raises(WorldError) as caught:
        given(None, str(path))
    assert "none was given" in str(caught.value)


# -- §7.5 the host's table ---------------------------------------------------


def test_the_header_carries_the_table_the_loader_resolves(tmp_path):
    profile = read_profile(write(tmp_path, MINIMAL))
    registry = read_registry(write(tmp_path, REGISTRY, "registry.toml"), profile)
    text = hostheader.generate(registry, tmp_path / "imports.h", source="registry.toml")
    assert "#ifndef MCUSCRIPT_IMPORTS_H" in text
    assert "MCUSCRIPT_IMPORT_SENSOR_TEMP = 0," in text
    assert "MCUSCRIPT_IMPORT_COUNT = 1" in text
    assert (
        '{ "sensor.temp", MCUSCRIPT_KIND_ENTITY, MCUSCRIPT_ACCESS_READ, '
        "MCUSCRIPT_I32, 1, 0, NULL }," in text
    )


def test_a_name_the_enum_needs_for_itself_is_refused(tmp_path):
    """`MCUSCRIPT_IMPORT_COUNT` is how many there are, not one of them."""
    profile = read_profile(write(tmp_path, MINIMAL))
    registry = read_registry(
        write(tmp_path, REGISTRY + '\n[entity.count]\nquantity = "i32"\n', "registry.toml"),
        profile,
    )
    with pytest.raises(hostheader.NameCollision):
        hostheader.generate(registry, tmp_path / "imports.h")


def test_a_function_parameter_list_that_is_not_one_is_refused(tmp_path):
    assert "a list of quantities was wanted" in refused_registry(
        tmp_path, REGISTRY + '\n[function."fan.set"]\nparams = 0\n'
    )


def test_two_names_that_become_one_c_name_are_refused(tmp_path):
    profile = read_profile(write(tmp_path, MINIMAL))
    registry = read_registry(
        write(
            tmp_path,
            REGISTRY + '\n[entity.sensor_temp]\nquantity = "i32"\n',
            "registry.toml",
        ),
        profile,
    )
    with pytest.raises(hostheader.NameCollision) as caught:
        hostheader.generate(registry, tmp_path / "imports.h")
    assert "rename one" in str(caught.value)


def test_the_generated_header_compiles(cc, tmp_path):
    """The point of generating it: what is wrong is wrong out loud."""
    import subprocess

    from homeprofile import REGISTRY as HOME_REGISTRY

    header = tmp_path / "imports.h"
    hostheader.write(HOME_REGISTRY, header, source="home-registry.toml")
    unit = tmp_path / "use.c"
    unit.write_text(
        '#include "imports.h"\n'
        "const mcuscript_import *first(void) { return &mcuscript_imports[0]; }\n"
        "unsigned char how_many(void) { return MCUSCRIPT_IMPORT_COUNT; }\n",
        encoding="utf-8",
    )
    runtime = Path(__file__).resolve().parents[2] / "runtime" / "include"
    built = subprocess.run(
        [cc, "-std=c99", "-Wall", "-Wextra", "-Werror", "-c", str(unit),
         f"-I{tmp_path}", f"-I{runtime}", "-o", str(tmp_path / "use.o")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert built.returncode == 0, built.stderr
