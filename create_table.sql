CREATE TABLE codetime_entries (
    id BIGSERIAL PRIMARY KEY,
    row_hash TEXT UNIQUE NOT NULL,
    method TEXT NOT NULL,
    path TEXT NOT NULL,
    query JSON,
    request_headers JSON,
    request_body JSON,
    response_status INTEGER NOT NULL,
    response_headers JSON,
    response_body JSON,
    duration_ms DOUBLE PRECISION NOT NULL,
    auth_header TEXT,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
