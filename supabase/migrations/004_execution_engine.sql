-- Execution Engine - Database Schema
-- Phase 3B: 承認後の実行エンジン

-- ==================== User Credentials Table ====================
-- ユーザー認証情報（暗号化して保存）
CREATE TABLE IF NOT EXISTS user_credentials (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL,  -- 将来的にusersテーブルとリンク可能
    service VARCHAR(50) NOT NULL,  -- "ex_reservation", "amazon", "rakuten", etc.
    encrypted_data TEXT NOT NULL,  -- AES-256暗号化されたJSON
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id, service)
);

-- Index for credential lookup
CREATE INDEX IF NOT EXISTS idx_user_credentials_user_id ON user_credentials(user_id);
CREATE INDEX IF NOT EXISTS idx_user_credentials_service ON user_credentials(service);

-- ==================== Execution Logs Table ====================
-- 実行ログ（タスク実行の各ステップを記録）
CREATE TABLE IF NOT EXISTS execution_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id UUID NOT NULL,  -- タスクID（tasksテーブルとリンク可能）
    step VARCHAR(50) NOT NULL,  -- "opened_url", "logged_in", "entered_details", etc.
    status VARCHAR(20) NOT NULL,  -- "success", "failed", "in_progress"
    details JSONB,  -- ステップ固有の詳細情報
    screenshot_path TEXT,  -- スクリーンショットのファイルパス
    error_message TEXT,  -- エラー発生時のメッセージ
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Index for execution log queries
CREATE INDEX IF NOT EXISTS idx_execution_logs_task_id ON execution_logs(task_id);
CREATE INDEX IF NOT EXISTS idx_execution_logs_task_created ON execution_logs(task_id, created_at DESC);

-- ==================== Task Execution State Table ====================
-- タスク実行状態（リアルタイム進捗管理）
CREATE TABLE IF NOT EXISTS task_execution_state (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id UUID UNIQUE NOT NULL,  -- 1タスクにつき1つの実行状態
    status VARCHAR(30) NOT NULL DEFAULT 'pending',  -- "pending", "executing", "awaiting_credentials", "completed", "failed"
    current_step VARCHAR(50),  -- 現在のステップ
    steps_completed JSONB DEFAULT '[]'::jsonb,  -- 完了したステップのリスト
    steps_remaining JSONB DEFAULT '[]'::jsonb,  -- 残りのステップのリスト
    required_service VARCHAR(50),  -- 認証が必要なサービス名
    execution_result JSONB,  -- 実行結果
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Index for task execution state
CREATE INDEX IF NOT EXISTS idx_task_execution_state_task_id ON task_execution_state(task_id);
CREATE INDEX IF NOT EXISTS idx_task_execution_state_status ON task_execution_state(status);

-- ==================== Updated At Trigger ====================
-- Trigger function for updated_at (if not exists from previous migrations)
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply updated_at triggers
CREATE TRIGGER update_user_credentials_updated_at
    BEFORE UPDATE ON user_credentials
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_task_execution_state_updated_at
    BEFORE UPDATE ON task_execution_state
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ==================== Row Level Security ====================
-- Enable RLS on all tables
ALTER TABLE user_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE execution_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE task_execution_state ENABLE ROW LEVEL SECURITY;

-- Service role bypass (for backend operations)
CREATE POLICY "Service role full access user_credentials"
    ON user_credentials FOR ALL
    TO service_role
    USING (true);

CREATE POLICY "Service role full access execution_logs"
    ON execution_logs FOR ALL
    TO service_role
    USING (true);

CREATE POLICY "Service role full access task_execution_state"
    ON task_execution_state FOR ALL
    TO service_role
    USING (true);

-- User can manage own credentials (for future authenticated access)
CREATE POLICY "Users can manage own credentials"
    ON user_credentials
    FOR ALL
    USING (auth.uid()::text = user_id::text);

-- ==================== Comments ====================
COMMENT ON TABLE user_credentials IS 'ユーザー認証情報（AES-256暗号化）';
COMMENT ON TABLE execution_logs IS 'タスク実行ログ（各ステップの記録）';
COMMENT ON TABLE task_execution_state IS 'タスク実行状態（リアルタイム進捗）';

COMMENT ON COLUMN user_credentials.service IS 'サービス名: ex_reservation, amazon, rakuten, jal, ana, etc.';
COMMENT ON COLUMN user_credentials.encrypted_data IS 'AES-256-GCM暗号化されたJSON形式の認証情報';
COMMENT ON COLUMN execution_logs.step IS 'ステップ名: opened_url, logged_in, entered_details, selected_item, confirmed, completed';
COMMENT ON COLUMN task_execution_state.status IS '実行状態: pending, executing, awaiting_credentials, completed, failed';
