//! FileSight desktop shell.
//!
//! Rust owns the Python worker process; the frontend can only send
//! whitelisted commands and receives events through a Tauri event channel.

pub mod python;
pub mod settings;
pub mod worker;
pub mod worker_program;

use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use serde::Serialize;
use serde_json::Value;
use tauri::{AppHandle, Emitter, Manager, State};

use settings::AppSettings;
use worker::{SharedWorker, WorkerEvent};
use worker_program::WorkerProgram;

pub struct AppState {
    pub worker: SharedWorker,
    pub config_dir: Mutex<PathBuf>,
    pub log_dir: Mutex<PathBuf>,
    pub repo_root: Mutex<Option<PathBuf>>,
    /// Where the bundle's resources live; `None` when not running in Tauri.
    pub resource_dir: Mutex<Option<PathBuf>>,
}

impl Default for AppState {
    fn default() -> Self {
        Self {
            worker: Arc::new(Mutex::new(None)),
            config_dir: Mutex::new(PathBuf::from(".")),
            log_dir: Mutex::new(PathBuf::from(".")),
            repo_root: Mutex::new(None),
            resource_dir: Mutex::new(None),
        }
    }
}

#[derive(Debug, Serialize)]
pub struct EnvironmentStatus {
    /// The interpreter, when one is in play. Kept for the Settings screen:
    /// a bundled worker has no interpreter to report.
    pub python: python::PythonInfo,
    /// What will actually be launched, and why.
    pub worker_program: WorkerProgram,
    pub worker_running: bool,
    pub repo_root: Option<String>,
}

fn log_line(state: &AppState, line: &str) {
    if let Ok(dir) = state.log_dir.lock() {
        settings::append_log(&dir, &settings::truncate_for_log(line, 400));
    }
}

/// Walk up from the executable/cwd looking for the Python package.
fn detect_repo_root() -> Option<PathBuf> {
    let mut candidates: Vec<PathBuf> = Vec::new();
    if let Ok(cwd) = std::env::current_dir() {
        candidates.push(cwd);
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(parent) = exe.parent() {
            candidates.push(parent.to_path_buf());
        }
    }
    for start in candidates {
        let mut current: Option<&std::path::Path> = Some(start.as_path());
        while let Some(dir) = current {
            if dir
                .join("src")
                .join("filesight")
                .join("worker.py")
                .is_file()
            {
                return Some(dir.to_path_buf());
            }
            current = dir.parent();
        }
    }
    None
}

/// Resolve what to launch, from whatever the app currently knows.
fn resolve_program(state: &AppState) -> WorkerProgram {
    let repo_root = state.repo_root.lock().ok().and_then(|r| r.clone());
    let resource_dir = state.resource_dir.lock().ok().and_then(|r| r.clone());
    let configured = {
        let dir = state.config_dir.lock().unwrap().clone();
        settings::load(&settings::settings_file(&dir)).python_path
    };
    worker_program::resolve(
        resource_dir.as_deref(),
        configured.as_deref(),
        repo_root.as_deref(),
    )
}

#[tauri::command]
fn get_environment_status(state: State<'_, AppState>) -> EnvironmentStatus {
    let repo_root = state.repo_root.lock().ok().and_then(|r| r.clone());
    let program = resolve_program(&state);
    // A bundled worker carries its own interpreter, so there is nothing
    // useful to say about Python; saying "not found" would read as a fault.
    let python = program
        .python
        .clone()
        .unwrap_or_else(|| python::PythonInfo {
            executable: None,
            source: python::PythonSource::NotFound,
            version: None,
            ok: program.ok,
            message: Some("Not needed: the analysis worker is bundled.".to_string()),
        });
    let worker_running = state
        .worker
        .lock()
        .map(|guard| guard.is_some())
        .unwrap_or(false);
    EnvironmentStatus {
        python,
        worker_program: program,
        worker_running,
        repo_root: repo_root.map(|p| p.to_string_lossy().into_owned()),
    }
}

/// Make sure a live worker exists, starting one if needed.
///
/// The lock is held for the whole check-and-spawn so two concurrent calls
/// (React's StrictMode mounts effects twice in development) cannot each
/// spawn an interpreter and then fight over which handle is kept.
fn ensure_worker(app: &AppHandle, state: &State<'_, AppState>) -> Result<String, String> {
    let mut guard = state.worker.lock().map_err(|_| "worker lock poisoned")?;
    if let Some(handle) = guard.as_mut() {
        if handle.is_running() {
            return Ok(handle.executable.clone());
        }
        log_line(state, "worker was not running; starting a new one");
        *guard = None;
    }

    let program = resolve_program(state);
    if !program.ok {
        return Err(program
            .message
            .clone()
            .unwrap_or_else(|| "No analysis worker could be found.".into()));
    }
    let working_dir = program.working_dir.clone().map(PathBuf::from);

    let event_app = app.clone();
    let log_app = app.clone();
    let handle = worker::spawn(
        &program.program,
        &program.args,
        working_dir.as_deref(),
        move |event: WorkerEvent| {
            let _ = event_app.emit("worker-event", event);
        },
        move |line: String| {
            if let Some(state) = log_app.try_state::<AppState>() {
                log_line(&state, &format!("worker stderr: {line}"));
            }
        },
    )?;

    let executable = program.program.clone();
    log_line(state, &format!("worker started: {}", program.describe()));
    *guard = Some(handle);
    Ok(executable)
}

#[tauri::command]
fn start_worker(app: AppHandle, state: State<'_, AppState>) -> Result<String, String> {
    ensure_worker(&app, &state)
}

#[tauri::command]
fn send_worker_command(
    app: AppHandle,
    state: State<'_, AppState>,
    request_id: String,
    command: String,
    payload: Option<Value>,
) -> Result<(), String> {
    if !worker::command_allowed(&command) {
        return Err(format!("Command '{command}' is not allowed."));
    }
    let line = worker::build_request_line(
        &request_id,
        &command,
        &payload.unwrap_or(Value::Object(Default::default())),
    );

    // First attempt with whatever worker we have.
    let failure = {
        let mut guard = state.worker.lock().map_err(|_| "worker lock poisoned")?;
        let mut reason = "worker not available".to_string();
        if let Some(handle) = guard.as_mut() {
            if handle.is_running() {
                match handle.write_line(&line) {
                    Ok(()) => return Ok(()),
                    Err(err) => reason = err,
                }
            } else {
                reason = "worker had stopped".to_string();
            }
        }
        reason
    };

    // A worker can disappear between requests (crash, or a stale handle
    // after a reload). Restart once and retry rather than dead-ending the
    // user on an error they cannot act on.
    log_line(
        &state,
        &format!("restarting worker after send failure: {failure}"),
    );
    ensure_worker(&app, &state)?;
    let mut guard = state.worker.lock().map_err(|_| "worker lock poisoned")?;
    let handle = guard
        .as_mut()
        .ok_or_else(|| "The analysis worker could not be started.".to_string())?;
    handle
        .write_line(&line)
        .map_err(|reason| format!("The analysis worker is not responding ({reason})."))
}

#[tauri::command]
fn stop_worker(state: State<'_, AppState>) -> Result<(), String> {
    let mut guard = state.worker.lock().map_err(|_| "worker lock poisoned")?;
    if let Some(mut handle) = guard.take() {
        handle.shutdown(std::time::Duration::from_secs(5));
    }
    Ok(())
}

#[tauri::command]
fn get_app_settings(state: State<'_, AppState>) -> AppSettings {
    let dir = state.config_dir.lock().unwrap().clone();
    settings::load(&settings::settings_file(&dir))
}

#[tauri::command]
fn save_app_settings(
    state: State<'_, AppState>,
    settings_value: AppSettings,
) -> Result<(), String> {
    let dir = state.config_dir.lock().unwrap().clone();
    settings::save(&settings::settings_file(&dir), &settings_value)
}

#[tauri::command]
fn get_log_directory(state: State<'_, AppState>) -> String {
    state
        .log_dir
        .lock()
        .map(|d| d.to_string_lossy().into_owned())
        .unwrap_or_default()
}

#[tauri::command]
fn get_thumbnail_cache_dir() -> String {
    std::env::temp_dir()
        .join("filesight-thumbnails")
        .to_string_lossy()
        .into_owned()
}

#[tauri::command]
fn log_message(state: State<'_, AppState>, message: String) {
    log_line(&state, &format!("ui: {message}"));
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let builder = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init());

    // Rule 28: the updater has to be compiled in, not merely configured.
    // The cfg gate mirrors the one in Cargo.toml exactly -- a mismatch here
    // is a link error that only shows up on the platform that was left out.
    #[cfg(not(any(target_os = "android", target_os = "ios")))]
    let builder = builder
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init());

    builder
        .manage(AppState::default())
        .setup(|app| {
            let state = app.state::<AppState>();
            if let Ok(dir) = app.path().app_config_dir() {
                *state.config_dir.lock().unwrap() = dir;
            }
            if let Ok(dir) = app.path().app_log_dir() {
                *state.log_dir.lock().unwrap() = dir;
            }
            if let Ok(dir) = app.path().resource_dir() {
                *state.resource_dir.lock().unwrap() = Some(dir);
            }
            *state.repo_root.lock().unwrap() = detect_repo_root();

            // Thumbnails live in a dedicated temp folder; allow reading them.
            let cache = std::env::temp_dir().join("filesight-thumbnails");
            let _ = std::fs::create_dir_all(&cache);
            let _ = app.asset_protocol_scope().allow_directory(&cache, false);

            log_line(
                &state,
                &format!("FileSight desktop {} starting", env!("CARGO_PKG_VERSION")),
            );
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_environment_status,
            start_worker,
            send_worker_command,
            stop_worker,
            get_app_settings,
            save_app_settings,
            get_log_directory,
            get_thumbnail_cache_dir,
            log_message,
        ])
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                // Never leave a Python process behind.
                if let Some(state) = window.try_state::<AppState>() {
                    if let Ok(mut guard) = state.worker.lock() {
                        if let Some(mut handle) = guard.take() {
                            handle.shutdown(std::time::Duration::from_secs(3));
                        }
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running FileSight");
}
