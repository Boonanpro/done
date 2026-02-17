-- Skill Proposals Table
-- Visual Agentのスキル提案を永続化する

CREATE TABLE IF NOT EXISTS skill_proposals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id TEXT NOT NULL,
    instruction TEXT,
    status TEXT NOT NULL DEFAULT 'pending',

    skill_name TEXT,
    description TEXT,
    site TEXT,
    actions JSONB DEFAULT '[]',
    parameters JSONB DEFAULT '[]',
    analysis JSONB DEFAULT '{}',
    steps JSONB DEFAULT '[]',

    approved_at TIMESTAMPTZ,
    generated_at TIMESTAMPTZ,
    generated_skill_name TEXT,
    generated_skill_path TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_skill_proposals_user_id ON skill_proposals(user_id);
CREATE INDEX IF NOT EXISTS idx_skill_proposals_session_id ON skill_proposals(session_id);
CREATE INDEX IF NOT EXISTS idx_skill_proposals_status ON skill_proposals(status);
CREATE INDEX IF NOT EXISTS idx_skill_proposals_updated_at ON skill_proposals(updated_at);

ALTER TABLE skill_proposals ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view their own skill proposals"
    ON skill_proposals FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can create their own skill proposals"
    ON skill_proposals FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update their own skill proposals"
    ON skill_proposals FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "Users can delete their own skill proposals"
    ON skill_proposals FOR DELETE
    USING (auth.uid() = user_id);

CREATE OR REPLACE FUNCTION update_skill_proposals_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_skill_proposals_updated_at
    BEFORE UPDATE ON skill_proposals
    FOR EACH ROW
    EXECUTE FUNCTION update_skill_proposals_updated_at();
