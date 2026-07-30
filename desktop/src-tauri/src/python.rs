//! Locating a usable Python interpreter.
//!
//! The frontend never supplies a program to run: it can only pick from
//! what this module resolves, which is why the discovery logic lives in
//! Rust and is unit tested.

use std::path::{Path, PathBuf};
use std::process::Command;

use serde::{Deserialize, Serialize};

/// Where the interpreter we settled on came from.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PythonSource {
    Settings,
    ProjectVenv,
    Path,
    Launcher,
    NotFound,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PythonInfo {
    pub executable: Option<String>,
    pub source: PythonSource,
    pub version: Option<String>,
    pub ok: bool,
    pub message: Option<String>,
}

impl PythonInfo {
    pub fn not_found(message: &str) -> Self {
        Self {
            executable: None,
            source: PythonSource::NotFound,
            version: None,
            ok: false,
            message: Some(message.to_string()),
        }
    }
}

/// Candidate interpreter path inside a repo checkout's virtualenv.
pub fn venv_python(repo_root: &Path) -> PathBuf {
    if cfg!(windows) {
        repo_root.join(".venv").join("Scripts").join("python.exe")
    } else {
        repo_root.join(".venv").join("bin").join("python")
    }
}

/// Build the ordered candidate list: settings, project venv, PATH, launcher.
///
/// Returned entries are candidates only; none of them is verified here so
/// the ordering can be tested without touching the filesystem.
pub fn candidates(
    configured: Option<&str>,
    repo_root: Option<&Path>,
) -> Vec<(String, PythonSource)> {
    let mut out: Vec<(String, PythonSource)> = Vec::new();

    if let Some(value) = configured {
        let trimmed = value.trim();
        if !trimmed.is_empty() {
            out.push((trimmed.to_string(), PythonSource::Settings));
        }
    }
    if let Some(root) = repo_root {
        let candidate = venv_python(root);
        out.push((
            candidate.to_string_lossy().into_owned(),
            PythonSource::ProjectVenv,
        ));
    }
    out.push(("python".to_string(), PythonSource::Path));
    if cfg!(windows) {
        out.push(("py".to_string(), PythonSource::Launcher));
    } else {
        out.push(("python3".to_string(), PythonSource::Path));
    }
    out
}

/// Parse the `Python 3.14.0` banner that `python --version` prints.
pub fn parse_version(output: &str) -> Option<(u32, u32)> {
    let text = output.trim();
    let rest = text.strip_prefix("Python ").unwrap_or(text);
    let mut parts = rest.split('.');
    let major: u32 = parts.next()?.trim().parse().ok()?;
    let minor: u32 = parts.next()?.trim().parse().ok()?;
    Some((major, minor))
}

/// FileSight needs 3.11 or newer.
pub fn version_supported(version: (u32, u32)) -> bool {
    version.0 > 3 || (version.0 == 3 && version.1 >= 11)
}

fn query_version(program: &str, launcher: bool) -> Option<String> {
    let mut command = Command::new(program);
    if launcher {
        command.arg("-3");
    }
    command.arg("--version");
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    let output = command.output().ok()?;
    let text = if output.stdout.is_empty() {
        String::from_utf8_lossy(&output.stderr).to_string()
    } else {
        String::from_utf8_lossy(&output.stdout).to_string()
    };
    if text.trim().is_empty() {
        None
    } else {
        Some(text.trim().to_string())
    }
}

/// Resolve the first candidate that runs and reports a supported version.
pub fn resolve(configured: Option<&str>, repo_root: Option<&Path>) -> PythonInfo {
    let mut last_message: Option<String> = None;

    for (program, source) in candidates(configured, repo_root) {
        // A project-venv candidate is a concrete path: skip it if absent.
        if source == PythonSource::ProjectVenv && !Path::new(&program).is_file() {
            continue;
        }
        if source == PythonSource::Settings
            && program.contains(std::path::MAIN_SEPARATOR)
            && !Path::new(&program).is_file()
        {
            last_message = Some(format!("Configured Python not found: {program}"));
            continue;
        }
        let launcher = source == PythonSource::Launcher;
        let Some(banner) = query_version(&program, launcher) else {
            continue;
        };
        match parse_version(&banner) {
            Some(version) if version_supported(version) => {
                return PythonInfo {
                    executable: Some(program),
                    source,
                    version: Some(banner),
                    ok: true,
                    message: None,
                };
            }
            Some(version) => {
                last_message = Some(format!(
                    "{program} is Python {}.{}, but FileSight needs 3.11 or newer.",
                    version.0, version.1
                ));
            }
            None => {
                last_message = Some(format!("Could not read a version from {program}."));
            }
        }
    }

    PythonInfo::not_found(last_message.as_deref().unwrap_or(
        "No Python 3.11+ interpreter was found. Install Python and set its path in Settings.",
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_a_normal_version_banner() {
        assert_eq!(parse_version("Python 3.14.0"), Some((3, 14)));
        assert_eq!(parse_version("  Python 3.11.9  "), Some((3, 11)));
    }

    #[test]
    fn parses_a_bare_version() {
        assert_eq!(parse_version("3.12.1"), Some((3, 12)));
    }

    #[test]
    fn rejects_unparseable_banners() {
        assert_eq!(parse_version("no idea"), None);
        assert_eq!(parse_version(""), None);
    }

    #[test]
    fn version_support_matches_requires_python() {
        assert!(version_supported((3, 11)));
        assert!(version_supported((3, 14)));
        assert!(version_supported((4, 0)));
        assert!(!version_supported((3, 10)));
        assert!(!version_supported((2, 7)));
    }

    #[test]
    fn candidate_order_prefers_settings_then_venv() {
        let root = PathBuf::from("C:\\repo");
        let list = candidates(Some("C:\\custom\\python.exe"), Some(&root));
        assert_eq!(list[0].1, PythonSource::Settings);
        assert_eq!(list[0].0, "C:\\custom\\python.exe");
        assert_eq!(list[1].1, PythonSource::ProjectVenv);
        assert!(list[1].0.contains(".venv"));
        assert_eq!(list[2].1, PythonSource::Path);
    }

    #[test]
    fn blank_settings_value_is_ignored() {
        let list = candidates(Some("   "), None);
        assert_eq!(list[0].1, PythonSource::Path);
    }

    #[test]
    fn venv_path_is_platform_correct() {
        let path = venv_python(Path::new("C:\\repo"));
        if cfg!(windows) {
            assert!(path.ends_with("python.exe"));
            assert!(path.to_string_lossy().contains("Scripts"));
        } else {
            assert!(path.ends_with("python"));
        }
    }

    #[test]
    fn not_found_info_is_not_ok() {
        let info = PythonInfo::not_found("nope");
        assert!(!info.ok);
        assert_eq!(info.source, PythonSource::NotFound);
        assert!(info.executable.is_none());
    }
}
