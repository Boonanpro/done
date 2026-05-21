-- LINE-style pin support for the chat list.
-- A non-null `pinned_at` means the project is pinned; newer pins sort above
-- older pins (the timestamp also defines the ordering between pinned items).
-- `pinned_at IS NULL` for the vast majority of projects, so the partial index
-- keeps the index tiny while still answering "give me the pinned ones first".

ALTER TABLE projects
    ADD COLUMN IF NOT EXISTS pinned_at TIMESTAMP WITH TIME ZONE;

CREATE INDEX IF NOT EXISTS idx_projects_pinned_at
    ON projects(pinned_at DESC)
    WHERE pinned_at IS NOT NULL;
