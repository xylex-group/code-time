CREATE TABLE codetime_entries (
    id BIGSERIAL PRIMARY KEY,
    row_hash TEXT UNIQUE NOT NULL,
    method TEXT NOT NULL,
    path TEXT NOT NULL,
    query JSONB,
    request_headers JSONB,
    request_body TEXT,
    response_status INTEGER NOT NULL,
    response_headers JSONB,
    response_body TEXT,
    duration_ms DOUBLE PRECISION NOT NULL,
    auth_header TEXT,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
