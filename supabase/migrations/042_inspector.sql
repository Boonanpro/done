-- inspector: 手動編集の履歴（audit log）。MVP では必須ではないが
-- 将来 undo/差分表示に使えるよう用意しておく。実際の変更は JSX ファイルに
-- 直接 patch される。

CREATE TABLE IF NOT EXISTS inspector_edits (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    project_id UUID,
    artifact_slug TEXT,
    file_path TEXT NOT NULL,
    line_number INT NOT NULL,
    column_number INT,
    element_tag TEXT,
    styles JSONB,
    attrs JSONB,
    applied BOOLEAN DEFAULT TRUE,
    error TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by UUID
);

CREATE INDEX IF NOT EXISTS idx_inspector_edits_project
    ON inspector_edits(project_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_inspector_edits_file
    ON inspector_edits(file_path, line_number);

ALTER TABLE inspector_edits ENABLE ROW LEVEL SECURITY;

CREATE POLICY "inspector_edits_owner" ON inspector_edits
    FOR ALL USING (created_by = auth.uid());
