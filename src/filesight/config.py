"""FileSight TOML configuration: loading, validation, profile resolution.

Reading uses the stdlib ``tomllib`` only — no heavy dependency. Nothing
here imports PyTorch, so config/preview/explain commands stay instant.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from filesight.categories import CategoryRule, default_rules
from filesight.constants import (
    MAX_FILENAME_LENGTH_LIMIT,
    MAX_INDEX_PADDING,
    MIN_FILENAME_LENGTH,
)
from filesight.localization import SUPPORTED_LANGUAGES
from filesight.models import ValidationIssue
from filesight.profiles import (
    BUILT_IN_PROFILES,
    SUPPORTED_CASE_STYLES,
    SUPPORTED_INDEX_SCOPES,
    SUPPORTED_SEPARATORS,
    NamingProfile,
    built_in_profile,
)
from filesight.templates import unknown_variables

CONFIG_FILE_NAME = "filesight.toml"
SUPPORTED_CONFIG_VERSIONS = {"1.0"}

_PROFILE_FIELDS = {
    "template": str,
    "language": str,
    "separator": str,
    "case_style": str,
    "transliterate": bool,
    "max_filename_length": int,
    "max_objects": int,
    "max_caption_words": int,
    "objects_separator": str,
    "date_format": str,
    "time_format": str,
    "index_start": int,
    "index_padding": int,
    "index_scope": str,
    "clean_original_stem": bool,
    "allow_original_stem_fallback": bool,
}

_CATEGORY_FIELDS = {
    "enabled": bool,
    "priority": int,
    "keywords": list,
    "keywords_any": list,
    "keywords_all": list,
    "filename_contains": list,
    "extensions": list,
    "media_types": list,
    "caption_contains": list,
    "min_matches": int,
}


class ConfigError(Exception):
    """The configuration cannot be used at all."""


@dataclass
class FileSightConfig:
    """A loaded configuration (or the built-in defaults)."""

    source: str = "built-in"
    config_version: Optional[str] = None
    default_profile: str = "default"
    profiles: dict[str, NamingProfile] = field(default_factory=dict)
    category_rules: list[CategoryRule] = field(default_factory=default_rules)
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    def profile_names(self) -> list[str]:
        return sorted(set(BUILT_IN_PROFILES) | set(self.profiles))

    def resolve_profile(self, name: Optional[str] = None) -> NamingProfile:
        """Pick a profile: explicit name -> default_profile -> 'default'.

        User profiles override built-ins of the same name.
        """
        wanted = name or self.default_profile or "default"
        if wanted in self.profiles:
            return self.profiles[wanted]
        built_in = built_in_profile(wanted)
        if built_in is not None:
            return built_in
        raise ConfigError(
            f"Profile '{wanted}' is not defined. Available: "
            + ", ".join(self.profile_names())
        )


def default_config() -> FileSightConfig:
    """The built-in configuration used when no TOML file is present."""
    return FileSightConfig(source="built-in")


def find_config_file(explicit: Optional[Path] = None) -> Optional[Path]:
    """Explicit path, else ./filesight.toml, else None (built-in defaults)."""
    if explicit is not None:
        return explicit
    candidate = Path.cwd() / CONFIG_FILE_NAME
    return candidate if candidate.is_file() else None


def load_config(path: Optional[Path], strict: bool = False) -> FileSightConfig:
    """Load and validate a config file. Raises ConfigError on fatal problems."""
    if path is None:
        return default_config()
    if not path.exists():
        raise ConfigError(f"Config file does not exist: {path}")
    if not path.is_file():
        raise ConfigError(f"Config path is not a file: {path}")
    try:
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Config is not valid TOML: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"Cannot read config {path}: {exc}") from exc

    config = parse_config(data, source=str(path))
    if config.errors:
        details = "\n".join(f"  [{i.code}] {i.message}" for i in config.errors)
        raise ConfigError(f"Invalid configuration in {path}:\n{details}")
    if strict and config.warnings:
        details = "\n".join(f"  [{i.code}] {i.message}" for i in config.warnings)
        raise ConfigError(f"Configuration warnings (strict mode) in {path}:\n{details}")
    return config


def parse_config(data: dict[str, Any], source: str = "memory") -> FileSightConfig:
    """Validate a parsed TOML mapping. Collects issues instead of raising."""
    issues: list[ValidationIssue] = []

    def error(code: str, message: str) -> None:
        issues.append(ValidationIssue("error", code, message))

    def warn(code: str, message: str) -> None:
        issues.append(ValidationIssue("warning", code, message))

    version = data.get("config_version")
    if version is None:
        error("MISSING_CONFIG_VERSION", "config_version is required (e.g. \"1.0\").")
    elif not isinstance(version, str):
        error("INVALID_CONFIG_VERSION", "config_version must be a string.")
    elif version not in SUPPORTED_CONFIG_VERSIONS:
        error(
            "UNSUPPORTED_CONFIG_VERSION",
            f"Unsupported config_version {version!r}. Supported: "
            + ", ".join(sorted(SUPPORTED_CONFIG_VERSIONS)),
        )

    for key in data:
        if key not in ("config_version", "default_profile", "profiles", "categories"):
            warn("UNKNOWN_KEY", f"Unknown top-level key: {key}")

    profiles = _parse_profiles(data.get("profiles"), issues)
    rules = _parse_categories(data.get("categories"), issues)

    default_profile = data.get("default_profile", "default")
    if not isinstance(default_profile, str):
        error("INVALID_DEFAULT_PROFILE", "default_profile must be a string.")
        default_profile = "default"
    elif default_profile not in profiles and default_profile not in BUILT_IN_PROFILES:
        error(
            "MISSING_DEFAULT_PROFILE",
            f"default_profile '{default_profile}' is not defined in "
            "[profiles] and is not a built-in profile.",
        )

    return FileSightConfig(
        source=source,
        config_version=version if isinstance(version, str) else None,
        default_profile=default_profile,
        profiles=profiles,
        category_rules=rules,
        issues=issues,
    )


def _parse_profiles(
    raw: Any, issues: list[ValidationIssue]
) -> dict[str, NamingProfile]:
    profiles: dict[str, NamingProfile] = {}
    if raw is None:
        return profiles
    if not isinstance(raw, dict):
        issues.append(
            ValidationIssue("error", "INVALID_PROFILES", "[profiles] must be a table.")
        )
        return profiles

    for name, body in raw.items():
        if not isinstance(body, dict):
            issues.append(
                ValidationIssue(
                    "error", "INVALID_PROFILE", f"Profile '{name}' must be a table."
                )
            )
            continue
        # start from the built-in of the same name so users can override partially
        base = built_in_profile(name) or NamingProfile()
        overrides: dict[str, Any] = {}
        for key, value in body.items():
            expected = _PROFILE_FIELDS.get(key)
            if expected is None:
                issues.append(
                    ValidationIssue(
                        "warning",
                        "UNKNOWN_PROFILE_KEY",
                        f"Profile '{name}': unknown key '{key}'.",
                    )
                )
                continue
            if expected is int and isinstance(value, bool):
                ok = False
            elif expected is int:
                ok = isinstance(value, int)
            else:
                ok = isinstance(value, expected)
            if not ok:
                issues.append(
                    ValidationIssue(
                        "error",
                        "INVALID_TYPE",
                        f"Profile '{name}': '{key}' must be "
                        f"{expected.__name__}, got {type(value).__name__}.",
                    )
                )
                continue
            overrides[key] = value

        profile = base.merged_with(overrides)
        profile.name = name
        _validate_profile(profile, issues)
        profiles[name] = profile
    return profiles


def _validate_profile(profile: NamingProfile, issues: list[ValidationIssue]) -> None:
    name = profile.name

    def error(code: str, message: str) -> None:
        issues.append(ValidationIssue("error", code, f"Profile '{name}': {message}"))

    if not profile.template or not profile.template.strip():
        error("EMPTY_TEMPLATE", "template must not be empty.")
    else:
        unknown = unknown_variables(profile.template)
        if unknown:
            error(
                "UNKNOWN_TEMPLATE_VARIABLE",
                "unknown template variable(s): " + ", ".join(sorted(set(unknown))),
            )
    if profile.language not in SUPPORTED_LANGUAGES:
        error(
            "INVALID_LANGUAGE",
            f"language must be one of {', '.join(SUPPORTED_LANGUAGES)}.",
        )
    if profile.separator not in SUPPORTED_SEPARATORS:
        error("INVALID_SEPARATOR", "separator must be '-', '_' or ' '.")
    if profile.case_style not in SUPPORTED_CASE_STYLES:
        error(
            "INVALID_CASE_STYLE",
            f"case_style must be one of {', '.join(SUPPORTED_CASE_STYLES)}.",
        )
    if not (MIN_FILENAME_LENGTH <= profile.max_filename_length <= MAX_FILENAME_LENGTH_LIMIT):
        error(
            "INVALID_MAX_LENGTH",
            f"max_filename_length must be between {MIN_FILENAME_LENGTH} and "
            f"{MAX_FILENAME_LENGTH_LIMIT}.",
        )
    if not (0 <= profile.max_objects <= 10):
        error("INVALID_MAX_OBJECTS", "max_objects must be between 0 and 10.")
    if not (0 <= profile.max_caption_words <= 30):
        error("INVALID_MAX_CAPTION_WORDS", "max_caption_words must be 0..30.")
    if not (1 <= profile.index_padding <= MAX_INDEX_PADDING):
        error(
            "INVALID_INDEX_PADDING",
            f"index_padding must be between 1 and {MAX_INDEX_PADDING}.",
        )
    if profile.index_start < 0:
        error("INVALID_INDEX_START", "index_start must be >= 0.")
    if profile.index_scope not in SUPPORTED_INDEX_SCOPES:
        error(
            "INVALID_INDEX_SCOPE",
            f"index_scope must be one of {', '.join(SUPPORTED_INDEX_SCOPES)}.",
        )
    for field_name, value in (
        ("date_format", profile.date_format),
        ("time_format", profile.time_format),
    ):
        problem = _validate_strftime(value)
        if problem:
            error("INVALID_DATE_FORMAT", f"{field_name}: {problem}")


def _validate_strftime(fmt: str) -> Optional[str]:
    """Reject formats that fail or produce Windows-forbidden characters."""
    from datetime import datetime

    if not fmt:
        return "must not be empty."
    try:
        rendered = datetime(2026, 7, 21, 18, 42, 10).strftime(fmt)
    except (ValueError, TypeError) as exc:
        return f"invalid strftime format ({exc})."
    if not rendered:
        return "produces an empty string."
    forbidden = [c for c in '<>:"/\\|?*' if c in rendered]
    if forbidden:
        return (
            "produces characters that are forbidden in Windows file names: "
            + " ".join(sorted(set(forbidden)))
        )
    return None


def _parse_categories(raw: Any, issues: list[ValidationIssue]) -> list[CategoryRule]:
    rules = default_rules()
    if raw is None:
        return rules
    if not isinstance(raw, dict):
        issues.append(
            ValidationIssue(
                "error", "INVALID_CATEGORIES", "[categories] must be a table."
            )
        )
        return rules

    by_name = {rule.name: rule for rule in rules}
    next_order = len(rules)
    seen: set[str] = set()

    for name, body in raw.items():
        normalized = name.strip().lower()
        if not normalized or not normalized.replace("_", "").replace("-", "").isalnum():
            issues.append(
                ValidationIssue(
                    "error",
                    "INVALID_CATEGORY_NAME",
                    f"Invalid category name: {name!r}",
                )
            )
            continue
        if normalized in seen:
            issues.append(
                ValidationIssue(
                    "error",
                    "DUPLICATE_CATEGORY",
                    f"Duplicate category after normalization: {normalized}",
                )
            )
            continue
        seen.add(normalized)
        if not isinstance(body, dict):
            issues.append(
                ValidationIssue(
                    "error",
                    "INVALID_CATEGORY",
                    f"Category '{name}' must be a table.",
                )
            )
            continue

        existing = by_name.get(normalized)
        rule = existing or CategoryRule(name=normalized, order=next_order)
        if existing is None:
            next_order += 1

        for key, value in body.items():
            expected = _CATEGORY_FIELDS.get(key)
            if expected is None:
                issues.append(
                    ValidationIssue(
                        "warning",
                        "UNKNOWN_CATEGORY_KEY",
                        f"Category '{normalized}': unknown key '{key}'.",
                    )
                )
                continue
            if expected is int and isinstance(value, bool):
                ok = False
            elif expected is int:
                ok = isinstance(value, int)
            else:
                ok = isinstance(value, expected)
            if not ok:
                issues.append(
                    ValidationIssue(
                        "error",
                        "INVALID_TYPE",
                        f"Category '{normalized}': '{key}' must be "
                        f"{expected.__name__}, got {type(value).__name__}.",
                    )
                )
                continue
            if expected is list and not all(isinstance(v, str) for v in value):
                issues.append(
                    ValidationIssue(
                        "error",
                        "INVALID_TYPE",
                        f"Category '{normalized}': '{key}' must be a list of strings.",
                    )
                )
                continue
            _apply_category_field(rule, normalized, key, value, issues)

        by_name[normalized] = rule

    ordered = sorted(by_name.values(), key=lambda r: r.order)
    return ordered


def _apply_category_field(
    rule: CategoryRule,
    name: str,
    key: str,
    value: Any,
    issues: list[ValidationIssue],
) -> None:
    if key == "enabled":
        rule.enabled = value
    elif key == "priority":
        rule.priority = value
    elif key in ("keywords", "keywords_any"):
        rule.keywords_any = tuple(dict.fromkeys(tuple(rule.keywords_any) + tuple(value)))
    elif key == "keywords_all":
        rule.keywords_all = tuple(value)
    elif key == "filename_contains":
        rule.filename_contains = tuple(value)
    elif key == "caption_contains":
        rule.caption_contains = tuple(value)
    elif key == "min_matches":
        rule.min_matches = max(1, value)
    elif key == "extensions":
        bad = [e for e in value if not e.startswith(".")]
        if bad:
            issues.append(
                ValidationIssue(
                    "error",
                    "INVALID_EXTENSION",
                    f"Category '{name}': extensions must start with a dot: "
                    + ", ".join(bad),
                )
            )
            return
        rule.extensions = tuple(e.lower() for e in value)
    elif key == "media_types":
        bad = [m for m in value if m not in ("image", "video")]
        if bad:
            issues.append(
                ValidationIssue(
                    "error",
                    "INVALID_MEDIA_TYPE",
                    f"Category '{name}': media_types must be 'image'/'video': "
                    + ", ".join(bad),
                )
            )
            return
        rule.media_types = tuple(value)
