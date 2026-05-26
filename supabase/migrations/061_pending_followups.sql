-- Deferred follow-ups: let Dan promise "I'll report when it's done" and have a
-- background poller actually wake Dan up later to check and report.
--
-- Internal infra table (no RLS / no client access; written by the backend via
-- the service-role key only). Dan calls the schedule_followup tool during a
-- turn -> a row is inserted with fire_at = now + delay. A poller in dan-core
-- picks up due rows and re-invokes the agent for that room, posting the report
-- to the chat. This exists because the agent is turn-based and cannot send a
-- message after its turn ends.

CREATE TABLE IF NOT EXISTS pending_followups (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    room_id     TEXT NOT NULL,
    user_id     TEXT,
    note        TEXT NOT NULL,                    -- what Dan is waiting on / should check & report
    fire_at     TIMESTAMPTZ NOT NULL,             -- when to wake Dan up
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending | firing | done | cancelled
    attempts    INT  NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Poller query: due pending rows, oldest first.
CREATE INDEX IF NOT EXISTS idx_pending_followups_due
    ON pending_followups(status, fire_at);

-- Per-room lookups (rate limiting / cancellation on new user activity).
CREATE INDEX IF NOT EXISTS idx_pending_followups_room
    ON pending_followups(room_id, status);
