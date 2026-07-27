-- A running agent turn must retain the exact user message that started it.
-- This makes cancellation and draft restoration independent of a mounted UI.
ALTER TABLE agent_runs
    ADD COLUMN IF NOT EXISTS origin_message_id UUID
        REFERENCES chat_messages(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_agent_runs_origin_message
    ON agent_runs(origin_message_id);
