-- Route external replies back to the originating Done chat room.

CREATE TABLE IF NOT EXISTS external_message_routes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE NOT NULL,
    channel VARCHAR(40) NOT NULL,
    external_account_id TEXT,
    external_recipient_id TEXT,
    external_thread_id TEXT,
    external_message_id TEXT,
    routing_key TEXT,
    origin_room_id UUID REFERENCES chat_rooms(id) ON DELETE CASCADE NOT NULL,
    origin_message_id UUID REFERENCES chat_messages(id) ON DELETE SET NULL,
    campaign_id TEXT,
    contact_id TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    last_outbound_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_external_routes_user_channel
    ON external_message_routes(user_id, channel);

CREATE INDEX IF NOT EXISTS idx_external_routes_thread
    ON external_message_routes(user_id, channel, external_thread_id)
    WHERE external_thread_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_external_routes_message
    ON external_message_routes(user_id, channel, external_message_id)
    WHERE external_message_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_external_routes_recipient
    ON external_message_routes(user_id, channel, external_recipient_id, last_outbound_at DESC)
    WHERE external_recipient_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_external_routes_routing_key
    ON external_message_routes(user_id, channel, routing_key)
    WHERE routing_key IS NOT NULL;

ALTER TABLE detected_messages
    ADD COLUMN IF NOT EXISTS routed_room_id UUID REFERENCES chat_rooms(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS routing_confidence NUMERIC,
    ADD COLUMN IF NOT EXISTS routing_reason TEXT,
    ADD COLUMN IF NOT EXISTS routed_at TIMESTAMP WITH TIME ZONE;

CREATE INDEX IF NOT EXISTS idx_detected_messages_routed_room
    ON detected_messages(routed_room_id)
    WHERE routed_room_id IS NOT NULL;

ALTER TABLE external_message_routes ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role full access external_message_routes"
    ON external_message_routes FOR ALL
    TO service_role
    USING (true);

CREATE POLICY "Users can view own external_message_routes"
    ON external_message_routes FOR SELECT
    USING (auth.uid() = user_id);

