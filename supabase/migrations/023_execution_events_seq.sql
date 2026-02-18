-- execution_events に連番 seq を追加
-- フロントエンドが「最後に受信した番号以降」で差分取得するために使う

-- seq カラム追加（SERIAL で自動インクリメント）
ALTER TABLE execution_events ADD COLUMN IF NOT EXISTS seq BIGSERIAL;

-- seq でのインデックス（project_id + seq での範囲検索用）
CREATE INDEX IF NOT EXISTS idx_exec_events_project_seq ON execution_events(project_id, seq);

-- room_id + seq でのインデックス（通常チャットの差分取得用）
CREATE INDEX IF NOT EXISTS idx_exec_events_room_seq ON execution_events(room_id, seq);
