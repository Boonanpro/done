-- Drop project_proposals system (replaced by observer-based plan management)

-- 1. Remove foreign key and column from agent_runs
ALTER TABLE agent_runs DROP COLUMN IF EXISTS active_proposal_id;

-- 2. Drop project_proposals table
DROP TABLE IF EXISTS project_proposals CASCADE;

-- 3. Remove 'proposed' and 'approved' from projects status
-- (These were only used by the proposal workflow)
-- Note: PostgreSQL doesn't support DROP VALUE from enums easily,
-- but since we're using TEXT columns (not enum types), no action needed.
