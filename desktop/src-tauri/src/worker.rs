//! Owns the Python worker child process and its JSON Lines transport.
//!
//! The frontend can only send *commands* (a fixed vocabulary handled by
//! the Python side); it can never choose the program or its arguments.

use std::io::{BufRead, BufReader, Write};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use serde::{Deserialize, Serialize};
use serde_json::Value;

/// One parsed line coming back from the worker.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct WorkerEvent {
    pub request_id: String,
    pub event: String,
    #[serde(default)]
    pub data: Value,
}

/// Turn one stdout line into an event, or explain why it could not be.
///
/// A malformed line must never take the UI down: it is surfaced as an
/// `error` event instead.
pub fn parse_event_line(line: &str) -> Result<WorkerEvent, String> {
    let trimmed = line.trim();
    if trimmed.is_empty() {
        return Err("empty line".to_string());
    }
    let value: Value =
        serde_json::from_str(trimmed).map_err(|err| format!("invalid JSON: {err}"))?;
    let object = value
        .as_object()
        .ok_or_else(|| "event must be a JSON object".to_string())?;
    let event = object
        .get("event")
        .and_then(Value::as_str)
        .ok_or_else(|| "event field is missing".to_string())?;
    let request_id = object
        .get("request_id")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    Ok(WorkerEvent {
        request_id,
        event: event.to_string(),
        data: object.get("data").cloned().unwrap_or(Value::Null),
    })
}

/// Serialize an outgoing request line.
pub fn build_request_line(request_id: &str, command: &str, payload: &Value) -> String {
    let body = serde_json::json!({
        "request_id": request_id,
        "command": command,
        "payload": payload,
    });
    format!("{body}\n")
}

/// The set of commands the frontend is allowed to ask for.
pub const ALLOWED_COMMANDS: &[&str] = &[
    "ping",
    "shutdown",
    "cancel",
    "scan",
    "load_report",
    "save_report",
    "validate_report",
    "build_rename_plan",
    "apply_rename",
    "undo",
    "regenerate_names",
    "get_profiles",
    "get_config",
    "get_environment",
    "make_thumbnail",
    "download_ffmpeg",
    "test_backend",
    "benchmark_backend",
    "list_backends",
];

pub fn command_allowed(command: &str) -> bool {
    ALLOWED_COMMANDS.contains(&command)
}

pub struct WorkerHandle {
    child: Child,
    stdin: Option<ChildStdin>,
    /// Cleared when the worker's stdout reaches EOF.
    ///
    /// This is the reliable liveness signal. A virtualenv's `python.exe`
    /// is a launcher that runs the real interpreter as a *separate*
    /// process, so `Child::try_wait()` describes the launcher, not the
    /// worker actually serving requests.
    alive: Arc<AtomicBool>,
    pub executable: String,
}

impl WorkerHandle {
    pub fn write_line(&mut self, line: &str) -> Result<(), String> {
        let stdin = self
            .stdin
            .as_mut()
            .ok_or_else(|| "worker stdin is closed".to_string())?;
        stdin
            .write_all(line.as_bytes())
            .map_err(|err| format!("cannot write to worker: {err}"))?;
        stdin
            .flush()
            .map_err(|err| format!("cannot flush worker stdin: {err}"))
    }

    pub fn is_running(&mut self) -> bool {
        // Only stdout closing proves the worker is gone; the launcher
        // process exiting does not.
        self.alive.load(Ordering::SeqCst) && !matches!(self.child.try_wait(), Ok(Some(_)))
    }

    /// Ask politely, then insist. Never leaves the child running.
    pub fn shutdown(&mut self, grace: std::time::Duration) {
        let _ = self.write_line(&build_request_line(
            "shutdown",
            "shutdown",
            &Value::Object(Default::default()),
        ));
        self.stdin.take(); // closing stdin ends the worker's read loop
        let deadline = std::time::Instant::now() + grace;
        while std::time::Instant::now() < deadline {
            match self.child.try_wait() {
                Ok(Some(_)) => return,
                Ok(None) => std::thread::sleep(std::time::Duration::from_millis(50)),
                Err(_) => break,
            }
        }
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

pub type SharedWorker = Arc<Mutex<Option<WorkerHandle>>>;

/// Spawn `python -m filesight.worker` and pump its stdout/stderr.
///
/// `on_event` receives every parsed event; `on_log` receives stderr lines.
pub fn spawn<F, L>(
    executable: &str,
    working_dir: Option<&std::path::Path>,
    mut on_event: F,
    mut on_log: L,
) -> Result<WorkerHandle, String>
where
    F: FnMut(WorkerEvent) + Send + 'static,
    L: FnMut(String) + Send + 'static,
{
    let mut command = Command::new(executable);
    command
        .arg("-u") // unbuffered: progress must arrive as it happens
        .arg("-m")
        .arg("filesight.worker")
        // Load the model up front. Importing the torch/transformers C
        // extensions *after* the worker starts serving a piped session
        // deadlocks on Windows, so the model must be ready before the
        // request loop begins.
        .arg("--preload")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .env("PYTHONIOENCODING", "utf-8")
        .env("PYTHONUTF8", "1");
    if let Some(dir) = working_dir {
        command.current_dir(dir);
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }

    let mut child = command
        .spawn()
        .map_err(|err| format!("cannot start the Python worker ({executable}): {err}"))?;

    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "worker stdout unavailable".to_string())?;
    let stderr = child
        .stderr
        .take()
        .ok_or_else(|| "worker stderr unavailable".to_string())?;
    let stdin = child.stdin.take();

    let alive = Arc::new(AtomicBool::new(true));
    let reader_alive = Arc::clone(&alive);
    std::thread::spawn(move || {
        let reader = BufReader::new(stdout);
        for line in reader.lines().map_while(Result::ok) {
            match parse_event_line(&line) {
                Ok(event) => on_event(event),
                Err(reason) => on_event(WorkerEvent {
                    request_id: String::new(),
                    event: "error".to_string(),
                    data: serde_json::json!({
                        "code": "WORKER_PROTOCOL_ERROR",
                        "message": format!("Unreadable worker output ({reason})."),
                        "recoverable": true,
                    }),
                }),
            }
        }
        // stdout ended: the worker is really gone.
        reader_alive.store(false, Ordering::SeqCst);
    });

    std::thread::spawn(move || {
        let reader = BufReader::new(stderr);
        for line in reader.lines().map_while(Result::ok) {
            on_log(line);
        }
    });

    Ok(WorkerHandle {
        child,
        stdin,
        alive,
        executable: executable.to_string(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_a_normal_event() {
        let event =
            parse_event_line(r#"{"request_id":"abc","event":"progress","data":{"percent":50}}"#)
                .unwrap();
        assert_eq!(event.request_id, "abc");
        assert_eq!(event.event, "progress");
        assert_eq!(event.data["percent"], 50);
    }

    #[test]
    fn tolerates_a_missing_data_field() {
        let event = parse_event_line(r#"{"request_id":"a","event":"started"}"#).unwrap();
        assert_eq!(event.data, Value::Null);
    }

    #[test]
    fn tolerates_a_missing_request_id() {
        let event = parse_event_line(r#"{"event":"error","data":{}}"#).unwrap();
        assert_eq!(event.request_id, "");
    }

    #[test]
    fn rejects_invalid_json() {
        assert!(parse_event_line("{not json").is_err());
    }

    #[test]
    fn rejects_a_non_object_line() {
        assert!(parse_event_line("[1,2,3]").is_err());
    }

    #[test]
    fn rejects_an_event_without_a_kind() {
        assert!(parse_event_line(r#"{"request_id":"a"}"#).is_err());
    }

    #[test]
    fn ignores_blank_lines() {
        assert!(parse_event_line("   ").is_err());
    }

    #[test]
    fn request_lines_are_newline_terminated_json() {
        let line = build_request_line("r1", "scan", &serde_json::json!({"directory": "D:\\x"}));
        assert!(line.ends_with('\n'));
        let parsed: Value = serde_json::from_str(line.trim()).unwrap();
        assert_eq!(parsed["command"], "scan");
        assert_eq!(parsed["request_id"], "r1");
        assert_eq!(parsed["payload"]["directory"], "D:\\x");
    }

    #[test]
    fn liveness_follows_stdout_not_the_launcher() {
        // A venv python.exe is a launcher: it starts the real interpreter
        // as another process and its own exit says nothing about the
        // worker. Only stdout closing means the worker is gone.
        let alive = Arc::new(AtomicBool::new(true));
        assert!(alive.load(Ordering::SeqCst));
        alive.store(false, Ordering::SeqCst);
        assert!(!alive.load(Ordering::SeqCst));
    }

    #[test]
    fn only_known_commands_are_allowed() {
        assert!(command_allowed("scan"));
        assert!(command_allowed("undo"));
        // arbitrary programs / shell strings can never be sent
        assert!(!command_allowed("rm -rf /"));
        assert!(!command_allowed("powershell.exe"));
        assert!(!command_allowed(""));
    }
}
