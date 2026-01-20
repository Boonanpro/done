-- Error Logs Table
-- ダンが自身の実行エラーを追跡するためのテーブル

CREATE TABLE IF NOT EXISTS error_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id TEXT,                      -- エージェントセッションID
    user_id UUID REFERENCES users(id),    -- ユーザーID（任意）
    source TEXT NOT NULL,                 -- エラー発生元 (例: "ex_reservation.search")
    level TEXT DEFAULT 'ERROR',           -- ログレベル (ERROR, WARNING, INFO)
    message TEXT NOT NULL,                -- エラーメッセージ
    traceback TEXT,                       -- スタックトレース
    context JSONB,                        -- 追加コンテキスト (パラメータ、リクエスト情報等)
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_error_logs_created ON error_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_error_logs_source ON error_logs(source);
CREATE INDEX IF NOT EXISTS idx_error_logs_session ON error_logs(session_id);
CREATE INDEX IF NOT EXISTS idx_error_logs_user ON error_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_error_logs_level ON error_logs(level);

-- 複合インデックス（よく使うクエリパターン用）
CREATE INDEX IF NOT EXISTS idx_error_logs_session_created ON error_logs(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_error_logs_source_created ON error_logs(source, created_at DESC);

-- RLS (Row Level Security) ポリシー
ALTER TABLE error_logs ENABLE ROW LEVEL SECURITY;

-- サービスロールは全アクセス可能
CREATE POLICY "Service role can access all error_logs"
    ON error_logs
    FOR ALL
    USING (auth.role() = 'service_role');

-- ユーザーは自分のエラーログのみ閲覧可能
CREATE POLICY "Users can view own error_logs"
    ON error_logs
    FOR SELECT
    USING (auth.uid() = user_id);

-- コメント
COMMENT ON TABLE error_logs IS 'ダンの実行エラーログ（Self-Healing用）';
COMMENT ON COLUMN error_logs.session_id IS 'エージェントセッションID（agent_sessions_v2と紐付け）';
COMMENT ON COLUMN error_logs.source IS 'エラー発生元（service_name.method形式）';
COMMENT ON COLUMN error_logs.context IS '追加コンテキスト（パラメータ、リクエスト情報等）';
