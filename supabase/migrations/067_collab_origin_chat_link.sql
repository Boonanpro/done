-- Link a guest-facing collab room to the originating Done chat room.

ALTER TABLE collab_rooms
    ADD COLUMN IF NOT EXISTS origin_chat_room_id UUID REFERENCES chat_rooms(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS origin_chat_message_id UUID REFERENCES chat_messages(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS origin_kind TEXT DEFAULT 'manual';

CREATE INDEX IF NOT EXISTS idx_collab_rooms_origin_chat_room
    ON collab_rooms(origin_chat_room_id)
    WHERE origin_chat_room_id IS NOT NULL;

