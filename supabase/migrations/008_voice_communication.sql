-- Phase 10: Voice Communication Schema
-- 音声通話（架電・受電）のためのテーブル

-- ========================================
-- voice_calls: 通話履歴
-- ========================================
CREATE TABLE IF NOT EXISTS voice_calls (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL,
    call_sid VARCHAR(100) UNIQUE NOT NULL,          -- TwilioのCall SID
    direction VARCHAR(20) NOT NULL,                  -- inbound (受電) / outbound (架電)
    status VARCHAR(30) NOT NULL DEFAULT 'initiated',
    from_number VARCHAR(30) NOT NULL,
    to_number VARCHAR(30) NOT NULL,
    started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    answered_at TIMESTAMP WITH TIME ZONE,
    ended_at TIMESTAMP WITH TIME ZONE,
    duration_seconds INTEGER,
    recording_url TEXT,                              -- 録音URL（オプション）
    transcription TEXT,                              -- 通話内容の文字起こし
    summary TEXT,                                    -- AI要約
    purpose VARCHAR(50),                             -- reservation, inquiry, otp_verification等
    task_id UUID,                                    -- 関連タスクID
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_voice_calls_user_id ON voice_calls(user_id);
CREATE INDEX IF NOT EXISTS idx_voice_calls_status ON voice_calls(status);
CREATE INDEX IF NOT EXISTS idx_voice_calls_direction ON voice_calls(direction);
CREATE INDEX IF NOT EXISTS idx_voice_calls_call_sid ON voice_calls(call_sid);
CREATE INDEX IF NOT EXISTS idx_voice_calls_started_at ON voice_calls(started_at);

-- ========================================
-- voice_call_messages: 通話中のメッセージ履歴
-- ========================================
CREATE TABLE IF NOT EXISTS voice_call_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    call_id UUID NOT NULL REFERENCES voice_calls(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL,                       -- user (相手) / assistant (AI)
    content TEXT NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_voice_call_messages_call_id ON voice_call_messages(call_id);
CREATE INDEX IF NOT EXISTS idx_voice_call_messages_timestamp ON voice_call_messages(timestamp);

-- ========================================
-- phone_number_rules: 電話番号ルール
-- ========================================
CREATE TABLE IF NOT EXISTS phone_number_rules (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL,
    phone_number VARCHAR(30) NOT NULL,
    rule_type VARCHAR(20) NOT NULL,                  -- whitelist / blacklist
    label VARCHAR(100),                              -- 相手の名前・会社名等
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_phone_number_rules_user_id ON phone_number_rules(user_id);
CREATE INDEX IF NOT EXISTS idx_phone_number_rules_user_phone ON phone_number_rules(user_id, phone_number);
CREATE INDEX IF NOT EXISTS idx_phone_number_rules_type ON phone_number_rules(rule_type);

-- ========================================
-- voice_settings: ユーザー別音声設定
-- ========================================
CREATE TABLE IF NOT EXISTS voice_settings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID UNIQUE NOT NULL,
    inbound_enabled BOOLEAN DEFAULT FALSE,           -- 受電を受けるかどうか
    default_greeting TEXT,                           -- デフォルトの挨拶
    auto_answer_whitelist BOOLEAN DEFAULT FALSE,     -- ホワイトリストは自動応答
    record_calls BOOLEAN DEFAULT FALSE,              -- 通話を録音するか
    notify_via_chat BOOLEAN DEFAULT TRUE,            -- チャットに通知するか
    elevenlabs_voice_id VARCHAR(100),                -- ElevenLabsの音声ID
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Index
CREATE INDEX IF NOT EXISTS idx_voice_settings_user_id ON voice_settings(user_id);

-- ========================================
-- Row Level Security
-- ========================================

-- voice_calls RLS
ALTER TABLE voice_calls ENABLE ROW LEVEL SECURITY;

CREATE POLICY voice_calls_user_policy ON voice_calls
    FOR ALL
    USING (auth.uid() = user_id OR auth.role() = 'service_role');

-- voice_call_messages RLS
ALTER TABLE voice_call_messages ENABLE ROW LEVEL SECURITY;

CREATE POLICY voice_call_messages_user_policy ON voice_call_messages
    FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM voice_calls 
            WHERE voice_calls.id = voice_call_messages.call_id 
            AND (voice_calls.user_id = auth.uid() OR auth.role() = 'service_role')
        )
    );

-- phone_number_rules RLS
ALTER TABLE phone_number_rules ENABLE ROW LEVEL SECURITY;

CREATE POLICY phone_number_rules_user_policy ON phone_number_rules
    FOR ALL
    USING (auth.uid() = user_id OR auth.role() = 'service_role');

-- voice_settings RLS
ALTER TABLE voice_settings ENABLE ROW LEVEL SECURITY;

CREATE POLICY voice_settings_user_policy ON voice_settings
    FOR ALL
    USING (auth.uid() = user_id OR auth.role() = 'service_role');

-- ========================================
-- Comments
-- ========================================
COMMENT ON TABLE voice_calls IS 'Phase 10: 通話履歴';
COMMENT ON COLUMN voice_calls.call_sid IS 'TwilioのCall SID';
COMMENT ON COLUMN voice_calls.direction IS '通話方向: inbound (受電) / outbound (架電)';
COMMENT ON COLUMN voice_calls.status IS '通話状態: initiated, ringing, in_progress, completed, failed等';
COMMENT ON COLUMN voice_calls.purpose IS '通話目的: reservation, inquiry, otp_verification等';
COMMENT ON COLUMN voice_calls.transcription IS '通話内容の文字起こし';
COMMENT ON COLUMN voice_calls.summary IS 'AI要約';

COMMENT ON TABLE voice_call_messages IS 'Phase 10: 通話中のメッセージ履歴';
COMMENT ON COLUMN voice_call_messages.role IS '発言者: user (相手) / assistant (AI)';

COMMENT ON TABLE phone_number_rules IS 'Phase 10: 電話番号ルール（ホワイトリスト/ブラックリスト）';
COMMENT ON COLUMN phone_number_rules.rule_type IS 'ルールタイプ: whitelist / blacklist';
COMMENT ON COLUMN phone_number_rules.label IS '相手の名前・会社名等';

COMMENT ON TABLE voice_settings IS 'Phase 10: ユーザー別音声設定';
COMMENT ON COLUMN voice_settings.inbound_enabled IS '受電を受けるかどうか';
COMMENT ON COLUMN voice_settings.auto_answer_whitelist IS 'ホワイトリストの番号は自動応答するか';
COMMENT ON COLUMN voice_settings.elevenlabs_voice_id IS 'ElevenLabsの音声ID（カスタム音声）';



