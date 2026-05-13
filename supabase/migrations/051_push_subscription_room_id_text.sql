-- Allow push subscriptions to target either a collaboration room UUID or a
-- user-scoped key such as user:<user_id> for Dan completion notifications.
ALTER TABLE push_subscriptions
    DROP CONSTRAINT IF EXISTS push_subscriptions_room_id_fkey;

ALTER TABLE push_subscriptions
    ALTER COLUMN room_id TYPE TEXT USING room_id::text;

COMMENT ON COLUMN push_subscriptions.room_id IS
    'Notification target key: collab room UUID or user:<user_id>.';
