-- inspector_overrides: 手動編集の runtime overrides レイヤー
-- JSX ファイルには触らず、デモページ起動時に InspectorRuntime がこの表を読んで
-- 該当要素にスタイル/属性を適用する。
--
-- element_key = DOM ツリー上のパス ('html>body>div[0]>section[2]>video[0]' 形式)

CREATE TABLE IF NOT EXISTS inspector_overrides (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    project_id UUID,
    artifact_slug TEXT NOT NULL,
    element_key TEXT NOT NULL,
    styles JSONB DEFAULT '{}'::jsonb,
    attrs JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_by UUID,
    UNIQUE (artifact_slug, element_key)
);

CREATE INDEX IF NOT EXISTS idx_inspector_overrides_slug
    ON inspector_overrides(artifact_slug);

ALTER TABLE inspector_overrides ENABLE ROW LEVEL SECURITY;

CREATE POLICY "inspector_overrides_owner" ON inspector_overrides
    FOR ALL USING (created_by = auth.uid());
