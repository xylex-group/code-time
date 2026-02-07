"""
CodeTime proxy that forwards requests while logging activity with ANSI colors.
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
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
MAX_REQUEST_BODY_BYTES = 2 * 1024 * 1024  # 2 MiB
MAX_JSON_BODY_BYTES = 512 * 1024  # 512 KiB for parse_body_json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("codetime_proxy")
colorama_init(autoreset=True)
load_dotenv()


@dataclass(frozen=True)
class ProxyConfig:
    upstream: str
    log_dir: Path
    pg_url: Optional[str]


def load_config() -> ProxyConfig:
    raw_upstream = (os.environ.get("CODETIME_UPSTREAM") or DEFAULT_UPSTREAM).strip().rstrip("/")
    if not raw_upstream:
        raw_upstream = DEFAULT_UPSTREAM
    parsed = urlparse(raw_upstream)
    if not parsed.scheme or not parsed.netloc:
        logger.warning("invalid CODETIME_UPSTREAM %r, using default", raw_upstream)
        raw_upstream = DEFAULT_UPSTREAM
    upstream = raw_upstream

    log_dir_raw = (os.environ.get("CODETIME_LOG_DIR") or "logs").strip() or "logs"
    log_dir = Path(log_dir_raw).resolve()
    pg_url = (os.environ.get("PG_URL") or "").strip() or None
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
    auth_header: str
    client_ip: Optional[str]
    user_agent: Optional[str]
    windows_username: Optional[str]
    file_extension: Optional[str]
    operation_type: Optional[str]
    git_branch: Optional[str]
    project: Optional[str]
    editor: Optional[str]
    platform: Optional[str]
    event_time: Optional[datetime]
    absolute_filepath: Optional[str]
    event_type: Optional[str]
    language: Optional[str]

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
        auth_header: str,
        client_ip: Optional[str],
        user_agent: Optional[str],
        windows_username: Optional[str],
        file_extension: Optional[str],
        operation_type: Optional[str],
        git_branch: Optional[str],
        project: Optional[str],
        editor: Optional[str],
        platform: Optional[str],
        event_time: Optional[datetime],
        absolute_filepath: Optional[str],
        event_type: Optional[str],
        language: Optional[str],
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
            timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
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
            auth_header=auth_header,
            client_ip=client_ip,
            user_agent=user_agent,
            windows_username=windows_username,
            file_extension=file_extension,
            operation_type=operation_type,
            git_branch=git_branch,
            project=project,
            editor=editor,
            platform=platform,
            event_time=event_time,
            absolute_filepath=absolute_filepath,
            event_type=event_type,
            language=language,
        )

    def to_json_line(self) -> str:
        serializable = asdict(self)
        if self.event_time:
            serializable["event_time"] = self.event_time.isoformat()
        return json.dumps(serializable, ensure_ascii=False)


class LogStorage:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = asyncio.Lock()

    async def append(self, entry: LogEntry) -> None:
        async with self.lock:
            try:
                await asyncio.to_thread(self._write_line, entry.to_json_line())
            except OSError as e:
                logger.warning("failed to write log entry: %s", e)
            except Exception as e:
                logger.exception("unexpected error writing log: %s", e)

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
        try:
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
                auth_header,
                client_ip,
                user_agent,
                windows_username,
                file_extension,
                operation_type,
                git_branch,
                project,
                editor,
                platform,
                event_time,
                absolute_filepath,
                event_type,
                language,
                recorded_at
            ) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24,$25)
            ON CONFLICT (row_hash) DO NOTHING
            """,
            entry.row_hash,
            entry.method,
            entry.path,
            json.dumps(entry.query, ensure_ascii=False),
            json.dumps(entry.request_headers, ensure_ascii=False),
            json.dumps(entry.request_body, ensure_ascii=True),
            entry.response_status,
            json.dumps(entry.response_headers, ensure_ascii=False),
            json.dumps(entry.response_body, ensure_ascii=True),
            entry.duration_ms,
            entry.auth_header,
            entry.client_ip,
            entry.user_agent,
            entry.windows_username,
            entry.file_extension,
            entry.operation_type,
            entry.git_branch,
            entry.project,
            entry.editor,
            entry.platform,
            entry.event_time,
            entry.absolute_filepath,
            entry.event_type,
            entry.language,
            datetime.now(timezone.utc),
            )
        except (asyncpg.PostgresError, OSError, ValueError) as e:
            logger.warning("failed to insert entry into Postgres: %s", e)
        except Exception as e:  # pragma: no cover
            logger.exception("unexpected error inserting entry: %s", e)


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


_IPV4_RE = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")
_JSON_SANITIZE_RE = re.compile(r"[^\x09\x0A\x0D\x20-\x7E]+")


def extract_client_ip(headers: Mapping[str, str]) -> Optional[str]:
    if not headers:
        return None
    candidates = []
    for key in ("x-real-ip", "x-forwarded-for", "x-forwarded"):
        value = headers.get(key)
        if value is None or not isinstance(value, str):
            continue
        candidates.extend(part.strip() for part in value.split(",") if part)

    for ip in candidates:
        if _IPV4_RE.fullmatch(ip):
            return ip
    host = headers.get("host")
    if isinstance(host, str) and _IPV4_RE.fullmatch(host):
        return host
    return None


def extract_user_agent(headers: Mapping[str, str]) -> Optional[str]:
    ua = headers.get("user-agent")
    return ua if isinstance(ua, str) else None


def extract_windows_username(path: Optional[str]) -> Optional[str]:
    if not path or not isinstance(path, str):
        return None
    match = re.search(r"[cC]:\\Users\\([^\\]+)\\", path)
    if match:
        return match.group(1)
    return None


def extract_file_extension(path: Optional[str]) -> Optional[str]:
    if not path or not isinstance(path, str):
        return None
    _, ext = os.path.splitext(path)
    return ext.lower() if ext else None


def parse_body_json(body: str) -> Dict[str, Any]:
    if not body or not isinstance(body, str):
        return {}
    if len(body.encode("utf-8")) > MAX_JSON_BODY_BYTES:
        logger.debug("request body too large to parse as JSON, skipping")
        return {}
    try:
        parsed = json.loads(body)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}
    except (TypeError, ValueError):
        return {}


def _safe_str(value: Any, max_len: int = 2048) -> Optional[str]:
    """Coerce value to string for metadata; cap length and return None for invalid."""
    if value is None:
        return None
    if isinstance(value, str):
        s = value
    elif isinstance(value, (int, float, bool)):
        s = str(value)
    else:
        return None
    return s[:max_len] if len(s) > max_len else s


def collect_metadata(body: str, headers: Mapping[str, str]) -> Dict[str, Any]:
    data = parse_body_json(body)
    if not isinstance(data, dict):
        data = {}
    absolute_file = _safe_str(data.get("absoluteFile") or data.get("absolute_filepath"))
    event_time_value = data.get("eventTime")
    event_time = None
    if isinstance(event_time_value, (int, float)):
        try:
            event_time = datetime.fromtimestamp(event_time_value / 1000.0, tz=timezone.utc)
        except (OSError, ValueError, OverflowError):
            event_time = None
    elif isinstance(event_time_value, str):
        try:
            event_time = datetime.fromtimestamp(float(event_time_value) / 1000.0, tz=timezone.utc)
        except (ValueError, TypeError, OverflowError):
            event_time = None

    return {
        "client_ip": extract_client_ip(headers),
        "user_agent": extract_user_agent(headers),
        "windows_username": extract_windows_username(absolute_file),
        "file_extension": extract_file_extension(absolute_file),
        "operation_type": _safe_str(data.get("operationType") or data.get("operation_type"), max_len=64),
        "git_branch": _safe_str(data.get("gitBranch") or data.get("git_branch")),
        "project": _safe_str(data.get("project")),
        "editor": _safe_str(data.get("editor")),
        "platform": _safe_str(data.get("platform")),
        "event_time": event_time,
        "absolute_filepath": absolute_file,
        "event_type": _safe_str(data.get("eventType") or data.get("event_type"), max_len=64),
        "language": _safe_str(data.get("language"), max_len=64),
    }


def sanitize_json_text(text: str) -> str:
    if not text or not isinstance(text, str):
        return "{}"
    cleaned = _JSON_SANITIZE_RE.sub("", text)
    try:
        json.loads(cleaned)
        return cleaned
    except json.JSONDecodeError:
        return cleaned


def build_target_url(path: str) -> str:
    safe_path = (path or "").strip().lstrip("/") or ""
    return f"{config.upstream}/{safe_path}"


def build_request_headers(original: Mapping[str, str]) -> Dict[str, str]:
    sanitized: Dict[str, str] = {}
    for k, v in original.items():
        if k and k.lower() == "host":
            continue
        if k and v is not None and isinstance(v, str):
            sanitized[k] = v
    netloc = urlparse(config.upstream).netloc or ""
    sanitized["host"] = netloc
    return sanitized


def filter_response_headers(headers: Mapping[str, str]) -> Dict[str, str]:
    forbidden = {"content-encoding", "transfer-encoding", "connection", "keep-alive"}
    return {
        k: (v if isinstance(v, str) else str(v))
        for k, v in headers.items()
        if k and k.lower() not in forbidden and v is not None
    }


@app.api_route("/{path:path}", methods=ALLOWED_METHODS)
async def proxy(path: str, request: Request) -> Response:
    user_agent_header = request.headers.get("user-agent", "")
    if "CodeTime Client" not in user_agent_header:
        return Response(status_code=403, content=b"Unsupported client")
    client: Optional[httpx.AsyncClient] = getattr(app.state, "client")
    storage: LogStorage = app.state.storage
    database: DatabaseStorage = app.state.database
    printer: AnsiPrinter = app.state.printer

    if client is None:
        raise HTTPException(status_code=503, detail="Upstream client not initialized")

    body = await request.body()
    if len(body) > MAX_REQUEST_BODY_BYTES:
        logger.warning("request body too large: %d bytes", len(body))
        raise HTTPException(status_code=413, detail="Request body too large")
    request_body = body.decode("utf-8", "ignore") if body else ""
    params = dict(request.query_params)

    start = time.perf_counter()
    try:
        upstream_response = await client.request(
            request.method,
            build_target_url(path),
            headers=build_request_headers(request.headers),
            params=params,
            content=body,
        )
    except httpx.TimeoutException as e:
        logger.warning("upstream timeout: %s", e)
        raise HTTPException(status_code=504, detail="Upstream timeout") from e
    except httpx.ConnectError as e:
        logger.warning("upstream connection error: %s", e)
        raise HTTPException(status_code=502, detail="Upstream unreachable") from e
    except httpx.HTTPError as e:
        logger.exception("upstream request failed: %s", e)
        raise HTTPException(status_code=502, detail="Upstream error") from e
    duration_ms = (time.perf_counter() - start) * 1000

    raw_response_text = upstream_response.text or ""
    sanitized_response_text = sanitize_json_text(raw_response_text)
    response_bytes = sanitized_response_text.encode("utf-8")

    auth_header = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    metadata = collect_metadata(request_body, request.headers)

    entry = LogEntry.create(
        method=request.method,
        path=request.url.path,
        query=params,
        request_headers=dict(request.headers),
        request_body=request_body,
        response_status=upstream_response.status_code,
        response_headers=dict(upstream_response.headers),
        response_body=sanitized_response_text,
        duration_ms=duration_ms,
        auth_header=auth_header,
        **metadata,
    )

    tasks = [storage.append(entry)]
    if database.pool:
        tasks.append(database.insert_entry(entry))

    try:
        await asyncio.gather(*tasks)
    except Exception:  # pragma: no cover
        logger.exception("error while recording entry")
    printer.print(entry)

    return Response(
        content=response_bytes,
        status_code=upstream_response.status_code,
        headers=filter_response_headers(upstream_response.headers),
        media_type=upstream_response.headers.get("content-type"),
    )


if __name__ == "__main__":
    port = int(os.environ.get("CODETIME_PORT", "9492"))
    uvicorn.run("proxy:app", host="0.0.0.0", port=port, log_level="info")
