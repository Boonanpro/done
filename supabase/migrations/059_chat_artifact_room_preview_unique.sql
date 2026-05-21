-- chat_artifact cards are scoped to a chat room and open a concrete preview URL.
-- Keep project_id as metadata, but prevent duplicate cards for the same route
-- inside one room. This supports sub-route artifacts such as /artifacts/kittoku/v2.

CREATE UNIQUE INDEX IF NOT EXISTS uniq_chat_artifact_room_preview_url
    ON chat_artifact(room_id, preview_url);
