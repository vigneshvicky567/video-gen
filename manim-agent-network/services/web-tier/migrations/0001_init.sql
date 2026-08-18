-- Neon schema for the web tier. Apply once against the Neon DATABASE_URL.
-- (SQLAlchemy create_all also builds this; the SQL is the source of truth for
--  prod/migrations.)

CREATE TABLE IF NOT EXISTS users (
    clerk_id        TEXT PRIMARY KEY,
    email           TEXT DEFAULT '',
    role            TEXT NOT NULL DEFAULT 'user',     -- user | admin
    daily_job_quota INTEGER,                          -- NULL = use server default
    banned          BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS jobs (
    id                 TEXT PRIMARY KEY,
    owner_user_id      TEXT NOT NULL REFERENCES users(clerk_id),
    topic              TEXT NOT NULL,
    brief              JSONB,
    status             TEXT NOT NULL DEFAULT 'queued', -- queued|running|done|failed|cancelled
    state              JSONB,
    video_url          TEXT,                           -- R2 object key
    target_duration_s  INTEGER,
    idempotency_key    TEXT,
    created_at         TIMESTAMP NOT NULL DEFAULT now(),
    updated_at         TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS jobs_owner_idx   ON jobs (owner_user_id);
CREATE INDEX IF NOT EXISTS jobs_status_idx  ON jobs (status);
CREATE INDEX IF NOT EXISTS jobs_created_idx ON jobs (created_at DESC);
CREATE INDEX IF NOT EXISTS jobs_idem_idx    ON jobs (owner_user_id, idempotency_key);

CREATE TABLE IF NOT EXISTS usage_minutes (
    owner_user_id   TEXT NOT NULL REFERENCES users(clerk_id),
    month           TEXT NOT NULL,                    -- YYYY-MM
    runner_minutes  INTEGER NOT NULL DEFAULT 0,
    jobs_count      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (owner_user_id, month)
);
