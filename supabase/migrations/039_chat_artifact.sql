-- chat_artifact: チャットメッセージに紐づく成果物（ダッシュボード/HP/ツール）のポインタ
-- プレビューペインで表示する対象を保持する。実体はfrontend/src/app/demo/{slug} 等の生成済みページ。

CREATE TABLE IF NOT EXISTS chat_artifact (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    project_id UUID,
    message_id UUID,
    slug TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'demo',
    label TEXT,
    preview_url TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_by UUID
);

CREATE INDEX IF NOT EXISTS idx_chat_artifact_project
    ON chat_artifact(project_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_chat_artifact_message
    ON chat_artifact(message_id);

ALTER TABLE chat_artifact ENABLE ROW LEVEL SECURITY;

CREATE POLICY "chat_artifact_owner" ON chat_artifact
    FOR ALL USING (created_by = auth.uid());

CREATE OR REPLACE FUNCTION update_chat_artifact_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER chat_artifact_updated_at
    BEFORE UPDATE ON chat_artifact
    FOR EACH ROW EXECUTE FUNCTION update_chat_artifact_updated_at();
