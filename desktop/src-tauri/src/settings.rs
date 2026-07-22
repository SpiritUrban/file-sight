//! Persisted application settings and the on-disk log file.

use std::fs;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default)]
pub struct AppSettings {
    pub python_path: Option<String>,
    pub ffmpeg_path: Option<String>,
    pub ffprobe_path: Option<String>,
    pub config_path: Option<String>,
    pub default_profile: String,
    pub default_recursive: bool,
    pub default_include_videos: bool,
    pub report_filename: String,
    pub last_directory: Option<String>,
    pub last_report_path: Option<String>,
    pub last_log_path: Option<String>,
    pub onboarding_seen: bool,
    pub backend: String,
    pub allow_fallback: bool,
}

impl Default for AppSettings {
    fn default() -> Self {
        Self {
            python_path: None,
            ffmpeg_path: None,
            ffprobe_path: None,
            config_path: None,
            default_profile: "default".to_string(),
            default_recursive: false,
            default_include_videos: false,
            report_filename: "filesight-report.json".to_string(),
            last_directory: None,
            last_report_path: None,
            last_log_path: None,
            onboarding_seen: false,
            backend: "auto".to_string(),
            allow_fallback: true,
        }
    }
}

/// Settings survive a malformed file: a bad JSON blob falls back to defaults
/// rather than blocking startup.
pub fn load(path: &Path) -> AppSettings {
    let Ok(text) = fs::read_to_string(path) else {
        return AppSettings::default();
    };
    serde_json::from_str(&text).unwrap_or_default()
}

pub fn save(path: &Path, settings: &AppSettings) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|err| format!("cannot create {parent:?}: {err}"))?;
    }
    let text = serde_json::to_string_pretty(settings)
        .map_err(|err| format!("cannot serialize settings: {err}"))?;
    fs::write(path, text).map_err(|err| format!("cannot write {path:?}: {err}"))
}

/// Append one line to the rolling application log.
pub fn append_log(log_dir: &Path, line: &str) {
    if fs::create_dir_all(log_dir).is_err() {
        return;
    }
    let stamp = chrono::Local::now().format("%Y-%m-%d %H:%M:%S");
    let file = log_dir.join("filesight-desktop.log");
    if let Ok(mut handle) = fs::OpenOptions::new().create(true).append(true).open(file) {
        use std::io::Write;
        let _ = writeln!(handle, "[{stamp}] {line}");
    }
}

/// Log lines must not carry image data or huge model output.
pub fn truncate_for_log(text: &str, max: usize) -> String {
    let cleaned: String = text.chars().filter(|c| *c != '\n' && *c != '\r').collect();
    if cleaned.chars().count() <= max {
        return cleaned;
    }
    let kept: String = cleaned.chars().take(max).collect();
    format!("{kept}… (truncated)")
}

pub fn settings_file(config_dir: &Path) -> PathBuf {
    config_dir.join("settings.json")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_dir(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("filesight-test-{name}"));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn defaults_are_sensible() {
        let settings = AppSettings::default();
        assert_eq!(settings.report_filename, "filesight-report.json");
        assert_eq!(settings.default_profile, "default");
        assert!(!settings.default_recursive);
        assert!(!settings.onboarding_seen);
        assert!(settings.python_path.is_none());
        // inference defaults: auto with fallback allowed
        assert_eq!(settings.backend, "auto");
        assert!(settings.allow_fallback);
    }

    #[test]
    fn backend_settings_persist() {
        let dir = temp_dir("settings-backend");
        let path = settings_file(&dir);
        let mut settings = AppSettings::default();
        settings.backend = "onnx-directml".to_string();
        settings.allow_fallback = false;
        save(&path, &settings).unwrap();
        let loaded = load(&path);
        assert_eq!(loaded.backend, "onnx-directml");
        assert!(!loaded.allow_fallback);
    }

    #[test]
    fn cuda_backend_choice_persists() {
        // The NVIDIA choice must survive a restart even on a machine that
        // has no NVIDIA card; Python decides availability, not this layer.
        let dir = temp_dir("settings-cuda");
        let path = settings_file(&dir);
        let mut settings = AppSettings::default();
        settings.backend = "onnx-cuda".to_string();
        save(&path, &settings).unwrap();
        assert_eq!(load(&path).backend, "onnx-cuda");
    }

    #[test]
    fn save_then_load_round_trips() {
        let dir = temp_dir("settings-roundtrip");
        let path = settings_file(&dir);
        let mut settings = AppSettings::default();
        settings.default_profile = "photos".to_string();
        settings.last_directory = Some("D:\\Photos".to_string());
        settings.default_include_videos = true;

        save(&path, &settings).unwrap();
        let loaded = load(&path);
        assert_eq!(loaded, settings);
    }

    #[test]
    fn missing_file_yields_defaults() {
        let dir = temp_dir("settings-missing");
        let loaded = load(&dir.join("nope.json"));
        assert_eq!(loaded, AppSettings::default());
    }

    #[test]
    fn corrupt_file_yields_defaults_instead_of_failing() {
        let dir = temp_dir("settings-corrupt");
        let path = settings_file(&dir);
        fs::write(&path, "{ not json at all").unwrap();
        assert_eq!(load(&path), AppSettings::default());
    }

    #[test]
    fn partial_json_keeps_defaults_for_absent_fields() {
        let dir = temp_dir("settings-partial");
        let path = settings_file(&dir);
        fs::write(&path, r#"{"default_profile":"archive"}"#).unwrap();
        let loaded = load(&path);
        assert_eq!(loaded.default_profile, "archive");
        assert_eq!(loaded.report_filename, "filesight-report.json");
    }

    #[test]
    fn log_lines_are_written() {
        let dir = temp_dir("logs");
        append_log(&dir, "worker started");
        let text = fs::read_to_string(dir.join("filesight-desktop.log")).unwrap();
        assert!(text.contains("worker started"));
    }

    #[test]
    fn log_truncation_keeps_lines_short_and_single_line() {
        let long = "x".repeat(500);
        let out = truncate_for_log(&long, 100);
        assert!(out.starts_with(&"x".repeat(100)));
        assert!(out.ends_with("(truncated)"));
        assert!(!truncate_for_log("a\nb", 10).contains('\n'));
    }
}
