-- Add extend-related columns to skill_proposals
-- decision: create / extend / skip
-- target_skill: 既存スキル名 (extend時)
-- new_actions: 追加アクション (extend時)

ALTER TABLE skill_proposals ADD COLUMN IF NOT EXISTS decision TEXT;
ALTER TABLE skill_proposals ADD COLUMN IF NOT EXISTS target_skill TEXT;
ALTER TABLE skill_proposals ADD COLUMN IF NOT EXISTS new_actions JSONB DEFAULT '[]';

COMMENT ON COLUMN skill_proposals.decision IS 'LLM judgment: create / extend / skip';
COMMENT ON COLUMN skill_proposals.target_skill IS 'Target skill name when decision is extend';
COMMENT ON COLUMN skill_proposals.new_actions IS 'Actions to add when decision is extend';
