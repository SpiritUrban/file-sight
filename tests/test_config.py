from pathlib import Path

import pytest

from filesight.config import (
    ConfigError,
    default_config,
    find_config_file,
    load_config,
    parse_config,
)
from filesight.profiles import built_in_profile

VALID = """
config_version = "1.0"
default_profile = "photos"

[profiles.photos]
template = "{date}-{category}-{subject}"
language = "en"
max_filename_length = 100
"""


def write(tmp_path: Path, text: str, name: str = "filesight.toml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def codes(config) -> list[str]:
    return [i.code for i in config.errors]


def test_missing_config_uses_built_in_default() -> None:
    config = load_config(None)
    assert config.source == "built-in"
    profile = config.resolve_profile()
    assert profile.name == "default"
    assert profile.template == built_in_profile("default").template


def test_find_config_file_returns_none_when_absent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert find_config_file(None) is None


def test_find_config_file_picks_up_cwd_file(tmp_path: Path, monkeypatch) -> None:
    path = write(tmp_path, VALID)
    monkeypatch.chdir(tmp_path)
    assert find_config_file(None) == path


def test_valid_toml_loads(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, VALID))
    assert config.config_version == "1.0"
    assert config.default_profile == "photos"
    assert config.resolve_profile().template == "{date}-{category}-{subject}"


def test_broken_toml_is_fatal(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not valid TOML"):
        load_config(write(tmp_path, "config_version = \n[[["))


def test_unsupported_config_version(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="UNSUPPORTED_CONFIG_VERSION"):
        load_config(write(tmp_path, 'config_version = "9.9"\n'))


def test_missing_config_version(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="MISSING_CONFIG_VERSION"):
        load_config(write(tmp_path, 'default_profile = "default"\n'))


def test_missing_default_profile(tmp_path: Path) -> None:
    text = 'config_version = "1.0"\ndefault_profile = "nope"\n'
    with pytest.raises(ConfigError, match="MISSING_DEFAULT_PROFILE"):
        load_config(write(tmp_path, text))


def test_unknown_template_variable() -> None:
    config = parse_config(
        {
            "config_version": "1.0",
            "profiles": {"p": {"template": "{subject}-{nope}"}},
            "default_profile": "p",
        }
    )
    assert "UNKNOWN_TEMPLATE_VARIABLE" in codes(config)


def test_empty_template_rejected() -> None:
    config = parse_config(
        {"config_version": "1.0", "profiles": {"p": {"template": "  "}},
         "default_profile": "p"}
    )
    assert "EMPTY_TEMPLATE" in codes(config)


def test_invalid_language() -> None:
    config = parse_config(
        {"config_version": "1.0", "profiles": {"p": {"language": "de"}},
         "default_profile": "p"}
    )
    assert "INVALID_LANGUAGE" in codes(config)


def test_invalid_separator() -> None:
    config = parse_config(
        {"config_version": "1.0", "profiles": {"p": {"separator": "//"}},
         "default_profile": "p"}
    )
    assert "INVALID_SEPARATOR" in codes(config)


def test_invalid_case_style() -> None:
    config = parse_config(
        {"config_version": "1.0", "profiles": {"p": {"case_style": "shout"}},
         "default_profile": "p"}
    )
    assert "INVALID_CASE_STYLE" in codes(config)


@pytest.mark.parametrize("value", [5, 5000])
def test_invalid_max_filename_length(value: int) -> None:
    config = parse_config(
        {"config_version": "1.0",
         "profiles": {"p": {"max_filename_length": value}}, "default_profile": "p"}
    )
    assert "INVALID_MAX_LENGTH" in codes(config)


def test_invalid_index_scope_and_padding() -> None:
    config = parse_config(
        {"config_version": "1.0",
         "profiles": {"p": {"index_scope": "planet", "index_padding": 99}},
         "default_profile": "p"}
    )
    assert "INVALID_INDEX_SCOPE" in codes(config)
    assert "INVALID_INDEX_PADDING" in codes(config)


def test_wrong_type_is_an_error() -> None:
    config = parse_config(
        {"config_version": "1.0",
         "profiles": {"p": {"max_filename_length": "lots"}}, "default_profile": "p"}
    )
    assert "INVALID_TYPE" in codes(config)


def test_date_format_producing_forbidden_characters() -> None:
    config = parse_config(
        {"config_version": "1.0",
         "profiles": {"p": {"date_format": "%Y/%m/%d"}}, "default_profile": "p"}
    )
    assert "INVALID_DATE_FORMAT" in codes(config)


def test_unknown_keys_are_warnings_not_errors() -> None:
    config = parse_config(
        {"config_version": "1.0", "surprise": 1,
         "profiles": {"default": {"nope": 5}}}
    )
    assert config.errors == []
    warn_codes = [i.code for i in config.warnings]
    assert "UNKNOWN_KEY" in warn_codes
    assert "UNKNOWN_PROFILE_KEY" in warn_codes


def test_strict_mode_turns_warnings_into_failure(tmp_path: Path) -> None:
    text = 'config_version = "1.0"\nmystery = 1\n'
    load_config(write(tmp_path, text))  # fine without strict
    with pytest.raises(ConfigError, match="strict"):
        load_config(write(tmp_path, text), strict=True)


def test_user_profile_overrides_built_in() -> None:
    config = parse_config(
        {
            "config_version": "1.0",
            "default_profile": "compact",
            "profiles": {"compact": {"template": "{category}-{index}"}},
        }
    )
    assert config.errors == []
    profile = config.resolve_profile("compact")
    assert profile.template == "{category}-{index}"
    # untouched fields still come from the built-in compact profile
    assert profile.max_filename_length == 70


def test_partial_profile_inherits_built_in_defaults() -> None:
    config = parse_config(
        {"config_version": "1.0", "profiles": {"photos": {"language": "uk"}},
         "default_profile": "photos"}
    )
    profile = config.resolve_profile("photos")
    assert profile.language == "uk"
    assert profile.template == built_in_profile("photos").template


def test_resolve_unknown_profile_raises() -> None:
    with pytest.raises(ConfigError, match="not defined"):
        default_config().resolve_profile("ghost")


def test_built_in_profiles_all_resolve() -> None:
    config = default_config()
    for name in ("default", "photos", "compact", "archive", "screenshots"):
        assert config.resolve_profile(name).name == name
