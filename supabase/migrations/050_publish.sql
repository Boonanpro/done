-- publish のテーブル定義
-- create_feature で自動生成。中身を実装してください。
--
-- 説明: Phase 3 公開フロー (Cloudflare/Vercel/SEO orchestrator + API)
-- 生成日時: 2026-05-12T11:04:52.077707

-- メインテーブル
CREATE TABLE IF NOT EXISTS publish (
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
ALTER TABLE publish ENABLE ROW LEVEL SECURITY;

-- RLSポリシー
CREATE POLICY "publish_owner" ON publish
    FOR ALL USING (created_by = auth.uid());

-- updated_atの自動更新
CREATE OR REPLACE FUNCTION update_publish_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER publish_updated_at
    BEFORE UPDATE ON publish
    FOR EACH ROW EXECUTE FUNCTION update_publish_updated_at();
