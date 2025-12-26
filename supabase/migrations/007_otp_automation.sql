-- Phase 9: OTP Automation Schema
-- OTP抽出・管理のためのテーブル

-- ========================================
-- otp_extractions: OTP抽出履歴
-- ========================================
CREATE TABLE IF NOT EXISTS otp_extractions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL,
    source VARCHAR(20) NOT NULL,                    -- email, sms
    source_id VARCHAR(255),                         -- メールID or SMS ID
    service VARCHAR(50),                            -- amazon, ex_reservation等
    sender VARCHAR(255),                            -- 送信元
    subject VARCHAR(500),                           -- メール件名（メールの場合）
    otp_code VARCHAR(20) NOT NULL,                  -- 抽出されたOTP
    extracted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    used_at TIMESTAMP WITH TIME ZONE,               -- 使用日時
    expires_at TIMESTAMP WITH TIME ZONE,            -- 有効期限
    is_used BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_otp_extractions_user_id ON otp_extractions(user_id);
CREATE INDEX IF NOT EXISTS idx_otp_extractions_user_service ON otp_extractions(user_id, service);
CREATE INDEX IF NOT EXISTS idx_otp_extractions_expires ON otp_extractions(expires_at);
CREATE INDEX IF NOT EXISTS idx_otp_extractions_source ON otp_extractions(source, source_id);

-- ========================================
-- sms_connections: SMS受信設定
-- ========================================
CREATE TABLE IF NOT EXISTS sms_connections (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL UNIQUE,
    phone_number VARCHAR(20),                       -- Twilioの電話番号
    is_active BOOLEAN DEFAULT TRUE,
    last_received_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Index
CREATE INDEX IF NOT EXISTS idx_sms_connections_user_id ON sms_connections(user_id);
CREATE INDEX IF NOT EXISTS idx_sms_connections_phone ON sms_connections(phone_number);

-- ========================================
-- Row Level Security
-- ========================================

-- otp_extractions RLS
ALTER TABLE otp_extractions ENABLE ROW LEVEL SECURITY;

CREATE POLICY otp_extractions_user_policy ON otp_extractions
    FOR ALL
    USING (auth.uid() = user_id OR auth.role() = 'service_role');

-- sms_connections RLS
ALTER TABLE sms_connections ENABLE ROW LEVEL SECURITY;

CREATE POLICY sms_connections_user_policy ON sms_connections
    FOR ALL
    USING (auth.uid() = user_id OR auth.role() = 'service_role');

-- ========================================
-- Comments
-- ========================================
COMMENT ON TABLE otp_extractions IS 'Phase 9: OTP抽出履歴';
COMMENT ON COLUMN otp_extractions.source IS 'OTPソース: email, sms';
COMMENT ON COLUMN otp_extractions.service IS '対象サービス: amazon, ex_reservation等';
COMMENT ON COLUMN otp_extractions.otp_code IS '抽出されたOTPコード';
COMMENT ON COLUMN otp_extractions.is_used IS 'OTPが使用済みかどうか';

COMMENT ON TABLE sms_connections IS 'Phase 9: SMS受信設定';
COMMENT ON COLUMN sms_connections.phone_number IS 'Twilioの電話番号';



