-- A site editor has two durable states:
-- * draft: updated while editing and used by the authenticated preview
-- * published: the one immutable revision visible on delivery/custom domains
-- Keeping them separate prevents a half-finished edit from becoming public.

CREATE TABLE IF NOT EXISTS artifact_edit_drafts (
    artifact_slug TEXT PRIMARY KEY,
    overrides JSONB NOT NULL DEFAULT '{}'::jsonb,
    revision INTEGER NOT NULL DEFAULT 0,
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS artifact_edit_releases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_slug TEXT NOT NULL,
    revision INTEGER NOT NULL,
    overrides JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (artifact_slug, revision)
);

CREATE INDEX IF NOT EXISTS idx_artifact_edit_releases_latest
    ON artifact_edit_releases (artifact_slug, revision DESC);

ALTER TABLE artifact_edit_drafts ENABLE ROW LEVEL SECURITY;
ALTER TABLE artifact_edit_releases ENABLE ROW LEVEL SECURITY;

CREATE POLICY "artifact_edit_drafts_owner" ON artifact_edit_drafts
    FOR ALL USING (created_by = auth.uid()) WITH CHECK (created_by = auth.uid());

-- Public reads are served by DAN's backend/service key, never by an anon table policy.
CREATE POLICY "artifact_edit_releases_owner" ON artifact_edit_releases
    FOR ALL USING (created_by = auth.uid()) WITH CHECK (created_by = auth.uid());
