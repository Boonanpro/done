-- amagasaki_sales_dashboard のテーブル定義
-- create_feature で自動生成。中身を実装してください。
--
-- 説明: 尼崎B2B AIセールスパイプラインの運用ダッシュボード。企業リスト→診断→課題仮説→プロトタイプ→送信→KPIを1画面で管理。
-- 生成日時: 2026-04-18T10:27:26.259878

-- メインテーブル
CREATE TABLE IF NOT EXISTS amagasaki_sales_dashboard (
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
ALTER TABLE amagasaki_sales_dashboard ENABLE ROW LEVEL SECURITY;

-- RLSポリシー
CREATE POLICY "amagasaki_sales_dashboard_owner" ON amagasaki_sales_dashboard
    FOR ALL USING (created_by = auth.uid());

-- updated_atの自動更新
CREATE OR REPLACE FUNCTION update_amagasaki_sales_dashboard_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER amagasaki_sales_dashboard_updated_at
    BEFORE UPDATE ON amagasaki_sales_dashboard
    FOR EACH ROW EXECUTE FUNCTION update_amagasaki_sales_dashboard_updated_at();
