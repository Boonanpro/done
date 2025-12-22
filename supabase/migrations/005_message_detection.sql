-- Phase 5: Message Detection - Database Schema
-- メッセージ検知機能のためのテーブル定義

-- ==================== Detected Messages Table ====================
-- 検知されたメッセージ（Doneチャット、Gmail、LINE等から）
CREATE TABLE IF NOT EXISTS detected_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    source VARCHAR(20) NOT NULL,          -- 'done_chat', 'gmail', 'line'
    source_id VARCHAR(255),               -- 元のメッセージID
    content TEXT,                         -- メッセージ本文
    subject VARCHAR(500),                 -- 件名（メールの場合）
    sender_info JSONB,                    -- 送信者情報
    metadata JSONB,                       -- ソース固有の追加情報
    status VARCHAR(20) DEFAULT 'pending', -- 'pending', 'processing', 'processed', 'failed'
    content_type VARCHAR(50),             -- 分類結果: 'invoice', 'otp', 'notification', 'general'
    processing_result JSONB,              -- 処理結果
    processed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for detected_messages
CREATE INDEX IF NOT EXISTS idx_detected_messages_user_id ON detected_messages(user_id);
CREATE INDEX IF NOT EXISTS idx_detected_messages_source ON detected_messages(source);
CREATE INDEX IF NOT EXISTS idx_detected_messages_status ON detected_messages(status);
CREATE INDEX IF NOT EXISTS idx_detected_messages_content_type ON detected_messages(content_type);
CREATE INDEX IF NOT EXISTS idx_detected_messages_created_at ON detected_messages(created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_detected_messages_source_id ON detected_messages(source, source_id) WHERE source_id IS NOT NULL;

-- ==================== Gmail Connections Table ====================
-- Gmail連携設定
CREATE TABLE IF NOT EXISTS gmail_connections (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE UNIQUE,
    email VARCHAR(255) NOT NULL,
    encrypted_token TEXT NOT NULL,        -- OAuth2トークン（暗号化）
    last_history_id VARCHAR(50),          -- Gmail履歴ID（差分取得用）
    last_sync_at TIMESTAMP WITH TIME ZONE,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Index for gmail_connections
CREATE INDEX IF NOT EXISTS idx_gmail_connections_user_id ON gmail_connections(user_id);
CREATE INDEX IF NOT EXISTS idx_gmail_connections_email ON gmail_connections(email);

-- ==================== Message Attachments Table ====================
-- 添付ファイル
CREATE TABLE IF NOT EXISTS message_attachments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    detected_message_id UUID REFERENCES detected_messages(id) ON DELETE CASCADE,
    filename VARCHAR(255) NOT NULL,
    mime_type VARCHAR(100) NOT NULL,
    file_size INTEGER,
    storage_path TEXT NOT NULL,           -- ローカルパス or Supabase Storage URL
    storage_type VARCHAR(20) DEFAULT 'local',  -- 'local', 'supabase'
    checksum VARCHAR(64),                 -- SHA256ハッシュ（重複検出用）
    extracted_text TEXT,                  -- OCR/PDFから抽出したテキスト（Phase 6で使用）
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for message_attachments
CREATE INDEX IF NOT EXISTS idx_message_attachments_message_id ON message_attachments(detected_message_id);
CREATE INDEX IF NOT EXISTS idx_message_attachments_mime_type ON message_attachments(mime_type);
CREATE INDEX IF NOT EXISTS idx_message_attachments_checksum ON message_attachments(checksum);

-- ==================== Updated At Trigger ====================
-- Apply updated_at trigger to gmail_connections
CREATE TRIGGER update_gmail_connections_updated_at
    BEFORE UPDATE ON gmail_connections
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ==================== Row Level Security ====================
-- Enable RLS on all Phase 5 tables
ALTER TABLE detected_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE gmail_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE message_attachments ENABLE ROW LEVEL SECURITY;

-- Service role bypass (for backend operations)
CREATE POLICY "Service role full access detected_messages"
    ON detected_messages FOR ALL
    TO service_role
    USING (true);

CREATE POLICY "Service role full access gmail_connections"
    ON gmail_connections FOR ALL
    TO service_role
    USING (true);

CREATE POLICY "Service role full access message_attachments"
    ON message_attachments FOR ALL
    TO service_role
    USING (true);

-- User policies (for authenticated users)
CREATE POLICY "Users can view own detected_messages"
    ON detected_messages FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can view own gmail_connections"
    ON gmail_connections FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can manage own gmail_connections"
    ON gmail_connections FOR ALL
    USING (auth.uid() = user_id);

CREATE POLICY "Users can view own message_attachments"
    ON message_attachments FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM detected_messages
            WHERE detected_messages.id = message_attachments.detected_message_id
            AND detected_messages.user_id = auth.uid()
        )
    );


