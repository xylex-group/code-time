# code-time
# CodeTime proxy

This repository runs a lightweight Python proxy that mirrors the CodeTime client endpoints, logs every request/response pair with ANSI colors, and forwards the traffic to `https://api.codetime.dev`.

## Setup

1. Create a virtual environment (optional but recommended):
   ```bash
   python -m venv .venv
   ```
2. Activate the virtual environment and install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and set your `PG_URL` plus any overrides (`CODETIME_UPSTREAM`, `CODETIME_LOG_DIR`):
   ```bash
   cp .env.example .env
   ```

## Running

Start the proxy with Uvicorn. By default it listens on port 9492:

```bash
uvicorn proxy:app --host 0.0.0.0 --port 9492
```

Or run the module directly; it will launch Uvicorn for you using the same defaults:

```bash
python proxy.py
```

Point your CodeTime client (or a curl command) at `http://localhost:9492` followed by the usual `/v3/...` path. The proxy forwards every request to `https://api.codetime.dev` (or the upstream override) and streams the response back to the client.

## Logging & persistence

- All requests/responses are printed to the terminal with ANSI colors (cyan for requests, green for responses).
- Every interaction is persisted to `logs/traffic.jsonl` (one JSON object per line) and is tagged with a `row_hash`.
- When `PG_URL` is defined in your `.env`, the proxy also inserts each entry (including the `Authorization` header) into the `codetime_entries` table (saved as `auth_header`).

## Configuration

- Set `CODETIME_UPSTREAM` to override the target host (defaults to `https://api.codetime.dev`).
- Set `CODETIME_LOG_DIR` to change where the JSON log file is written (`logs/` by default).
- Set `PG_URL` via `.env` to enable Postgres inserts.
- Set `CODETIME_PORT` (or `PORT`) if you want a different port when running `python proxy.py`.

## Database schema

- Run `psql -f create_table.sql` to create the `codetime_entries` table before starting the proxy (it now stores headers/body as `JSON` plus extracted metadata including `language`).
- Each row stores the JSON payload plus HTTP metadata and enforces uniqueness via `row_hash`. The table now captures `client_ip`, `user_agent`, `windows_username`, `file_extension`, `operation_type`, `git_branch`, `project`, `editor`, `platform`, `event_time`, `absolute_filepath`, and `event_type`.
- Known event types logged in `event_type`:
  - `activateFileChanged`
  - `editorChanged`
  - `fileSaved`
  - `fileAddedLine`
  - `fileCreated`
  - `fileEdited`
  - `changeEditorSelection`
  - `changeEditorVisibleRanges`

## Testing

- **Proxy (Python):** `pip install -r requirements-dev.txt` then `python -m pytest tests/ -v`
- **Zed extension (Rust):** `cd extensions/zed && cargo test`
- **VS Code extension:** `cd extensions/vscode && npm install && npm test`
- **Neovim stub (Lua):** from repo root, `lua extensions/nvim/spec/test_init_spec.lua` (requires Lua 5.1+)

## Notes

- The proxy implements the GET `/v3/users/self/minutes` and POST `/v3/users/event-log` paths (among others) because it captures everything and forwards it transparently.
- This setup can be extended with extra filters or saved analytics as needed.
- The proxy only forwards requests whose `User-Agent` includes `CodeTime Client`; other requests return `403` immediately.
