-- Persist per-room unread state so room lists do not scan chat_messages.

ALTER TABLE chat_room_members
    ADD COLUMN IF NOT EXISTS unread_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_read_message_id UUID REFERENCES chat_messages(id) ON DELETE SET NULL;

ALTER TABLE chat_rooms
    ADD COLUMN IF NOT EXISTS last_message_at TIMESTAMP WITH TIME ZONE;

CREATE INDEX IF NOT EXISTS idx_chat_room_members_user_unread
    ON chat_room_members(user_id, unread_count)
    WHERE unread_count > 0;

CREATE INDEX IF NOT EXISTS idx_chat_rooms_last_message_at
    ON chat_rooms(last_message_at DESC);

UPDATE chat_rooms r
SET last_message_at = latest.created_at
FROM (
    SELECT room_id, MAX(created_at) AS created_at
    FROM chat_messages
    GROUP BY room_id
) AS latest
WHERE r.id = latest.room_id
  AND r.last_message_at IS NULL;

-- Existing history should not suddenly become unread after this migration.
UPDATE chat_room_members
SET unread_count = 0,
    last_read_at = COALESCE(last_read_at, NOW());
