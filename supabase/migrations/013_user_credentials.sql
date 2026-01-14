-- Migration: user_credentials table
-- Phase 3B Enhancement: Supabaseでの認証情報永続化

-- 認証情報テーブル
CREATE TABLE IF NOT EXISTS user_credentials (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    service VARCHAR(100) NOT NULL,  -- ex_reservation, amazon, gmail_imap, etc.
    credential_type VARCHAR(50) NOT NULL DEFAULT 'login',  -- login, api_key, oauth, imap
    encrypted_data TEXT NOT NULL,  -- Fernetで暗号化された認証情報
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- 同一ユーザー・サービスは1レコード
    UNIQUE(user_id, service)
);

-- 更新日時自動更新
CREATE OR REPLACE FUNCTION update_user_credentials_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_user_credentials_timestamp ON user_credentials;
CREATE TRIGGER update_user_credentials_timestamp
    BEFORE UPDATE ON user_credentials
    FOR EACH ROW
    EXECUTE FUNCTION update_user_credentials_updated_at();

-- インデックス
CREATE INDEX IF NOT EXISTS idx_user_credentials_user_id ON user_credentials(user_id);
CREATE INDEX IF NOT EXISTS idx_user_credentials_service ON user_credentials(service);

-- RLSポリシー
ALTER TABLE user_credentials ENABLE ROW LEVEL SECURITY;

-- ユーザーは自分の認証情報のみアクセス可能
CREATE POLICY user_credentials_user_policy ON user_credentials
    FOR ALL
    USING (user_id = auth.uid());

-- サービスアカウント用（バックエンド処理）
CREATE POLICY user_credentials_service_policy ON user_credentials
    FOR ALL
    USING (true);

-- コメント
COMMENT ON TABLE user_credentials IS 'ユーザーごとのサービス認証情報（暗号化保存）';
COMMENT ON COLUMN user_credentials.service IS 'サービス識別子: ex_reservation, amazon, gmail_imap等';
COMMENT ON COLUMN user_credentials.credential_type IS 'login=ID/PW, api_key=APIキー, oauth=OAuth, imap=IMAP認証';
COMMENT ON COLUMN user_credentials.encrypted_data IS 'Fernet暗号化されたJSON: {"username":"...", "password":"..."}';
