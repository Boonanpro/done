-- Add lifecycle/publish state for generated chat artifacts.
-- Preview URLs are public /preview/<slug> routes that mirror /artifacts/<slug>
-- and load inspector_overrides, so they stay aligned with live preview edits.

ALTER TABLE chat_artifact
    ADD COLUMN IF NOT EXISTS artifact_type TEXT NOT NULL DEFAULT 'tool',
    ADD COLUMN IF NOT EXISTS share_url TEXT,
    ADD COLUMN IF NOT EXISTS draft_url TEXT,
    ADD COLUMN IF NOT EXISTS production_url TEXT,
    ADD COLUMN IF NOT EXISTS custom_domain TEXT,
    ADD COLUMN IF NOT EXISTS publish_status TEXT NOT NULL DEFAULT 'preview_live',
    ADD COLUMN IF NOT EXISTS last_publish_error TEXT,
    ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ;

UPDATE chat_artifact
SET
    share_url = COALESCE(share_url, '/preview/' || slug),
    draft_url = COALESCE(draft_url, '/preview/' || slug),
    artifact_type = CASE
        WHEN artifact_type IS NOT NULL AND artifact_type <> '' THEN artifact_type
        WHEN kind IN ('website', 'site', 'hp') THEN 'website'
        WHEN kind = 'dashboard' OR slug ILIKE '%dashboard%' THEN 'dashboard'
        ELSE 'tool'
    END,
    publish_status = COALESCE(NULLIF(publish_status, ''), 'preview_live')
WHERE share_url IS NULL
   OR draft_url IS NULL
   OR artifact_type IS NULL
   OR artifact_type = ''
   OR publish_status IS NULL
   OR publish_status = '';

CREATE INDEX IF NOT EXISTS idx_chat_artifact_type
    ON chat_artifact(artifact_type);

CREATE INDEX IF NOT EXISTS idx_chat_artifact_publish_status
    ON chat_artifact(publish_status);
