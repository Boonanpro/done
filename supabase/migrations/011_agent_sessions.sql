-- Agent Sessions Table
-- StateMachineの状態を永続化して会話の文脈を維持

-- セッションテーブル
CREATE TABLE IF NOT EXISTS agent_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id TEXT NOT NULL UNIQUE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    room_id UUID REFERENCES chat_rooms(id) ON DELETE SET NULL,

    -- 現在の状態
    current_state TEXT NOT NULL DEFAULT 'intake',

    -- 各ステップの結果（JSONB）
    intake_result JSONB DEFAULT '{}',
    plan_result JSONB DEFAULT '{}',
    research_result JSONB DEFAULT '{}',
    proposal JSONB DEFAULT '{}',
    execution_result JSONB DEFAULT '{}',
    verification JSONB DEFAULT '{}',
    report JSONB DEFAULT '{}',

    -- 推論過程（プロセス表示用）
    reasoning_steps JSONB DEFAULT '[]',

    -- 実行履歴（成功/失敗両方）
    execution_history JSONB DEFAULT '[]',

    -- ユーザーの傾向
    user_preferences JSONB DEFAULT '{}',

    -- エラー情報
    error TEXT,

    -- タイムスタンプ
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_agent_sessions_session_id ON agent_sessions(session_id);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_user_id ON agent_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_room_id ON agent_sessions(room_id);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_updated_at ON agent_sessions(updated_at);

-- RLSポリシー
ALTER TABLE agent_sessions ENABLE ROW LEVEL SECURITY;

-- ユーザーは自分のセッションのみアクセス可能
CREATE POLICY "Users can view their own sessions"
    ON agent_sessions FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can create their own sessions"
    ON agent_sessions FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update their own sessions"
    ON agent_sessions FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "Users can delete their own sessions"
    ON agent_sessions FOR DELETE
    USING (auth.uid() = user_id);

-- 更新日時の自動更新
CREATE OR REPLACE FUNCTION update_agent_session_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_agent_session_updated_at
    BEFORE UPDATE ON agent_sessions
    FOR EACH ROW
    EXECUTE FUNCTION update_agent_session_updated_at();

-- 古いセッションの自動削除（7日以上更新がないもの）
-- 定期的にメンテナンスで実行
COMMENT ON TABLE agent_sessions IS 'StateMachine状態の永続化。7日以上更新がないセッションは定期削除対象。';
