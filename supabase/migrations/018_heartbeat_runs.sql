-- Heartbeat実行ログテーブル
CREATE TABLE IF NOT EXISTS heartbeat_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    response TEXT,
    tools_used JSONB DEFAULT '[]',
    status TEXT DEFAULT 'success',
    error TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_heartbeat_runs_date ON heartbeat_runs(user_id, created_at DESC);
