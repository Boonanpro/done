-- Agent runs: project chat execution units backed by Claude Code sessions.

CREATE TABLE IF NOT EXISTS agent_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    room_id UUID NOT NULL REFERENCES chat_rooms(id) ON DELETE CASCADE,
    claude_session_id TEXT,
    parent_run_id UUID REFERENCES agent_runs(id) ON DELETE SET NULL,
    state TEXT NOT NULL DEFAULT 'running',
    active_proposal_id UUID REFERENCES project_proposals(id) ON DELETE SET NULL,
    superseded_by_run_id UUID REFERENCES agent_runs(id) ON DELETE SET NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_project_created
    ON agent_runs(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_runs_room_created
    ON agent_runs(room_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_runs_project_state
    ON agent_runs(project_id, state);

DROP TRIGGER IF EXISTS update_agent_runs_updated_at ON agent_runs;
CREATE TRIGGER update_agent_runs_updated_at
    BEFORE UPDATE ON agent_runs
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

ALTER TABLE execution_events
    ADD COLUMN IF NOT EXISTS run_id UUID REFERENCES agent_runs(id) ON DELETE SET NULL;

ALTER TABLE project_proposals
    ADD COLUMN IF NOT EXISTS run_id UUID REFERENCES agent_runs(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_exec_events_run_seq
    ON execution_events(run_id, seq);
CREATE INDEX IF NOT EXISTS idx_exec_events_run_created
    ON execution_events(run_id, created_at);
CREATE INDEX IF NOT EXISTS idx_project_proposals_run_created
    ON project_proposals(run_id, created_at DESC);

ALTER TABLE agent_runs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own agent runs"
    ON agent_runs FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM projects
            WHERE projects.id = agent_runs.project_id
            AND projects.user_id = auth.uid()
        )
    );

CREATE POLICY "Service role full access agent_runs"
    ON agent_runs FOR ALL
    TO service_role
    USING (true);
