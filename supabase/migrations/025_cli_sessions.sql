-- CLIセッションID永続化テーブル
-- 旧: projects.metadata.cli_session_id（dan-type roomでは保存不可だった）
-- 新: 全room_idに対応する専用テーブル

CREATE TABLE IF NOT EXISTS cli_sessions (
    room_id UUID PRIMARY KEY REFERENCES chat_rooms(id) ON DELETE CASCADE,
    cli_session_id TEXT NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE cli_sessions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role full access cli_sessions"
    ON cli_sessions FOR ALL TO service_role USING (true);

-- 既存データをprojects.metadataから移行
INSERT INTO cli_sessions (room_id, cli_session_id, updated_at)
SELECT p.room_id, p.metadata->>'cli_session_id', p.updated_at
FROM projects p
WHERE p.room_id IS NOT NULL
  AND p.metadata->>'cli_session_id' IS NOT NULL
ON CONFLICT (room_id) DO NOTHING;
