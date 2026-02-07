# CodeTime Proxy Client (VS Code stub)

Stub VS Code extension that can send CodeTime-style events to the [code-time](../../README.md) proxy.

## Event types

Map editor activity to these `event_type` values when posting to `/v3/users/event-log`:

- `activateFileChanged` – active file changed
- `editorChanged` – editor/window changed
- `fileSaved` – file saved
- `fileAddedLine` – line added
- `fileCreated` – file created
- `fileEdited` – file edited
- `changeEditorSelection` – selection changed
- `changeEditorVisibleRanges` – visible range changed

## Configuration

- **codetimeProxy.baseUrl** – Proxy base URL (default: `http://localhost:9492`).
- **codetimeProxy.enabled** – Turn event sending on/off.

## Setup

1. `npm install`
2. `npm run compile`
3. Run from VS Code (F5) or package as `.vsix`.

Requests must use `User-Agent: CodeTime Client` or the proxy returns 403.
