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

Point your CodeTime client (or a curl command) at `http://localhost:9492` followed by the usual `/v3/...` path. The proxy forwards every request to `https://api.codetime.dev` (or the upstream override) and streams the response back to the client.

## Logging & persistence

- All requests/responses are printed to the terminal with ANSI colors (cyan for requests, green for responses).
- Every interaction is persisted to `logs/traffic.jsonl` (one JSON object per line) and is tagged with a `row_hash`.
- When `PG_URL` is defined in your `.env`, the proxy also inserts each entry (including the `Authorization` header) into the `codetime_entries` table.

## Configuration

- Set `CODETIME_UPSTREAM` to override the target host (defaults to `https://api.codetime.dev`).
- Set `CODETIME_LOG_DIR` to change where the JSON log file is written (`logs/` by default).
- Set `PG_URL` via `.env` to enable Postgres inserts.

## Database schema

- Run `psql -f create_table.sql` to create the `codetime_entries` table before starting the proxy (it now includes an `authorization` column for the token).
- Each row stores the JSON payload plus HTTP metadata and enforces uniqueness via `row_hash`.

## Notes

- The proxy implements the GET `/v3/users/self/minutes` and POST `/v3/users/event-log` paths (among others) because it captures everything and forwards it transparently.
- This setup can be extended with extra filters or saved analytics as needed.
