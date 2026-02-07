use serde::{Deserialize, Serialize};
use std::env;
use zed_extension_api::{self as zed, http_client::HttpMethod, http_client::HttpRequestBuilder};

const USER_AGENT: &str = "CodeTime Client";
const DEFAULT_BASE_URL: &str = "http://localhost:9492";
const MAX_RELATIVE_PATH_LEN: usize = 2048;

const EVENT_TYPES: &[&str] = &[
    "activateFileChanged",
    "editorChanged",
    "fileSaved",
    "fileAddedLine",
    "fileCreated",
    "fileEdited",
    "changeEditorSelection",
    "changeEditorVisibleRanges",
];

/// Returns a validated base URL (http/https only); falls back to default if invalid.
fn base_url() -> String {
    let raw = env::var("CODETIME_PROXY_URL").unwrap_or_else(|_| DEFAULT_BASE_URL.to_string());
    let trimmed = raw.trim().trim_end_matches('/');
    if trimmed.starts_with("https://") || trimmed.starts_with("http://") {
        trimmed.to_string()
    } else {
        DEFAULT_BASE_URL.to_string()
    }
}

/// Returns a masked version of the base URL for display (scheme + host, no path or query).
pub(crate) fn base_url_display() -> String {
    let u = base_url();
    if let Some(after) = u.strip_prefix("https://") {
        let host = after.split('/').next().unwrap_or(after);
        format!("https://{}", host)
    } else if let Some(after) = u.strip_prefix("http://") {
        let host = after.split('/').next().unwrap_or(after);
        format!("http://{}", host)
    } else {
        u
    }
}

/// Sanitizes relative file path: no traversal, reasonable length, forward slashes.
pub(crate) fn sanitize_relative_path(input: &str) -> String {
    let s = input.trim();
    if s.is_empty() {
        return "unknown".to_string();
    }
    let no_back = s.replace('\\', "/");
    let parts: Vec<&str> = no_back.split('/').filter(|p| !p.is_empty() && *p != "..").collect();
    let joined = parts.join("/");
    if joined.is_empty() {
        return "unknown".to_string();
    }
    if joined.len() > MAX_RELATIVE_PATH_LEN {
        return joined.chars().take(MAX_RELATIVE_PATH_LEN).collect();
    }
    joined
}

fn bearer_token() -> Option<String> {
    env::var("CODETIME_API_KEY").ok()
}

fn platform_string() -> String {
    let (os, arch) = zed::current_platform();
    let os_str = match os {
        zed::Os::Mac => "macOS",
        zed::Os::Linux => "Linux",
        zed::Os::Windows => "Windows",
    };
    let arch_str = match arch {
        zed::Architecture::Aarch64 => "aarch64",
        zed::Architecture::X86 => "x86",
        zed::Architecture::X8664 => "x64",
    };
    format!("{} {}", os_str, arch_str)
}

pub(crate) fn project_name_from_root(root_path: &str) -> String {
    std::path::Path::new(root_path)
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("unknown")
        .to_string()
}

pub(crate) fn language_from_extension(relative_file: &str) -> String {
    std::path::Path::new(relative_file)
        .extension()
        .and_then(|e| e.to_str())
        .map(|e| {
            let e: String = e.to_lowercase();
            match e.as_str() {
                "rs" => "rust",
                "py" => "python",
                "js" => "javascript",
                "ts" => "typescript",
                "tsx" => "typescript",
                "jsx" => "javascript",
                "mjs" | "cjs" => "javascript",
                "sql" => "sql",
                "md" => "markdown",
                "json" => "json",
                "yaml" | "yml" => "yaml",
                "toml" => "toml",
                "html" | "htm" => "html",
                "css" | "scss" | "less" => "css",
                "sh" | "bash" | "zsh" => "shell",
                "go" | "mod" => "go",
                "java" => "java",
                "kt" | "kts" => "kotlin",
                "swift" => "swift",
                "c" | "h" => "c",
                "cpp" | "cc" | "cxx" | "hpp" | "hxx" => "cpp",
                "rb" => "ruby",
                "php" => "php",
                "vue" => "vue",
                "svelte" => "svelte",
                "lua" => "lua",
                "r" => "r",
                "ex" | "exs" => "elixir",
                "erl" | "hrl" => "erlang",
                "scala" | "sc" => "scala",
                "fs" | "fsi" | "fsx" => "fsharp",
                "zig" => "zig",
                "v" => "v",
                "nim" => "nim",
                "cr" => "crystal",
                _ => e.as_str(),
            }
            .to_string()
        })
        .unwrap_or_else(|| "unknown".to_string())
}

pub(crate) fn operation_type_for_event(event_type: &str) -> &'static str {
    match event_type {
        "fileSaved" | "fileEdited" | "fileCreated" | "fileAddedLine" => "write",
        _ => "read",
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct EventLogBody {
    project: String,
    language: String,
    relative_file: String,
    absolute_file: String,
    editor: String,
    platform: String,
    event_time: i64,
    event_type: String,
    operation_type: String,
}

#[derive(Deserialize)]
struct MinutesResponse {
    minutes: Option<String>,
}

struct CodetimeExtension;

impl zed::Extension for CodetimeExtension {
    fn new() -> Self {
        Self
    }

    fn run_slash_command(
        &self,
        command: zed::SlashCommand,
        args: Vec<String>,
        worktree: Option<&zed::Worktree>,
    ) -> Result<zed::SlashCommandOutput, String> {
        match command.name.as_str() {
            "codetime_minutes" => run_minutes(),
            "codetime_report" => run_report(args, worktree),
            "codetime_status" => run_status(),
            _ => Err(format!("unknown command: {}", command.name)),
        }
    }

    fn complete_slash_command_argument(
        &self,
        command: zed::SlashCommand,
        _args: Vec<String>,
    ) -> Result<Vec<zed::SlashCommandArgumentCompletion>, String> {
        if command.name == "codetime_report" {
            return Ok(EVENT_TYPES
                .iter()
                .map(|&name| zed::SlashCommandArgumentCompletion {
                    label: name.to_string(),
                    new_text: name.to_string(),
                    run_command: true,
                })
                .collect());
        }
        Ok(vec![])
    }
}

fn run_minutes() -> Result<zed::SlashCommandOutput, String> {
    let base = base_url();
    let url = format!("{}/v3/users/self/minutes", base.trim_end_matches('/'));

    let mut req = HttpRequestBuilder::new()
        .method(HttpMethod::Get)
        .url(&url)
        .header("User-Agent", USER_AGENT);

    if let Some(token) = bearer_token() {
        req = req.header("Authorization", format!("Bearer {}", token));
    }

    let req = req.build().map_err(|e| format!("CodeTime: request setup failed: {}", e))?;
    let response = zed::http_client::fetch(&req).map_err(|e| {
        format!(
            "CodeTime proxy unreachable (check CODETIME_PROXY_URL and network): {}",
            e
        )
    })?;

    let body_str = String::from_utf8_lossy(&response.body);
    let parsed = serde_json::from_str::<MinutesResponse>(&body_str).map_err(|e| {
        format!(
            "CodeTime: invalid response from proxy (check proxy version): {}",
            e
        )
    })?;

    let minutes = parsed.minutes.unwrap_or_else(|| "0".to_string());
    let text = format!("Tracked minutes: {}", minutes);

    Ok(zed::SlashCommandOutput {
        text: text.clone(),
        sections: vec![zed::SlashCommandOutputSection {
            range: (0..text.len()).into(),
            label: "Minutes".to_string(),
        }],
    })
}

fn run_report(
    args: Vec<String>,
    worktree: Option<&zed::Worktree>,
) -> Result<zed::SlashCommandOutput, String> {
    let event_type: &str = args.first().map(String::as_str).unwrap_or("fileEdited");
    if !EVENT_TYPES.contains(&event_type) {
        return Err(format!(
            "unknown event type: {}. Use one of: {}",
            event_type,
            EVENT_TYPES.join(", ")
        ));
    }

    let (project, relative_file, absolute_file) = match worktree {
        Some(wt) => {
            let root = wt.root_path();
            let project = project_name_from_root(&root);
            let raw_relative = args.get(1).cloned().unwrap_or_else(|| "unknown".to_string());
            let relative = sanitize_relative_path(&raw_relative);
            let abs = std::path::Path::new(&root).join(&relative);
            let absolute_file = abs.to_string_lossy().to_string();
            (project, relative, absolute_file)
        }
        None => (
            "unknown".to_string(),
            sanitize_relative_path(
                &args.get(1).cloned().unwrap_or_else(|| "unknown".to_string()),
            ),
            "unknown".to_string(),
        ),
    };

    let language: String = language_from_extension(&relative_file);
    let event_time_ms: i64 = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as i64)
        .unwrap_or(0);
    let platform: String = platform_string();
    let operation_type: String = operation_type_for_event(event_type).to_string();

    let body: EventLogBody = EventLogBody {
        project,
        language,
        relative_file: relative_file.clone(),
        absolute_file: absolute_file.clone(),
        editor: "Zed".to_string(),
        platform,
        event_time: event_time_ms,
        event_type: event_type.to_string(),
        operation_type,
    };

    let body_bytes = serde_json::to_vec(&body)
        .map_err(|e| format!("CodeTime: failed to build request: {}", e))?;
    let base = base_url();
    let url = format!("{}/v3/users/event-log", base.trim_end_matches('/'));

    let mut req = HttpRequestBuilder::new()
        .method(HttpMethod::Post)
        .url(&url)
        .header("User-Agent", USER_AGENT)
        .header("Content-Type", "application/json")
        .body(body_bytes);

    if let Some(token) = bearer_token() {
        req = req.header("Authorization", format!("Bearer {}", token));
    }

    let req = req.build().map_err(|e| format!("CodeTime: request setup failed: {}", e))?;
    zed::http_client::fetch(&req).map_err(|e| {
        format!(
            "CodeTime proxy unreachable (check CODETIME_PROXY_URL and network): {}",
            e
        )
    })?;

    let text: String = format!("Reported {} for {}", event_type, relative_file);
    Ok(zed::SlashCommandOutput {
        text: text.clone(),
        sections: vec![zed::SlashCommandOutputSection {
            range: (0..text.len()).into(),
            label: "CodeTime".to_string(),
        }],
    })
}

fn run_status() -> Result<zed::SlashCommandOutput, String> {
    let url_display = base_url_display();
    let auth = if bearer_token().is_some() {
        "set (Bearer)"
    } else {
        "not set"
    };
    let lines = [
        format!("Proxy: {}", url_display),
        format!("CODETIME_API_KEY: {}", auth),
        "".to_string(),
        "Env: CODETIME_PROXY_URL, CODETIME_API_KEY".to_string(),
    ];
    let text = lines.join("\n");
    Ok(zed::SlashCommandOutput {
        text: text.clone(),
        sections: vec![zed::SlashCommandOutputSection {
            range: (0..text.len()).into(),
            label: "CodeTime".to_string(),
        }],
    })
}

zed::register_extension!(CodetimeExtension);

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_project_name_from_root() {
        assert_eq!(project_name_from_root("/home/user/code-time"), "code-time");
        assert_eq!(
            project_name_from_root(r"C:\Users\dev\my-project"),
            "my-project"
        );
        assert_eq!(project_name_from_root(""), "unknown");
    }

    #[test]
    fn test_language_from_extension() {
        assert_eq!(language_from_extension("src/lib.rs"), "rust");
        assert_eq!(language_from_extension("proxy.py"), "python");
        assert_eq!(language_from_extension("create_table.sql"), "sql");
        assert_eq!(language_from_extension("README.md"), "markdown");
        assert_eq!(language_from_extension("file.json"), "json");
        assert_eq!(language_from_extension("config.toml"), "toml");
        assert_eq!(language_from_extension("script.sh"), "shell");
        assert_eq!(language_from_extension("noext"), "unknown");
        assert_eq!(language_from_extension("file.TS"), "typescript");
    }

    #[test]
    fn test_operation_type_for_event() {
        assert_eq!(operation_type_for_event("fileSaved"), "write");
        assert_eq!(operation_type_for_event("fileEdited"), "write");
        assert_eq!(operation_type_for_event("fileCreated"), "write");
        assert_eq!(operation_type_for_event("fileAddedLine"), "write");
        assert_eq!(operation_type_for_event("activateFileChanged"), "read");
        assert_eq!(operation_type_for_event("editorChanged"), "read");
        assert_eq!(operation_type_for_event("changeEditorSelection"), "read");
    }

    #[test]
    fn test_event_types_constant() {
        assert_eq!(EVENT_TYPES.len(), 8);
        assert!(EVENT_TYPES.contains(&"fileSaved"));
        assert!(EVENT_TYPES.contains(&"fileEdited"));
    }

    #[test]
    fn test_sanitize_relative_path() {
        assert_eq!(sanitize_relative_path("src/lib.rs"), "src/lib.rs");
        assert_eq!(sanitize_relative_path("a/../b"), "a/b");
        assert_eq!(sanitize_relative_path(".."), "unknown");
        assert_eq!(sanitize_relative_path(""), "unknown");
        assert_eq!(sanitize_relative_path("  "), "unknown");
        assert!(!sanitize_relative_path(r"foo\bar").contains('\\'));
    }

    #[test]
    fn test_base_url_display() {
        assert_eq!(base_url_display(), "http://localhost:9492");
    }

    #[test]
    fn test_language_from_extension_extended() {
        assert_eq!(language_from_extension("main.go"), "go");
        assert_eq!(language_from_extension("App.kt"), "kotlin");
        assert_eq!(language_from_extension("lib.swift"), "swift");
        assert_eq!(language_from_extension("script.rb"), "ruby");
        assert_eq!(language_from_extension("index.vue"), "vue");
        assert_eq!(language_from_extension("main.zig"), "zig");
        assert_eq!(language_from_extension("style.scss"), "css");
    }
}
