"""
CodeTime proxy that forwards requests while logging activity with ANSI colors.
"""

import asyncio
import csv
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from colorama import Fore, Style, init as colorama_init
from fastapi import FastAPI, HTTPException, Request, Response

APP_TITLE = "CodeTime Proxy"
UPSTREAM_BASE = "https://api.codetime.dev"
ALLOWED_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]

colorama_init(autoreset=True)

app = FastAPI(title=APP_TITLE)

client: Optional[httpx.AsyncClient] = None
storage_lock = asyncio.Lock()

LOGS_DIR = Path("logs")
JSON_LOG_PATH = LOGS_DIR / "traffic.jsonl"
CSV_LOG_PATH = LOGS_DIR / "traffic.csv"
CSV_FIELDS = [
    "timestamp",
    "method",
    "path",
    "query",
    "request_headers",
    "request_body",
    "response_status",
    "response_headers",
    "response_body",
    "duration_ms",
]


def truncate_preview(value: str, length: int = 400) -> str:
    if len(value) <= length:
        return value
    return f"{value[:length]}...(truncated {len(value) - length} chars)"


def format_headers(headers: Dict[str, str]) -> str:
    return ", ".join(f"{k}: {v}" for k, v in headers.items())


def ensure_logs_dir() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


def encode_for_csv(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def build_csv_row(entry: Dict[str, Any]) -> Dict[str, str]:
    return {
        "timestamp": entry["timestamp"],
        "method": entry["method"],
        "path": entry["path"],
        "query": encode_for_csv(entry["query"]),
        "request_headers": encode_for_csv(entry["request_headers"]),
        "request_body": entry["request_body"],
        "response_status": str(entry["response_status"]),
        "response_headers": encode_for_csv(entry["response_headers"]),
        "response_body": entry["response_body"],
        "duration_ms": f"{entry['duration_ms']:.2f}",
    }


def write_json(entry: Dict[str, Any]) -> None:
    ensure_logs_dir()
    with JSON_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False))
        handle.write("\n")


def write_csv(entry: Dict[str, Any]) -> None:
    ensure_logs_dir()
    existed = CSV_LOG_PATH.exists()
    with CSV_LOG_PATH.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        if not existed:
            writer.writeheader()
        writer.writerow(build_csv_row(entry))


def print_request_response(
    request: Request,
    request_body: str,
    response: httpx.Response,
    duration_ms: float,
) -> None:
    req_line = f"{request.method} {request.url.path}?{request.url.query}" if request.url.query else f"{request.method} {request.url.path}"
    print(f"{Fore.CYAN}>> {req_line}")
    print(f"{Fore.MAGENTA}   Req headers: {format_headers(dict(request.headers))}")
    if request_body:
        print(f"{Fore.LIGHTBLUE_EX}   Req body: {truncate_preview(request_body)}")

    print(f"{Fore.GREEN}<< {response.status_code} ({duration_ms:.2f}ms)")
    if response.text:
        print(f"{Fore.LIGHTGREEN_EX}   Resp body: {truncate_preview(response.text)}")
    print(Style.RESET_ALL, end="")


async def persist_entry(entry: Dict[str, Any]) -> None:
    async with storage_lock:
        await asyncio.gather(
            asyncio.to_thread(write_json, entry),
            asyncio.to_thread(write_csv, entry),
        )


@app.on_event("startup")
async def on_startup() -> None:
    global client
    client = httpx.AsyncClient(timeout=30.0)


@app.on_event("shutdown")
async def on_shutdown() -> None:
    if client:
        await client.aclose()


@app.api_route("/{path:path}", methods=ALLOWED_METHODS)
async def proxy(path: str, request: Request) -> Response:
    if not client:
        raise HTTPException(status_code=503, detail="Upstream client not ready")

    target_url = f"{UPSTREAM_BASE.rstrip('/')}/{path}"
    body = await request.body()
    params = dict(request.query_params)
    headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}
    headers["Host"] = "api.codetime.dev"

    start = time.perf_counter()
    upstream_response = await client.request(
        request.method,
        target_url,
        headers=headers,
        params=params,
        content=body,
    )
    duration_ms = (time.perf_counter() - start) * 1000

    request_body_text = body.decode("utf-8", "ignore") if body else ""
    timestamp = datetime.utcnow().isoformat() + "Z"

    await persist_entry(
        {
            "timestamp": timestamp,
            "method": request.method,
            "path": request.url.path,
            "query": params,
            "request_headers": dict(request.headers),
            "request_body": request_body_text,
            "response_status": upstream_response.status_code,
            "response_headers": dict(upstream_response.headers),
            "response_body": upstream_response.text,
            "duration_ms": duration_ms,
        }
    )

    print_request_response(request, request_body_text, upstream_response, duration_ms)

    filtered_headers = {
        k: v
        for k, v in upstream_response.headers.items()
        if k.lower() not in {"content-encoding", "transfer-encoding", "connection", "keep-alive"}
    }

    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=filtered_headers,
        media_type=upstream_response.headers.get("content-type"),
    )
