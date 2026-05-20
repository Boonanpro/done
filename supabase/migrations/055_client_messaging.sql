-- client_messaging のテーブル定義
-- create_feature で自動生成。中身を実装してください。
--
-- 説明: Persistent client accounts + magic-link auth + friend-style direct chat for client communication
-- 生成日時: 2026-05-20T16:11:38.542736

-- メインテーブル
CREATE TABLE IF NOT EXISTS client_messaging (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    -- TODO: カラムを定義してください
    -- 例:
    -- title TEXT NOT NULL,
    -- content JSONB DEFAULT '{}',
    -- status TEXT DEFAULT 'active',
    -- user_id UUID REFERENCES auth.users(id),

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_by UUID REFERENCES auth.users(id)
);

-- RLS有効化
ALTER TABLE client_messaging ENABLE ROW LEVEL SECURITY;

-- RLSポリシー
CREATE POLICY "client_messaging_owner" ON client_messaging
    FOR ALL USING (created_by = auth.uid());

-- updated_atの自動更新
CREATE OR REPLACE FUNCTION update_client_messaging_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER client_messaging_updated_at
    BEFORE UPDATE ON client_messaging
    FOR EACH ROW EXECUTE FUNCTION update_client_messaging_updated_at();
