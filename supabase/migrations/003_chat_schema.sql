-- Done Chat System - Database Schema
-- Phase 2: AIネイティブチャット機能

-- ==================== Chat Users Table ====================
-- Done Chatアカウント（既存usersテーブルとリンク可能）
CREATE TABLE IF NOT EXISTS chat_users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    avatar_url TEXT,
    done_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Index for email lookup
CREATE INDEX IF NOT EXISTS idx_chat_users_email ON chat_users(email);
CREATE INDEX IF NOT EXISTS idx_chat_users_done_user_id ON chat_users(done_user_id);

-- ==================== Chat Invites Table ====================
-- 招待リンク
CREATE TABLE IF NOT EXISTS chat_invites (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    code VARCHAR(20) UNIQUE NOT NULL,
    creator_id UUID REFERENCES chat_users(id) ON DELETE CASCADE NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE,
    max_uses INTEGER DEFAULT 1,
    use_count INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Index for code lookup
CREATE INDEX IF NOT EXISTS idx_chat_invites_code ON chat_invites(code);
CREATE INDEX IF NOT EXISTS idx_chat_invites_creator ON chat_invites(creator_id);

-- ==================== Chat Friendships Table ====================
-- 友達関係（双方向）
CREATE TABLE IF NOT EXISTS chat_friendships (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES chat_users(id) ON DELETE CASCADE NOT NULL,
    friend_id UUID REFERENCES chat_users(id) ON DELETE CASCADE NOT NULL,
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id, friend_id)
);

-- Index for friendship lookup
CREATE INDEX IF NOT EXISTS idx_chat_friendships_user ON chat_friendships(user_id);
CREATE INDEX IF NOT EXISTS idx_chat_friendships_friend ON chat_friendships(friend_id);

-- ==================== Chat Rooms Table ====================
-- チャットルーム（1対1 or グループ）
CREATE TABLE IF NOT EXISTS chat_rooms (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100),
    type VARCHAR(20) DEFAULT 'direct', -- 'direct' or 'group'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ==================== Chat Room Members Table ====================
-- ルームメンバー
CREATE TABLE IF NOT EXISTS chat_room_members (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    room_id UUID REFERENCES chat_rooms(id) ON DELETE CASCADE NOT NULL,
    user_id UUID REFERENCES chat_users(id) ON DELETE CASCADE NOT NULL,
    role VARCHAR(20) DEFAULT 'member', -- 'owner', 'admin', 'member'
    ai_mode VARCHAR(20) DEFAULT 'off', -- 'off', 'assist', 'auto'
    last_read_at TIMESTAMP WITH TIME ZONE,
    joined_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(room_id, user_id)
);

-- Index for room member lookup
CREATE INDEX IF NOT EXISTS idx_chat_room_members_room ON chat_room_members(room_id);
CREATE INDEX IF NOT EXISTS idx_chat_room_members_user ON chat_room_members(user_id);

-- ==================== Chat Messages Table ====================
-- メッセージ
CREATE TABLE IF NOT EXISTS chat_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    room_id UUID REFERENCES chat_rooms(id) ON DELETE CASCADE NOT NULL,
    sender_id UUID REFERENCES chat_users(id) ON DELETE SET NULL,
    sender_type VARCHAR(20) DEFAULT 'human', -- 'human' or 'ai'
    content TEXT NOT NULL,
    reply_to UUID REFERENCES chat_messages(id) ON DELETE SET NULL,
    ai_context JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Index for message queries
CREATE INDEX IF NOT EXISTS idx_chat_messages_room ON chat_messages(room_id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_room_created ON chat_messages(room_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_messages_sender ON chat_messages(sender_id);

-- ==================== Chat AI Settings Table ====================
-- AI設定（ルームごと）
CREATE TABLE IF NOT EXISTS chat_ai_settings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    room_id UUID REFERENCES chat_rooms(id) ON DELETE CASCADE UNIQUE NOT NULL,
    enabled BOOLEAN DEFAULT false,
    mode VARCHAR(20) DEFAULT 'assist', -- 'off', 'assist', 'auto'
    personality TEXT,
    auto_reply_delay_ms INTEGER DEFAULT 3000,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Index for AI settings lookup
CREATE INDEX IF NOT EXISTS idx_chat_ai_settings_room ON chat_ai_settings(room_id);

-- ==================== Updated At Triggers ====================
-- Apply updated_at triggers to new tables
CREATE TRIGGER update_chat_users_updated_at
    BEFORE UPDATE ON chat_users
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_chat_rooms_updated_at
    BEFORE UPDATE ON chat_rooms
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_chat_ai_settings_updated_at
    BEFORE UPDATE ON chat_ai_settings
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ==================== Row Level Security ====================
-- Enable RLS on all chat tables
ALTER TABLE chat_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_invites ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_friendships ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_rooms ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_room_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_ai_settings ENABLE ROW LEVEL SECURITY;

-- Service role bypass (for backend operations)
CREATE POLICY "Service role full access chat_users"
    ON chat_users FOR ALL
    TO service_role
    USING (true);

CREATE POLICY "Service role full access chat_invites"
    ON chat_invites FOR ALL
    TO service_role
    USING (true);

CREATE POLICY "Service role full access chat_friendships"
    ON chat_friendships FOR ALL
    TO service_role
    USING (true);

CREATE POLICY "Service role full access chat_rooms"
    ON chat_rooms FOR ALL
    TO service_role
    USING (true);

CREATE POLICY "Service role full access chat_room_members"
    ON chat_room_members FOR ALL
    TO service_role
    USING (true);

CREATE POLICY "Service role full access chat_messages"
    ON chat_messages FOR ALL
    TO service_role
    USING (true);

CREATE POLICY "Service role full access chat_ai_settings"
    ON chat_ai_settings FOR ALL
    TO service_role
    USING (true);
