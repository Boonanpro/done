-- meta_ad_accounts のテーブル定義
-- マルチテナント前提の Meta (Instagram/Facebook) 広告アカウント接続情報。
--
-- 設計（SaaS型 / client-owns）:
--   - Meta Developer App は「運営者（ダン提供者）が1つ」持つ。account_label='__app__' の行に
--     app_id / app_secret を暗号化保存する（user_id=運営者）。
--   - 各テナント（クライアント）は自分の広告アカウントを OAuth 接続し、自分のトークンを持つ。
--     (user_id, account_label) でテナント別・複数アカウントを識別。
--   - 秘匿情報（access_token / app_secret）は encrypted_data(JSON) に Fernet 暗号化して格納。
--     ad_account_id / page_id / ig_user_id / currency は表示・選択用に平文カラムで持つ（秘匿ではない）。
--   - 復号は CLI(scripts/meta_ads_cli.py) の出稿・取得処理時のみ。閲覧系は平文トークンを返さない。

DROP TABLE IF EXISTS meta_ad_accounts;

CREATE TABLE meta_ad_accounts (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL,
    -- テナント内でアカウントを識別するラベル。既定 'default'。運営者アプリ設定は '__app__'。
    account_label TEXT NOT NULL DEFAULT 'default',
    -- 表示・選択用の非秘匿メタデータ
    ad_account_id TEXT,        -- 例 "1234567890"（act_ プレフィックスは付けず数値部分のみ保存）
    page_id TEXT,              -- 広告クリエイティブに紐づく Facebook ページID
    ig_user_id TEXT,           -- Instagram ビジネスアカウントの IG User ID
    currency TEXT,             -- 広告アカウント通貨（JPY等）。予算の最小単位換算に使う
    display_name TEXT,         -- 人間向け表示名（任意）
    -- 秘匿情報の暗号化 JSON。{access_token, token_type, expires_at, app_id?, app_secret?}
    encrypted_data TEXT NOT NULL,
    token_expires_at TIMESTAMPTZ,   -- トークン失効予定（never 失効=NULL）
    last_used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, account_label)
);

CREATE INDEX idx_meta_ad_accounts_user_id ON meta_ad_accounts(user_id);

-- updated_at 自動更新トリガー
CREATE OR REPLACE FUNCTION update_meta_ad_accounts_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER meta_ad_accounts_updated_at
    BEFORE UPDATE ON meta_ad_accounts
    FOR EACH ROW EXECUTE FUNCTION update_meta_ad_accounts_updated_at();

-- アクセス制御はサーバー(FastAPI/CLI)側で user_id ベースに行うため RLS は無効化
ALTER TABLE meta_ad_accounts DISABLE ROW LEVEL SECURITY;
