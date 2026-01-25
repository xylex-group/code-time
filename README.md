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

## Running

Start the proxy with Uvicorn. By default it listens on port 9492:

```bash
uvicorn proxy:app --host 0.0.0.0 --port 9492
```

Point your CodeTime client (or a curl command) at `http://localhost:8000` followed by the usual `/v3/...` path. The proxy will forward every request to `https://api.codetime.dev` and stream the upstream response back to the client.

## Logging & persistence

- All requests/responses are printed to the terminal with ANSI colors (cyan for requests, green for responses) to make the flow easy to scan.
- The proxy persists each interaction in `logs/traffic.jsonl` (JSON lines) and `logs/traffic.csv`. The CSV includes request/response headers, bodies, status, and timing metadata.
- The `logs/` directory is created automatically and is ignored by Git via `.gitignore`.

## Notes

- The proxy implements the GET `/v3/users/self/minutes` and POST `/v3/users/event-log` paths (among others) because it captures everything and forwards it transparently.
- This setup can be extended with extra filters or saved analytics as needed.
