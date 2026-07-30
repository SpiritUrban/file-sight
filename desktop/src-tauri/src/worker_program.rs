//! Deciding *what* to launch as the analysis worker.
//!
//! There are two ways to run the Python core, and the app must pick the
//! right one without asking:
//!
//! * a **frozen sidecar** shipped inside the installer -- what an installed
//!   copy uses, and the reason a user needs no Python at all;
//! * a **Python interpreter** plus a source checkout -- what a developer
//!   uses, and the only way to see code changes without rebuilding.
//!
//! The order below is not arbitrary; each step is there to stop a specific
//! wrong answer. Resolution is separated from spawning so it can be tested
//! without starting processes.

use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use crate::python;

/// Where the program we settled on came from.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WorkerSource {
    /// The frozen worker shipped in the bundle.
    Bundled,
    /// A Python interpreter running the package from a checkout.
    Python,
    /// Nothing usable was found.
    NotFound,
}

/// A resolved, ready-to-spawn worker command.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WorkerProgram {
    pub program: String,
    pub args: Vec<String>,
    pub working_dir: Option<String>,
    pub source: WorkerSource,
    /// Which interpreter answered, when the Python route was taken.
    pub python: Option<python::PythonInfo>,
    pub ok: bool,
    /// User-facing explanation when `ok` is false.
    pub message: Option<String>,
}

impl WorkerProgram {
    fn not_found(message: String, python: Option<python::PythonInfo>) -> Self {
        Self {
            program: String::new(),
            args: Vec::new(),
            working_dir: None,
            source: WorkerSource::NotFound,
            python,
            ok: false,
            message: Some(message),
        }
    }

    /// A short line for the log: which route was taken and with what.
    pub fn describe(&self) -> String {
        match self.source {
            WorkerSource::Bundled => format!("bundled worker at {}", self.program),
            WorkerSource::Python => format!("python worker via {}", self.program),
            WorkerSource::NotFound => {
                format!(
                    "no worker: {}",
                    self.message.as_deref().unwrap_or("unknown")
                )
            }
        }
    }
}

/// Path of the frozen worker inside a resource directory.
///
/// Built with `join` rather than a literal separator: a hardcoded `\` is
/// legal in a Unix file name, so it produces a path that simply does not
/// exist rather than an error anybody would notice.
pub fn bundled_worker_path(resource_dir: &Path) -> PathBuf {
    let name = if cfg!(windows) {
        "filesight-worker.exe"
    } else {
        "filesight-worker"
    };
    resource_dir.join("filesight-worker").join(name)
}

/// The arguments the frozen worker is started with.
///
/// `--preload` is mandatory, not an optimisation: importing torch or the
/// onnxruntime/DirectML DLLs *after* the worker starts serving a piped
/// session deadlocks in the Windows loader, because the reader thread is
/// blocked in a stdin read. Loading up front is what avoids it.
fn bundled_args() -> Vec<String> {
    vec!["--preload".to_string()]
}

/// The arguments an interpreter is started with.
fn python_args() -> Vec<String> {
    vec![
        "-u".to_string(), // unbuffered: progress must arrive as it happens
        "-m".to_string(),
        "filesight.worker".to_string(),
        "--preload".to_string(),
    ]
}

/// Choose the worker to launch.
///
/// `resource_dir` is the bundle's resource directory (`None` outside Tauri),
/// `configured` an interpreter the user set in Settings, `repo_root` a source
/// checkout if the app is running from one.
pub fn resolve(
    resource_dir: Option<&Path>,
    configured: Option<&str>,
    repo_root: Option<&Path>,
) -> WorkerProgram {
    let explicit = configured.map(str::trim).filter(|value| !value.is_empty());

    // 1. An interpreter set in Settings wins outright. It is the one place
    //    the user has said, in words, which Python to use; silently ignoring
    //    it in favour of a bundled copy would be unfixable from the UI.
    if explicit.is_some() {
        return from_python(explicit, repo_root);
    }

    // 2. A source checkout beats the bundle. Running from a checkout means
    //    somebody is working on the code, and a frozen copy would quietly
    //    serve yesterday's version -- a class of confusion that costs hours
    //    because everything looks fine.
    if let Some(root) = repo_root {
        if python::venv_python(root).is_file() {
            return from_python(None, Some(root));
        }
    }

    // 3. The bundled worker: the normal path for an installed copy, and the
    //    reason it works on a machine with no Python.
    if let Some(dir) = resource_dir {
        let candidate = bundled_worker_path(dir);
        if candidate.is_file() {
            return WorkerProgram {
                program: candidate.to_string_lossy().into_owned(),
                args: bundled_args(),
                working_dir: None,
                source: WorkerSource::Bundled,
                python: None,
                ok: true,
                message: None,
            };
        }
    }

    // 4. Any Python that can run the package.
    from_python(None, repo_root)
}

fn from_python(configured: Option<&str>, repo_root: Option<&Path>) -> WorkerProgram {
    let info = python::resolve(configured, repo_root);
    let Some(executable) = info.executable.clone() else {
        let message = info.message.clone().unwrap_or_else(|| {
            "No Python interpreter and no bundled worker were found.".to_string()
        });
        return WorkerProgram::not_found(message, Some(info));
    };
    // The package is imported by name, so the interpreter has to run with the
    // checkout as its working directory when there is one.
    let working_dir = repo_root.map(|root| root.to_string_lossy().into_owned());
    WorkerProgram {
        program: executable,
        args: python_args(),
        working_dir,
        source: WorkerSource::Python,
        python: Some(info),
        ok: true,
        message: None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    /// A scratch directory that does not depend on any path separator being
    /// spelled out (rule 6a).
    fn scratch(name: &str) -> PathBuf {
        let mut dir = std::env::temp_dir();
        dir.push("filesight-worker-program-tests");
        dir.push(name);
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn make_bundle(resource_dir: &Path) -> PathBuf {
        let path = bundled_worker_path(resource_dir);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(&path, b"stub").unwrap();
        path
    }

    fn make_venv(repo_root: &Path) -> PathBuf {
        let path = python::venv_python(repo_root);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(&path, b"stub").unwrap();
        path
    }

    #[test]
    fn bundled_path_is_built_without_writing_a_separator() {
        let dir = scratch("path-shape");
        let path = bundled_worker_path(&dir);
        assert_eq!(
            path.parent().unwrap().file_name().unwrap(),
            "filesight-worker"
        );
        if cfg!(windows) {
            assert!(path.ends_with("filesight-worker.exe"));
        } else {
            assert!(path.ends_with("filesight-worker"));
        }
        // The whole path must live under the resource directory, whatever
        // the platform spells its separator as.
        assert!(path.starts_with(&dir));
    }

    #[test]
    fn a_bundled_worker_is_used_when_there_is_no_checkout() {
        let resources = scratch("bundle-only");
        make_bundle(&resources);

        let program = resolve(Some(&resources), None, None);
        assert_eq!(program.source, WorkerSource::Bundled);
        assert!(program.ok);
        assert_eq!(program.args, vec!["--preload".to_string()]);
        assert!(program.python.is_none());
    }

    #[test]
    fn the_bundled_worker_always_preloads() {
        // Not cosmetic: importing the native runtimes after the piped session
        // starts deadlocks the Windows loader.
        let resources = scratch("bundle-preload");
        make_bundle(&resources);
        let program = resolve(Some(&resources), None, None);
        assert!(program.args.iter().any(|a| a == "--preload"));
    }

    #[test]
    fn a_checkout_wins_over_the_bundle() {
        // Otherwise `tauri dev` in a source tree silently runs a frozen copy
        // and the developer debugs code that is not executing.
        let resources = scratch("checkout-wins-res");
        let repo = scratch("checkout-wins-repo");
        make_bundle(&resources);
        make_venv(&repo);

        let program = resolve(Some(&resources), None, Some(&repo));
        assert_eq!(program.source, WorkerSource::Python);
        assert!(program.args.iter().any(|a| a == "filesight.worker"));
    }

    #[test]
    fn a_checkout_without_a_venv_falls_through_to_the_bundle() {
        let resources = scratch("empty-checkout-res");
        let repo = scratch("empty-checkout-repo");
        make_bundle(&resources);

        let program = resolve(Some(&resources), None, Some(&repo));
        assert_eq!(program.source, WorkerSource::Bundled);
    }

    #[test]
    fn a_configured_interpreter_beats_the_bundle() {
        // The user named an interpreter in Settings. Ignoring it would leave
        // them with no way to change the answer.
        let resources = scratch("configured-res");
        make_bundle(&resources);

        let program = resolve(Some(&resources), Some("definitely-not-a-real-python"), None);
        assert_ne!(program.source, WorkerSource::Bundled);
    }

    #[test]
    fn a_blank_configured_value_is_ignored() {
        let resources = scratch("blank-configured");
        make_bundle(&resources);

        let program = resolve(Some(&resources), Some("   "), None);
        assert_eq!(program.source, WorkerSource::Bundled);
    }

    #[test]
    fn a_missing_bundle_is_not_used() {
        let resources = scratch("no-bundle");
        // Nothing written: the directory exists but holds no worker.
        let program = resolve(Some(&resources), None, None);
        assert_ne!(program.source, WorkerSource::Bundled);
    }

    #[test]
    fn python_route_runs_the_package_as_a_module() {
        let program = from_python(None, None);
        if program.ok {
            assert_eq!(program.args[0], "-u");
            assert_eq!(program.args[1], "-m");
            assert_eq!(program.args[2], "filesight.worker");
            assert_eq!(program.args[3], "--preload");
        }
    }

    #[test]
    fn a_failed_resolution_explains_itself() {
        let program = WorkerProgram::not_found("nothing here".to_string(), None);
        assert!(!program.ok);
        assert_eq!(program.source, WorkerSource::NotFound);
        assert!(program.describe().contains("nothing here"));
    }
}
