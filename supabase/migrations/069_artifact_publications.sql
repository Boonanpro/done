-- Site-level publication ledger.
-- A chat artifact is the thing the user made; a publication is a concrete,
-- independently deployable release of that artifact.  Custom domains are
-- optional aliases of a publication, never a prerequisite for publishing.

CREATE TABLE IF NOT EXISTS artifact_publication (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_id UUID NOT NULL REFERENCES chat_artifact(id) ON DELETE CASCADE,
    release_number INTEGER NOT NULL,
    source_revision TEXT NOT NULL,
    source_kind TEXT NOT NULL DEFAULT 'git',
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'shared', 'deploying', 'live', 'failed', 'retired')),
    -- Every site has its own delivery target.  It may be a Vercel project now,
    -- without imposing a custom domain on the site owner.
    deployment_provider TEXT NOT NULL DEFAULT 'vercel',
    deployment_project TEXT,
    deployment_id TEXT,
    shared_url TEXT,
    production_url TEXT,
    custom_domain TEXT,
    domain_status TEXT NOT NULL DEFAULT 'not_requested'
        CHECK (domain_status IN ('not_requested', 'pending_payment', 'purchasing',
                                 'configuring_dns', 'verifying', 'live', 'failed')),
    job_status JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at TIMESTAMPTZ,
    UNIQUE (artifact_id, release_number)
);

-- A project is unique only once it has actually been provisioned.  Treating
-- NULL as equal here would make every newly created (not-yet-provisioned)
-- release collide with the first one.
CREATE UNIQUE INDEX IF NOT EXISTS idx_artifact_publication_deployment_project
    ON artifact_publication(deployment_provider, deployment_project)
    WHERE deployment_project IS NOT NULL;

-- A custom domain is optional, but a claimed domain must never be connected to
-- two releases at the same time.
CREATE UNIQUE INDEX IF NOT EXISTS idx_artifact_publication_custom_domain
    ON artifact_publication(custom_domain)
    WHERE custom_domain IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_artifact_publication_artifact_created
    ON artifact_publication(artifact_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_artifact_publication_status
    ON artifact_publication(status, domain_status);

COMMENT ON TABLE artifact_publication IS
    'Independent site releases. shared_url is optional-domain public delivery; production_url is the canonical URL when a custom domain is live.';
