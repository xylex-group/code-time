"""
CodeTime proxy that forwards requests while logging activity with ANSI colors.
"""

import asyncio
import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Mapping, Optional
from urllib.parse import urlencode, urlparse

import httpx
from colorama import Fore, Style, init as colorama_init
from fastapi import FastAPI, HTTPException, Request, Response

APP_TITLE = "CodeTime Proxy"
DEFAULT_UPSTREAM = "https://api.codetime.dev"
ALLOWED_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]

colorama_init(autoreset=True)

UPSTREAM_BASE = os.environ.get("CODETIME_UPSTREAM", DEFAULT_UPSTREAM).rstrip("/")
LOG_DIR = Path(os.environ.get("CODETIME_LOG_DIR", "logs"))
JSON_LOG_PATH = LOG_DIR / "traffic.jsonl"

app = FastAPI(title=APP_TITLE)


@dataclass(frozen=True)
class LogEntry:
    timestamp: str
    method: str
    path: str
    query: Dict[str, str]
    request_headers: Dict[str, str]
    request_body: str
    response_status: int
    response_headers: Dict[str, str]
    response_body: str
    duration_ms: float

    def to_json_line(self) -> str:
        serialized = asdict(self)
        return json.dumps(serialized, ensure_ascii=False)


class LogStorage:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = asyncio.Lock()

    async def append(self, entry: LogEntry) -> None:
        async with self.lock:
            await asyncio.to_thread(self._write_line, entry.to_json_line())

    def _write_line(self, line: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.write("\n")


class AnsiPrinter:
    @staticmethod
    def print(entry: LogEntry) -> None:
        request_line = AnsiPrinter._build_request_line(entry)
        print(f"{Fore.CYAN}>> {request_line}")
        print(f"{Fore.MAGENTA}   Req headers: {format_headers(entry.request_headers)}")
        if entry.request_body:
            print(f"{Fore.LIGHTBLUE_EX}   Req body: {truncate_preview(entry.request_body)}")
        print(f"{Fore.GREEN}<< {entry.response_status} ({entry.duration_ms:.2f}ms)")
        if entry.response_body:
            print(f"{Fore.LIGHTGREEN_EX}   Resp body: {truncate_preview(entry.response_body)}")
        print(Style.RESET_ALL, end="")

    @staticmethod
    def _build_request_line(entry: LogEntry) -> str:
        if entry.query:
            return f"{entry.method} {entry.path}?{urlencode(entry.query)}"
        return f"{entry.method} {entry.path}"


def truncate_preview(value: str, length: int = 400) -> str:
    if len(value) <= length:
        return value
    return f"{value[:length]}...(truncated {len(value) - length} chars)"


def format_headers(headers: Mapping[str, str]) -> str:
    return ", ".join(f"{k}: {v}" for k, v in headers.items())


def build_target_url(path: str) -> str:
    return f"{UPSTREAM_BASE}/{path.lstrip('/')}"


def build_request_headers(original: Mapping[str, str]) -> Dict[str, str]:
    sanitized = {k: v for k, v in original.items() if k.lower() != "host"}
    netloc = urlparse(UPSTREAM_BASE).netloc
    sanitized["host"] = netloc
    return sanitized


def filter_response_headers(headers: Mapping[str, str]) -> Dict[str, str]:
    forbidden = {"content-encoding", "transfer-encoding", "connection", "keep-alive"}
    return {k: v for k, v in headers.items() if k.lower() not in forbidden}


@app.on_event("startup")
async def on_startup() -> None:
    app.state.client = httpx.AsyncClient(timeout=30.0)
    app.state.storage = LogStorage(JSON_LOG_PATH)
    app.state.printer = AnsiPrinter()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    client: Optional[httpx.AsyncClient] = getattr(app.state, "client", None)
    if client:
        await client.aclose()


@app.api_route("/{path:path}", methods=ALLOWED_METHODS)
async def proxy(path: str, request: Request) -> Response:
    client: Optional[httpx.AsyncClient] = getattr(app.state, "client", None)
    storage: LogStorage = app.state.storage
    printer: AnsiPrinter = app.state.printer

    if client is None:
        raise HTTPException(status_code=503, detail="Upstream client not initialized")

    body = await request.body()
    request_body = body.decode("utf-8", "ignore") if body else ""
    params = dict(request.query_params)

    start = time.perf_counter()
    upstream_response = await client.request(
        request.method,
        build_target_url(path),
        headers=build_request_headers(request.headers),
        params=params,
        content=body,
    )
    duration_ms = (time.perf_counter() - start) * 1000

    entry = LogEntry(
        timestamp=datetime.utcnow().isoformat() + "Z",
        method=request.method,
        path=request.url.path,
        query=params,
        request_headers=dict(request.headers),
        request_body=request_body,
        response_status=upstream_response.status_code,
        response_headers=dict(upstream_response.headers),
        response_body=upstream_response.text,
        duration_ms=duration_ms,
    )

    await storage.append(entry)
    printer.print(entry)

    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=filter_response_headers(upstream_response.headers),
        media_type=upstream_response.headers.get("content-type"),
    )
