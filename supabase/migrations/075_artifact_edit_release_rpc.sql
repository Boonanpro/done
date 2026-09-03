-- Publishing has to be a single database operation: two browser tabs must
-- never calculate the same next revision and overwrite one another.
CREATE OR REPLACE FUNCTION publish_artifact_edit_release(
    p_artifact_slug TEXT,
    p_created_by UUID,
    p_overrides JSONB
)
RETURNS artifact_edit_releases
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_next_revision INTEGER;
    v_release artifact_edit_releases;
BEGIN
    -- Per-site transaction lock. Different sites can still publish in parallel.
    PERFORM pg_advisory_xact_lock(hashtext(p_artifact_slug));

    SELECT COALESCE(MAX(revision), 0) + 1
      INTO v_next_revision
      FROM artifact_edit_releases
     WHERE artifact_slug = p_artifact_slug;

    INSERT INTO artifact_edit_releases (artifact_slug, revision, overrides, created_by)
    VALUES (p_artifact_slug, v_next_revision, p_overrides, p_created_by)
    RETURNING * INTO v_release;

    RETURN v_release;
END;
$$;

REVOKE ALL ON FUNCTION publish_artifact_edit_release(TEXT, UUID, JSONB) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION publish_artifact_edit_release(TEXT, UUID, JSONB) TO service_role;
