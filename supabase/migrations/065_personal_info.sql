-- ==================== Personal Info Table ====================
-- ユーザーの個人情報（電話番号・クレジットカード・住所など）を
-- 暗号化して永続保存する。サービスのログイン認証情報(credentials)とは別管理。
--
-- 設計方針:
-- - encrypted_value: Fernet暗号化したJSON {"value": "..."} （実値は平文で持たない）
-- - masked_hint:     表示用のマスク済み文字列（例 "VISA ****1234" / "090-****-**89"）
--                    システムプロンプトに常時注入してDanに「保有している」事実を認識させる。
--                    実値はget_personal_infoツールで必要時のみ復号取得する。
CREATE TABLE IF NOT EXISTS personal_info (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    field_key VARCHAR(100) NOT NULL,               -- 正規化キー: phone, credit_card, address_home 等
    category VARCHAR(50) NOT NULL DEFAULT 'other',  -- contact / payment / identity / address / other
    label VARCHAR(200),                            -- 人間向けラベル（例: "メインのVISA"）
    encrypted_value TEXT NOT NULL,                 -- Fernet暗号化済みJSON
    masked_hint VARCHAR(120),                      -- 表示用マスク（平文・非機密）
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id, field_key)
);

CREATE INDEX IF NOT EXISTS idx_personal_info_user ON personal_info(user_id);

-- updated_at 自動更新トリガー（001_initial_schema.sql の update_updated_at_column を再利用）
DROP TRIGGER IF EXISTS update_personal_info_updated_at ON personal_info;
CREATE TRIGGER update_personal_info_updated_at
    BEFORE UPDATE ON personal_info
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ==================== Row Level Security ====================
ALTER TABLE personal_info ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own personal_info"
    ON personal_info FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can manage own personal_info"
    ON personal_info FOR ALL
    USING (auth.uid() = user_id);

-- Service role bypass (バックエンド操作用)
CREATE POLICY "Service role full access personal_info"
    ON personal_info FOR ALL
    TO service_role
    USING (true);
