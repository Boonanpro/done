-- LINE-style last-message preview on the chat list.
-- Denormalized onto chat_rooms (like last_message_at) so the projects list
-- can show "what was said last" without a per-room message lookup.

ALTER TABLE chat_rooms
    ADD COLUMN IF NOT EXISTS last_message_preview TEXT;

-- Backfill from the most recent message in each room so existing chats show
-- a preview immediately instead of waiting for the next message.
UPDATE chat_rooms r
SET last_message_preview = sub.content
FROM (
    SELECT DISTINCT ON (room_id) room_id, content
    FROM chat_messages
    ORDER BY room_id, created_at DESC
) sub
WHERE r.id = sub.room_id
  AND r.last_message_preview IS NULL;
