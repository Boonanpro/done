-- Durable job state for Salonboard style posting.
-- The browser worker may still run on a single Windows VM, but job status must
-- survive FastAPI restarts and be visible from the Vercel UI.

CREATE TABLE IF NOT EXISTS salonboard_post_jobs (
    id UUID PRIMARY KEY,
    device_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'needs_human', 'done', 'error')),
    message TEXT,
    style_name TEXT,
    style_id TEXT,
    registered BOOLEAN,
    published BOOLEAN,
    photo_count INT NOT NULL DEFAULT 0,
    fields JSONB,
    images_meta JSONB,
    result JSONB,
    error TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_salonboard_post_jobs_device_created
    ON salonboard_post_jobs(device_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_salonboard_post_jobs_status_created
    ON salonboard_post_jobs(status, created_at DESC);

CREATE OR REPLACE FUNCTION update_salonboard_post_jobs_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS salonboard_post_jobs_updated_at ON salonboard_post_jobs;
CREATE TRIGGER salonboard_post_jobs_updated_at
    BEFORE UPDATE ON salonboard_post_jobs
    FOR EACH ROW EXECUTE FUNCTION update_salonboard_post_jobs_updated_at();

ALTER TABLE salonboard_post_jobs DISABLE ROW LEVEL SECURITY;
