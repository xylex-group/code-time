"""
CodeTime proxy that forwards requests while logging activity with ANSI colors.
"""

import asyncio
import hashlib
import json
import os
import time
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Mapping, Optional
from urllib.parse import urlencode, urlparse

import asyncpg
import httpx
from colorama import Fore, Style, init as colorama_init
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response
import uvicorn

APP_TITLE = "CodeTime Proxy"
DEFAULT_UPSTREAM = "https://api.codetime.dev"
ALLOWED_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]

colorama_init(autoreset=True)
load_dotenv()


@dataclass(frozen=True)
class ProxyConfig:
    upstream: str
    log_dir: Path
    pg_url: Optional[str]


def load_config() -> ProxyConfig:
    upstream = os.environ.get("CODETIME_UPSTREAM", DEFAULT_UPSTREAM).rstrip("/")
    log_dir = Path(os.environ.get("CODETIME_LOG_DIR", "logs"))
    pg_url = os.environ.get("PG_URL")
    return ProxyConfig(upstream=upstream, log_dir=log_dir, pg_url=pg_url)


config = load_config()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.client = httpx.AsyncClient(timeout=30.0)
    app.state.storage = LogStorage(config.log_dir / "traffic.jsonl")
    app.state.database = DatabaseStorage(config.pg_url)
    await app.state.database.initialize()
    app.state.printer = AnsiPrinter()
    try:
        yield
    finally:
        client: Optional[httpx.AsyncClient] = getattr(app.state, "client", None)
        if client:
            await client.aclose()
        db: DatabaseStorage = getattr(app.state, "database")
        await db.close()


app = FastAPI(title=APP_TITLE, lifespan=lifespan)


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
    row_hash: str
    authorization: str

    @classmethod
    def create(
        cls,
        method: str,
        path: str,
        query: Dict[str, str],
        request_headers: Dict[str, str],
        request_body: str,
        response_status: int,
        response_headers: Dict[str, str],
        response_body: str,
        duration_ms: float,
        authorization: str,
    ) -> "LogEntry":
        payload = json.dumps(
            {
                "method": method,
                "path": path,
                "query": query,
                "request_body": request_body,
                "response_status": response_status,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        row_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return cls(
            timestamp=datetime.utcnow().isoformat() + "Z",
            method=method,
            path=path,
            query=query,
            request_headers=request_headers,
            request_body=request_body,
            response_status=response_status,
            response_headers=response_headers,
            response_body=response_body,
            duration_ms=duration_ms,
            row_hash=row_hash,
            authorization=authorization,
        )

    def to_json_line(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


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


class DatabaseStorage:
    def __init__(self, dsn: Optional[str]) -> None:
        self.dsn = dsn
        self.pool: Optional[asyncpg.Pool] = None

    async def initialize(self) -> None:
        if not self.dsn:
            return
        self.pool = await asyncpg.create_pool(
            dsn=self.dsn,
            min_size=1,
            max_size=4,
        )

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()

    async def insert_entry(self, entry: LogEntry) -> None:
        if self.pool is None:
            return
        await self.pool.execute(
            """
            INSERT INTO codetime_entries(
                row_hash,
                method,
                path,
                query,
                request_headers,
                request_body,
                response_status,
                response_headers,
                response_body,
                duration_ms,
                authorization,
                recorded_at
            ) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
            ON CONFLICT (row_hash) DO NOTHING
            """,
            entry.row_hash,
            entry.method,
            entry.path,
            json.dumps(entry.query, ensure_ascii=False),
            json.dumps(entry.request_headers, ensure_ascii=False),
            entry.request_body,
            entry.response_status,
            json.dumps(entry.response_headers, ensure_ascii=False),
            entry.response_body,
            entry.duration_ms,
            entry.authorization,
            datetime.utcnow(),
        )


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
    return f"{config.upstream}/{path.lstrip('/')}"


def build_request_headers(original: Mapping[str, str]) -> Dict[str, str]:
    sanitized = {k: v for k, v in original.items() if k.lower() != "host"}
    netloc = urlparse(config.upstream).netloc
    sanitized["host"] = netloc
    return sanitized


def filter_response_headers(headers: Mapping[str, str]) -> Dict[str, str]:
    forbidden = {"content-encoding", "transfer-encoding", "connection", "keep-alive"}
    return {k: v for k, v in headers.items() if k.lower() not in forbidden}


@app.api_route("/{path:path}", methods=ALLOWED_METHODS)
async def proxy(path: str, request: Request) -> Response:
    client: Optional[httpx.AsyncClient] = getattr(app.state, "client")
    storage: LogStorage = app.state.storage
    database: DatabaseStorage = app.state.database
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

    authorization = request.headers.get("authorization") or request.headers.get("Authorization") or ""

    entry = LogEntry.create(
        method=request.method,
        path=request.url.path,
        query=params,
        request_headers=dict(request.headers),
        request_body=request_body,
        response_status=upstream_response.status_code,
        response_headers=dict(upstream_response.headers),
        response_body=upstream_response.text,
        duration_ms=duration_ms,
        authorization=authorization,
    )

    await asyncio.gather(
        storage.append(entry),
        database.insert_entry(entry),
    )
    printer.print(entry)

    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=filter_response_headers(upstream_response.headers),
        media_type=upstream_response.headers.get("content-type"),
    )


if __name__ == "__main__":
    port = int(os.environ.get("CODETIME_PORT", "9492"))
    uvicorn.run("proxy:app", host="0.0.0.0", port=port, log_level="info")
