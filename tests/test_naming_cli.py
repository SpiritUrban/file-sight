import json
import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

from filesight.cli import app

from helpers import make_file

runner = CliRunner()

VALID_CONFIG = """
config_version = "1.0"
default_profile = "myphotos"

[profiles.myphotos]
template = "{date}-{category}-{subject}"
language = "en"
max_filename_length = 90

[categories.receipts]
enabled = true
priority = 150
keywords_any = ["receipt", "invoice"]
"""


def write_config(tmp_path: Path, text: str = VALID_CONFIG) -> Path:
    path = tmp_path / "filesight.toml"
    path.write_text(text, encoding="utf-8")
    return path


# --- config commands ------------------------------------------------------

def test_config_init_creates_valid_file(tmp_path: Path) -> None:
    target = tmp_path / "photos.toml"
    result = runner.invoke(
        app, ["config", "init", "--profile", "photos", "--output", str(target)]
    )
    assert result.exit_code == 0
    assert target.is_file()
    check = runner.invoke(app, ["config", "validate", str(target)])
    assert check.exit_code == 0
    assert "valid" in check.output


def test_config_init_refuses_overwrite_without_force(tmp_path: Path) -> None:
    target = tmp_path / "c.toml"
    runner.invoke(app, ["config", "init", "--output", str(target)])
    again = runner.invoke(app, ["config", "init", "--output", str(target)])
    assert again.exit_code != 0
    assert "already exists" in again.output


def test_config_init_force_overwrites(tmp_path: Path) -> None:
    target = tmp_path / "c.toml"
    runner.invoke(app, ["config", "init", "--output", str(target)])
    again = runner.invoke(app, ["config", "init", "--output", str(target), "--force"])
    assert again.exit_code == 0


def test_config_validate_reports_errors(tmp_path: Path) -> None:
    bad = write_config(tmp_path, 'config_version = "9.9"\n')
    result = runner.invoke(app, ["config", "validate", str(bad)])
    assert result.exit_code == 3
    assert "invalid" in result.output.lower()


def test_config_show_displays_effective_profile(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    result = runner.invoke(app, ["config", "show", str(path)])
    assert result.exit_code == 0
    assert "Effective profile: myphotos" in result.output
    assert "{date}-{category}-{subject}" in result.output


def test_config_show_honors_profile_flag(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    result = runner.invoke(app, ["config", "show", str(path), "--profile", "compact"])
    assert result.exit_code == 0
    assert "Effective profile: compact" in result.output


def test_config_show_unknown_profile_fails(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    result = runner.invoke(app, ["config", "show", str(path), "--profile", "ghost"])
    assert result.exit_code == 2


# --- naming preview -------------------------------------------------------

def test_naming_preview_basic() -> None:
    result = runner.invoke(
        app,
        ["naming", "preview", "--caption",
         "A black dog running through snow near trees",
         "--profile", "photos", "--date", "2026-01-14"],
    )
    assert result.exit_code == 0
    assert "2026-01-14-animals-black-dog-snow.jpg" in result.output
    assert "Category: animals" in result.output


def test_naming_preview_template_override() -> None:
    result = runner.invoke(
        app,
        ["naming", "preview", "--caption", "A black dog running",
         "--template", "{subject}-{index}", "--index", "7"],
    )
    assert result.exit_code == 0
    assert "black-dog-007.jpg" in result.output


def test_naming_preview_rejects_unknown_template_variable() -> None:
    result = runner.invoke(
        app,
        ["naming", "preview", "--caption", "a dog", "--template", "{nope}"],
    )
    assert result.exit_code == 2
    assert "Unknown template variable" in result.output


def test_naming_preview_ukrainian_and_transliteration() -> None:
    uk = runner.invoke(
        app,
        ["naming", "preview", "--caption", "A black dog running through snow",
         "--template", "{category}-{subject}-{action}", "--language", "uk"],
    )
    assert uk.exit_code == 0
    assert "тварини-чорний-пес-біжить.jpg" in uk.output

    latin = runner.invoke(
        app,
        ["naming", "preview", "--caption", "A black dog running through snow",
         "--template", "{category}-{subject}-{action}", "--language", "uk",
         "--transliterate"],
    )
    assert latin.exit_code == 0
    assert "tvaryny-chornyi-pes-bizhyt.jpg" in latin.output


def test_naming_preview_uses_custom_config(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    result = runner.invoke(
        app,
        ["naming", "preview", "--caption", "a scanned invoice",
         "--config", str(path)],
    )
    assert result.exit_code == 0
    assert "Category: receipts" in result.output


def test_naming_preview_extension_preserved() -> None:
    result = runner.invoke(
        app,
        ["naming", "preview", "--caption", "a black dog", "--extension", ".PNG"],
    )
    assert result.exit_code == 0
    assert ".PNG" in result.output


# --- category explain -----------------------------------------------------

def test_category_explain_shows_reasoning() -> None:
    result = runner.invoke(
        app, ["category", "explain", "--caption", "A woman standing near a red car"]
    )
    assert result.exit_code == 0
    assert "Selected category: people" in result.output
    assert "keyword:woman" in result.output
    assert "keyword:car" in result.output
    assert "priority" in result.output.lower()


def test_category_explain_other() -> None:
    result = runner.invoke(
        app, ["category", "explain", "--caption", "zzzz qqqq"]
    )
    assert result.exit_code == 0
    assert "other" in result.output


def test_category_explain_uses_filename() -> None:
    result = runner.invoke(
        app,
        ["category", "explain", "--caption", "a blurry rectangle",
         "--original-name", "Screenshot_2026-07-20.png"],
    )
    assert result.exit_code == 0
    assert "screenshots" in result.output


# --- report rename-suggestions -------------------------------------------

def build_report(tmp_path: Path) -> Path:
    a = make_file(tmp_path / "IMG_1.jpg")
    report = {
        "schema_version": "1.1",
        "created_at": "2026-07-21T00:00:00Z",
        "source_directory": str(tmp_path),
        "recursive": False,
        "model": {"provider": "huggingface", "name": "fake", "device": "cpu"},
        "summary": {"discovered": 1, "processed": 1, "failed": 0,
                    "duration_seconds": 1.0},
        "files": [
            {
                "original_path": str(a),
                "original_name": a.name,
                "extension": ".jpg",
                "status": "success",
                "caption": "a black dog running through snow",
                "suggested_name": "black-dog-running-through-snow.jpg",
                "processing_time_ms": 5,
                "error": None,
            }
        ],
    }
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def test_report_transform_dry_run_changes_nothing(tmp_path: Path) -> None:
    report = build_report(tmp_path)
    before = report.read_text(encoding="utf-8")
    result = runner.invoke(
        app,
        ["report", "rename-suggestions", str(report), "--profile", "compact",
         "--dry-run"],
    )
    assert result.exit_code == 0
    assert "OLD:" in result.output and "NEW:" in result.output
    assert "no report was written" in result.output
    assert report.read_text(encoding="utf-8") == before


def test_report_transform_refuses_to_overwrite_source(tmp_path: Path) -> None:
    report = build_report(tmp_path)
    result = runner.invoke(
        app, ["report", "rename-suggestions", str(report), "--profile", "compact"]
    )
    assert result.exit_code != 0
    assert "Refusing to overwrite" in result.output


def test_report_transform_writes_new_file(tmp_path: Path) -> None:
    report = build_report(tmp_path)
    target = tmp_path / "new.json"
    result = runner.invoke(
        app,
        ["report", "rename-suggestions", str(report), "--profile", "compact",
         "--output", str(target)],
    )
    assert result.exit_code == 0
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["files"][0]["suggested_name"] == "black-dog-running.jpg"
    assert data["naming_configuration"]["profile"] == "compact"


def test_report_transform_overwrite_flag(tmp_path: Path) -> None:
    report = build_report(tmp_path)
    result = runner.invoke(
        app,
        ["report", "rename-suggestions", str(report), "--profile", "compact",
         "--overwrite"],
    )
    assert result.exit_code == 0
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["files"][0]["suggested_name"] == "black-dog-running.jpg"


# --- scan flag plumbing ---------------------------------------------------

def test_scan_reports_profile_without_config(tmp_path: Path) -> None:
    result = runner.invoke(app, ["scan", str(tmp_path)])
    assert result.exit_code == 0
    assert "Profile: default (built-in)" in result.output


def test_scan_accepts_profile_and_template(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["scan", str(tmp_path), "--profile", "compact",
         "--template", "{subject}-{index}"],
    )
    assert result.exit_code == 0
    assert "Profile: compact" in result.output
    assert "{subject}-{index}" in result.output


def test_scan_rejects_unknown_profile(tmp_path: Path) -> None:
    result = runner.invoke(app, ["scan", str(tmp_path), "--profile", "ghost"])
    assert result.exit_code == 2


def test_scan_rejects_bad_template(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["scan", str(tmp_path), "--template", "{mystery}"]
    )
    assert result.exit_code == 2


def test_scan_uses_config_file(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    result = runner.invoke(app, ["scan", str(tmp_path), "--config", str(config)])
    assert result.exit_code == 0
    assert "Profile: myphotos" in result.output


# --- the no-ML guarantee --------------------------------------------------

NO_ML_SNIPPET = """
import sys
from typer.testing import CliRunner
from filesight.cli import app
CliRunner().invoke(app, {args})
heavy = [m for m in ("torch", "transformers") if m in sys.modules]
print("HEAVY:" + ",".join(heavy))
"""


def run_isolated(args: list[str]) -> str:
    """Run a CLI command in a fresh interpreter and report heavy imports."""
    code = NO_ML_SNIPPET.format(args=repr(args))
    completed = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=180
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


def test_naming_preview_does_not_load_ml() -> None:
    out = run_isolated(
        ["naming", "preview", "--caption", "a black dog running"]
    )
    assert "HEAVY:" in out and out.strip().endswith("HEAVY:")


def test_category_explain_does_not_load_ml() -> None:
    out = run_isolated(["category", "explain", "--caption", "a black dog"])
    assert out.strip().endswith("HEAVY:")


def test_config_validate_does_not_load_ml(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    out = run_isolated(["config", "validate", str(path)])
    assert out.strip().endswith("HEAVY:")
