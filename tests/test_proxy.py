"""Tests for the CodeTime proxy (proxy.py)."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from proxy import (
    build_request_headers,
    build_target_url,
    collect_metadata,
    extract_client_ip,
    extract_file_extension,
    extract_user_agent,
    extract_windows_username,
    filter_response_headers,
    load_config,
    parse_body_json,
    sanitize_json_text,
)


class TestLoadConfig:
    def test_load_config_upstream_strips_trailing_slash(self):
        with patch.dict(
            os.environ,
            {"CODETIME_UPSTREAM": "https://api.example.com/", "CODETIME_LOG_DIR": "logs"},
            clear=False,
        ):
            cfg = load_config()
            assert cfg.upstream == "https://api.example.com"

    def test_load_config_log_dir(self):
        with patch.dict(os.environ, {"CODETIME_LOG_DIR": "custom_logs"}, clear=False):
            cfg = load_config()
            assert cfg.log_dir.name == "custom_logs"

    def test_load_config_pg_url(self):
        with patch.dict(os.environ, {"PG_URL": "postgres://localhost/db"}, clear=False):
            cfg = load_config()
            assert cfg.pg_url == "postgres://localhost/db"

    def test_load_config_empty_upstream_uses_default(self):
        with patch.dict(os.environ, {"CODETIME_UPSTREAM": "", "CODETIME_LOG_DIR": "logs"}, clear=False):
            cfg = load_config()
            assert cfg.upstream  # default restored or validated


class TestExtractClientIp:
    def test_x_real_ip(self):
        assert extract_client_ip({"x-real-ip": "192.168.1.1"}) == "192.168.1.1"

    def test_x_forwarded_for_first(self):
        assert extract_client_ip({"x-forwarded-for": "10.0.0.1, 10.0.0.2"}) == "10.0.0.1"

    def test_no_ip(self):
        assert extract_client_ip({"host": "api.example.com"}) is None

    def test_invalid_ip_ignored(self):
        assert extract_client_ip({"x-real-ip": "not-an-ip"}) is None

    def test_empty_headers_returns_none(self):
        assert extract_client_ip({}) is None

    def test_non_string_header_ignored(self):
        assert extract_client_ip({"x-real-ip": 123}) is None
        assert extract_client_ip({"x-forwarded-for": None}) is None


class TestExtractUserAgent:
    def test_present(self):
        assert extract_user_agent({"user-agent": "CodeTime Client"}) == "CodeTime Client"

    def test_missing(self):
        assert extract_user_agent({}) is None

    def test_non_string_returns_none(self):
        assert extract_user_agent({"user-agent": 123}) is None
        assert extract_user_agent({"user-agent": None}) is None


class TestExtractWindowsUsername:
    def test_windows_path(self):
        assert extract_windows_username(r"C:\Users\alice\code\foo") == "alice"
        assert extract_windows_username(r"c:\Users\bob\file.txt") == "bob"

    def test_non_windows(self):
        assert extract_windows_username("/home/alice/foo") is None
        assert extract_windows_username(None) is None

    def test_non_string_returns_none(self):
        assert extract_windows_username(123) is None
        assert extract_windows_username("") is None


class TestExtractFileExtension:
    def test_with_ext(self):
        assert extract_file_extension("/path/to/file.rs") == ".rs"
        assert extract_file_extension(r"C:\code\file.sql") == ".sql"

    def test_no_ext(self):
        assert extract_file_extension("/path/noext") is None

    def test_none(self):
        assert extract_file_extension(None) is None

    def test_empty_string_returns_none(self):
        assert extract_file_extension("") is None

    def test_non_string_returns_none(self):
        assert extract_file_extension(123) is None


class TestParseBodyJson:
    def test_valid(self):
        assert parse_body_json('{"a": 1}') == {"a": 1}

    def test_invalid(self):
        assert parse_body_json("not json") == {}

    def test_empty_string_returns_empty_dict(self):
        assert parse_body_json("") == {}

    def test_null_literal_returns_empty_dict(self):
        assert parse_body_json("null") == {}

    def test_array_returns_empty_dict(self):
        assert parse_body_json("[1,2,3]") == {}

    def test_number_returns_empty_dict(self):
        assert parse_body_json("42") == {}

    def test_none_input_returns_empty_dict(self):
        assert parse_body_json(None) == {}  # type: ignore[arg-type]


class TestCollectMetadata:
    def test_camelCase_event_log(self):
        body = json.dumps({
            "project": "my-project",
            "language": "rust",
            "absoluteFile": r"C:\Users\dev\my-project\src\lib.rs",
            "eventType": "fileSaved",
            "operationType": "write",
            "eventTime": 1700000000000,
        })
        meta = collect_metadata(body, {"user-agent": "CodeTime Client"})
        assert meta["project"] == "my-project"
        assert meta["event_type"] == "fileSaved"
        assert meta["operation_type"] == "write"
        assert meta["language"] == "rust"
        assert meta["absolute_filepath"] == r"C:\Users\dev\my-project\src\lib.rs"
        assert meta["event_time"] is not None

    def test_snake_case_fallback(self):
        body = json.dumps({"event_type": "fileEdited", "operation_type": "read"})
        meta = collect_metadata(body, {})
        assert meta["event_type"] == "fileEdited"
        assert meta["operation_type"] == "read"

    def test_event_time_string_parsed(self):
        body = json.dumps({"eventTime": "1700000000000"})
        meta = collect_metadata(body, {})
        assert meta["event_time"] is not None

    def test_event_time_invalid_ignored(self):
        body = json.dumps({"eventTime": "not-a-number"})
        meta = collect_metadata(body, {})
        assert meta["event_time"] is None

    def test_non_dict_json_returns_safe_metadata(self):
        meta = collect_metadata("[1,2,3]", {})
        assert meta["client_ip"] is None
        assert meta["event_type"] is None
        assert meta["project"] is None

    def test_missing_keys_do_not_raise(self):
        meta = collect_metadata("{}", {})
        assert "event_type" in meta
        assert meta["event_type"] is None
        assert meta["language"] is None


class TestSanitizeJsonText:
    def test_clean_passthrough(self):
        s = '{"x": 1}'
        assert sanitize_json_text(s) == s

    def test_strips_invalid_unicode(self):
        cleaned = sanitize_json_text('{"x": 1}\x00\x01')
        assert "\x00" not in cleaned
        assert json.loads(cleaned) == {"x": 1}

    def test_empty_returns_empty_object(self):
        assert sanitize_json_text("") == "{}"

    def test_none_returns_empty_object(self):
        assert sanitize_json_text(None) == "{}"  # type: ignore[arg-type]


class TestBuildTargetUrl:
    def test_path_joining(self):
        with patch("proxy.config", MagicMock(upstream="https://api.example.com")):
            assert build_target_url("/v3/users/event-log") == "https://api.example.com/v3/users/event-log"
            assert build_target_url("v3/users/event-log") == "https://api.example.com/v3/users/event-log"

    def test_empty_path_joins_without_double_slash(self):
        with patch("proxy.config", MagicMock(upstream="https://api.example.com")):
            assert build_target_url("") == "https://api.example.com/"
            assert build_target_url("/") == "https://api.example.com/"


class TestBuildRequestHeaders:
    def test_host_replaced(self):
        with patch("proxy.config", MagicMock(upstream="https://codetime.example.com")):
            out = build_request_headers({"host": "localhost:9492", "authorization": "Bearer x"})
            assert out["host"] == "codetime.example.com"
            assert out["authorization"] == "Bearer x"

    def test_non_string_header_value_excluded(self):
        with patch("proxy.config", MagicMock(upstream="https://x.com")):
            out = build_request_headers({"x-foo": 123, "host": "y"})
            assert "x-foo" not in out or isinstance(out.get("x-foo"), str)
            assert out["host"] == "x.com"


class TestFilterResponseHeaders:
    def test_forbidden_removed(self):
        h = {"content-type": "application/json", "content-encoding": "gzip", "connection": "close"}
        out = filter_response_headers(h)
        assert "content-type" in out
        assert "content-encoding" not in out
        assert "connection" not in out

    def test_none_value_excluded(self):
        out = filter_response_headers({"content-type": "application/json", "x-nil": None})
        assert "content-type" in out
        assert "x-nil" not in out


class TestProxyApp:
    """Test the FastAPI app (403 when User-Agent is not CodeTime Client)."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from proxy import app
        return TestClient(app)

    def test_403_when_user_agent_not_codetime_client(self, client):
        response = client.get("/v3/users/self/minutes", headers={"User-Agent": "Other Client"})
        assert response.status_code == 403
        assert response.content == b"Unsupported client"

    def test_403_when_user_agent_empty(self, client):
        response = client.get("/v3/users/self/minutes")
        assert response.status_code == 403
        assert response.content == b"Unsupported client"
