-- Stable assistant-turn identity for live execution events.
-- run_id remains the long-running work session; turn_id identifies one
-- assistant response segment within that run, including follow-up boundaries.

ALTER TABLE execution_events
    ADD COLUMN IF NOT EXISTS turn_id UUID;

CREATE INDEX IF NOT EXISTS idx_exec_events_turn_seq
    ON execution_events(turn_id, seq);

CREATE INDEX IF NOT EXISTS idx_exec_events_run_turn_seq
    ON execution_events(run_id, turn_id, seq);
