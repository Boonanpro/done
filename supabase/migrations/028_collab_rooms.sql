-- Collaboration Rooms - コミュニケーション機能
-- オーナーとゲスト（友人・クライアント等）が共同作業するためのチャットルーム

-- ==================== Collab Rooms ====================
CREATE TABLE IF NOT EXISTS collab_rooms (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT,
    project_ref TEXT,                    -- 紐付けプロジェクト識別子 (任意)
    status TEXT NOT NULL DEFAULT 'active', -- active / archived
    ai_auto_assist BOOLEAN DEFAULT true, -- DAN自動アシストON/OFF
    ai_assist_config JSONB DEFAULT '{"summarize_feedback": true, "auto_organize_files": true, "auto_suggest_fixes": false}',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_collab_rooms_owner ON collab_rooms(owner_id);
CREATE INDEX IF NOT EXISTS idx_collab_rooms_status ON collab_rooms(status);

-- ==================== Collab Invites ====================
CREATE TABLE IF NOT EXISTS collab_invites (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    room_id UUID NOT NULL REFERENCES collab_rooms(id) ON DELETE CASCADE,
    token TEXT UNIQUE NOT NULL,          -- URL用ランダムトークン
    guest_name TEXT,                     -- ゲストが入力した表示名
    guest_token TEXT,                    -- 認証用JWT (参加後に発行)
    role TEXT NOT NULL DEFAULT 'reviewer', -- reviewer / editor
    status TEXT NOT NULL DEFAULT 'pending', -- pending / joined / expired
    expires_at TIMESTAMPTZ NOT NULL,
    joined_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_collab_invites_token ON collab_invites(token);
CREATE INDEX IF NOT EXISTS idx_collab_invites_room ON collab_invites(room_id);

-- ==================== Collab Messages ====================
CREATE TABLE IF NOT EXISTS collab_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    room_id UUID NOT NULL REFERENCES collab_rooms(id) ON DELETE CASCADE,
    sender_type TEXT NOT NULL,           -- owner / guest / dan_owner / dan_guest
    sender_name TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',         -- file_ids, mentions, etc.
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_collab_messages_room ON collab_messages(room_id);
CREATE INDEX IF NOT EXISTS idx_collab_messages_room_created ON collab_messages(room_id, created_at DESC);

-- ==================== Collab Files ====================
CREATE TABLE IF NOT EXISTS collab_files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    room_id UUID NOT NULL REFERENCES collab_rooms(id) ON DELETE CASCADE,
    message_id UUID REFERENCES collab_messages(id) ON DELETE SET NULL,
    uploaded_by TEXT NOT NULL,           -- owner / guest
    file_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_type TEXT,
    file_size INTEGER,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_collab_files_room ON collab_files(room_id);

-- ==================== Triggers ====================
CREATE TRIGGER update_collab_rooms_updated_at
    BEFORE UPDATE ON collab_rooms
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ==================== Row Level Security ====================
ALTER TABLE collab_rooms ENABLE ROW LEVEL SECURITY;
ALTER TABLE collab_invites ENABLE ROW LEVEL SECURITY;
ALTER TABLE collab_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE collab_files ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role full access collab_rooms"
    ON collab_rooms FOR ALL TO service_role USING (true);
CREATE POLICY "Service role full access collab_invites"
    ON collab_invites FOR ALL TO service_role USING (true);
CREATE POLICY "Service role full access collab_messages"
    ON collab_messages FOR ALL TO service_role USING (true);
CREATE POLICY "Service role full access collab_files"
    ON collab_files FOR ALL TO service_role USING (true);
