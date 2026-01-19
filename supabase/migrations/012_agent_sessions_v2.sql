-- Agent Sessions v2
-- Messages配列で会話の文脈を維持する新アーキテクチャ

-- セッションテーブル（v2）
CREATE TABLE IF NOT EXISTS agent_sessions_v2 (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id TEXT NOT NULL,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- 会話履歴（Messages配列）- これが全て
    messages JSONB NOT NULL DEFAULT '[]',

    -- 現在の状態
    current_state TEXT NOT NULL DEFAULT 'intake',

    -- 推論ステップ（ナレーション用）
    reasoning_steps JSONB DEFAULT '[]',

    -- コンテキスト（状態間で引き継ぐデータ）
    context JSONB DEFAULT '{}',

    -- タイムスタンプ
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- 複合ユニーク制約
    CONSTRAINT agent_sessions_v2_unique UNIQUE (session_id, user_id)
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_agent_sessions_v2_session_id ON agent_sessions_v2(session_id);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_v2_user_id ON agent_sessions_v2(user_id);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_v2_updated_at ON agent_sessions_v2(updated_at);

-- RLSポリシー
ALTER TABLE agent_sessions_v2 ENABLE ROW LEVEL SECURITY;

-- サービスロールは全てアクセス可能（バックエンドAPI用）
CREATE POLICY "Service role has full access to sessions_v2"
    ON agent_sessions_v2
    FOR ALL
    USING (true)
    WITH CHECK (true);

-- ユーザーは自分のセッションのみアクセス可能
CREATE POLICY "Users can view their own sessions_v2"
    ON agent_sessions_v2 FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can create their own sessions_v2"
    ON agent_sessions_v2 FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update their own sessions_v2"
    ON agent_sessions_v2 FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "Users can delete their own sessions_v2"
    ON agent_sessions_v2 FOR DELETE
    USING (auth.uid() = user_id);

-- 更新日時の自動更新
CREATE OR REPLACE FUNCTION update_agent_session_v2_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_agent_session_v2_updated_at
    BEFORE UPDATE ON agent_sessions_v2
    FOR EACH ROW
    EXECUTE FUNCTION update_agent_session_v2_updated_at();

-- コメント
COMMENT ON TABLE agent_sessions_v2 IS 'Agent v2: Messages配列で会話の文脈を維持。7日以上更新がないセッションは定期削除対象。';
COMMENT ON COLUMN agent_sessions_v2.messages IS 'ChatGPT形式のMessages配列。[{"role": "user", "content": "..."}, ...]';
COMMENT ON COLUMN agent_sessions_v2.context IS '状態間で引き継ぐデータ（認証情報の有無、選択した列車など）';
