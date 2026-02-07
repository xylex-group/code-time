# Editor extensions for CodeTime proxy

This folder holds editor-specific integration stubs and configs so CodeTime-style events can be sent to the [code-time](../README.md) proxy (default `http://localhost:9492`).

## Logged event types

The proxy persists entries with an `event_type` field. Known values (see main [README.md](../README.md) and `codetime_entries.event_type`) are:

| Event type | Description |
|------------|-------------|
| `activateFileChanged` | Active file in the editor changed |
| `editorChanged` | Editor (e.g. window/tab) changed |
| `fileSaved` | File was saved |
| `fileAddedLine` | A line was added to a file |
| `fileCreated` | A new file was created |
| `fileEdited` | File content was edited |
| `changeEditorSelection` | Editor selection changed |
| `changeEditorVisibleRanges` | Visible range in the editor changed |

Extensions here should map editor events to these types and POST to `/v3/users/event-log` (or use the same API shape the proxy expects). The proxy only forwards requests whose `User-Agent` includes `CodeTime Client`; other requests get `403`.

## Subdirectories

- **vscode/** – VS Code extension stub (TypeScript/JSON).
- **nvim/** – Neovim plugin / config stub (Lua).
- **zed/** – Zed editor extension (Rust). Slash commands `/codetime_minutes` and `/codetime_report` to fetch minutes and report events. Zed does not expose editor lifecycle hooks, so event reporting is manual.
