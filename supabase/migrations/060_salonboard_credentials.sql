-- salonboard_credentials のテーブル定義
-- 美容師ごとに、サロンボードのログイン情報を暗号化して保存する。
-- アプリにログイン機能がないため device_id (ブラウザlocalStorageで生成するUUID) でユーザー識別。
-- 暗号化は Fernet (対称鍵)。鍵はサーバー環境変数 SALONBOARD_ENCRYPTION_KEY。
-- サーバーは自動投稿処理時のみ復号する。閲覧APIは平文を返さない設計。

DROP TABLE IF EXISTS salonboard_credentials;

CREATE TABLE salonboard_credentials (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    device_id TEXT NOT NULL UNIQUE,
    stylist_name TEXT NOT NULL,
    encrypted_login_id TEXT NOT NULL,
    encrypted_password TEXT NOT NULL,
    encryption_version INT NOT NULL DEFAULT 1,
    consent_at TIMESTAMPTZ NOT NULL,
    last_used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_salonboard_credentials_device_id ON salonboard_credentials(device_id);

-- updated_at の自動更新トリガー
CREATE OR REPLACE FUNCTION update_salonboard_credentials_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER salonboard_credentials_updated_at
    BEFORE UPDATE ON salonboard_credentials
    FOR EACH ROW EXECUTE FUNCTION update_salonboard_credentials_updated_at();

-- アプリにログイン機能がないため RLS は無効化し、サーバー側 (FastAPI) で device_id ベースのアクセス制御を行う
ALTER TABLE salonboard_credentials DISABLE ROW LEVEL SECURITY;
