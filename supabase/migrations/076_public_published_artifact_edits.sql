-- Delivery sites may read only completed public revisions. Drafts remain
-- private and are never exposed through this policy.
DROP POLICY IF EXISTS "artifact_edit_releases_public_read" ON artifact_edit_releases;
CREATE POLICY "artifact_edit_releases_public_read"
    ON artifact_edit_releases
    FOR SELECT
    USING (true);
