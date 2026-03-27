-- Push notification subscriptions
CREATE TABLE IF NOT EXISTS push_subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    room_id UUID NOT NULL REFERENCES collab_rooms(id) ON DELETE CASCADE,
    sender_type TEXT NOT NULL,          -- 'owner' or 'guest'
    endpoint TEXT NOT NULL,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(room_id, sender_type, endpoint)
);

CREATE INDEX IF NOT EXISTS idx_push_subscriptions_room ON push_subscriptions(room_id);

ALTER TABLE push_subscriptions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role full access push_subscriptions"
    ON push_subscriptions FOR ALL TO service_role USING (true);
