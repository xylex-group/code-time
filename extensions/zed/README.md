# CodeTime Zed extension

Zed extension that talks to the [CodeTime proxy](../../README.md) (OpenAPI-compliant). It fetches tracked minutes and reports events via slash commands.

**Note:** The Zed Extension API does not expose editor lifecycle hooks (file saved, buffer changed, selection, etc.). Tracking is **manual**: run `/codetime_report` when you want to log an event (e.g. after saving or switching context).

## Slash commands

| Command | Description |
|--------|-------------|
| **`/codetime_minutes`** | Fetches your tracked coding minutes from the proxy (`GET /v3/users/self/minutes`) and shows the result in the slash command output. |
| **`/codetime_report`** | Reports one event to the proxy (`POST /v3/users/event-log`). **First argument:** event type (completions available). **Optional second argument:** relative file path (defaults to `unknown` if omitted or when not in a worktree). Example: `codetime_report fileSaved src/lib.rs` |
| **`/codetime_status`** | Shows current configuration: proxy base URL (scheme + host) and whether `CODETIME_API_KEY` is set. Use this to verify env vars before calling `/codetime_minutes` or `/codetime_report`. |

## Configuration

Environment variables (Zed does not expose a settings API for arbitrary keys in extensions):

| Variable | Description |
|----------|-------------|
| **`CODETIME_PROXY_URL`** | Base URL of the CodeTime proxy (e.g. `http://localhost:9492` or `https://codetime.example.com`). Default: `http://localhost:9492`. Only `http://` and `https://` are accepted; otherwise the default is used. |
| **`CODETIME_API_KEY`** | Optional Bearer token. If set, it is sent as `Authorization: Bearer <token>` on both GET minutes and POST event-log. |

Check with `/codetime_status` that the proxy URL and auth are as expected.

## Event types

Same as the proxy’s [event types](../README.md#logged-event-types):

`activateFileChanged`, `editorChanged`, `fileSaved`, `fileAddedLine`, `fileCreated`, `fileEdited`, `changeEditorSelection`, `changeEditorVisibleRanges`.

When you run `/codetime_report`, the first argument offers completions for these event types.

## Detected languages

The extension maps file extensions to a language name sent in the event body. Supported extensions include (among others): `rs`, `py`, `js`, `ts`, `tsx`, `jsx`, `mjs`, `cjs`, `go`, `mod`, `java`, `kt`, `kts`, `swift`, `c`, `h`, `cpp`, `cc`, `cxx`, `rb`, `php`, `vue`, `svelte`, `lua`, `r`, `ex`, `exs`, `erl`, `scala`, `fs`, `zig`, `v`, `nim`, `cr`, `sql`, `md`, `json`, `yaml`, `yml`, `toml`, `html`, `htm`, `css`, `scss`, `less`, `sh`, `bash`, `zsh`. Unknown extensions are sent as the lowercased extension name.

## API

The extension uses the endpoints and body shape from the repo’s [openapi.yaml](../../openapi.yaml): GET `/v3/users/self/minutes`, POST `/v3/users/event-log` with camelCase fields (`project`, `language`, `relativeFile`, `absoluteFile`, `editor`, `platform`, `eventTime`, `eventType`, `operationType`). All requests send `User-Agent: CodeTime Client`.

## Example workflow

1. Start the CodeTime proxy (e.g. `python proxy.py` with env set).
2. In Zed, set `CODETIME_PROXY_URL` and optionally `CODETIME_API_KEY` (e.g. in your shell profile or Zed’s launch environment).
3. Run `/codetime_status` to confirm proxy URL and auth.
4. Run `/codetime_minutes` to see tracked minutes.
5. After saving a file or switching context, run `/codetime_report fileSaved src/lib.rs` (or another event type and path). Use tab completion for the event type.

## Troubleshooting

- **“CodeTime proxy unreachable”** – Check that the proxy is running and that `CODETIME_PROXY_URL` is correct. Run `/codetime_status` to see the resolved URL. Ensure no firewall or VPN is blocking the request.
- **“CodeTime: invalid response from proxy”** – The proxy returned a body that couldn’t be parsed (e.g. HTML error page or non-JSON). Ensure the proxy version matches the expected API (see [openapi.yaml](../../openapi.yaml)).
- **“unknown event type”** – Use one of the allowed event types; the first argument of `/codetime_report` has completions.
- **Relative path shows as “unknown”** – You may not have a worktree open, or you didn’t pass a second argument. Pass the path relative to the project root (e.g. `src/lib.rs`).

For debug output, run Zed from the terminal with `zed --foreground`.

## Build and install

1. Install [Rust via rustup](https://www.rust-lang.org/tools/install).
2. From this directory: `cargo build`.
3. In Zed: **Extensions** → **Install Dev Extension** and select this directory (the one containing `extension.toml`).
