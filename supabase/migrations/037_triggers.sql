-- Migration 037: Triggers & Agent Runs — Dan Workspace Phase 3/4
--
-- トリガー定義と実行履歴、自律エージェントのトレース記録を扱う。
-- 既存の execution_events とは独立: こちらは「ユーザー定義の自動化」の単位。

-- ============================================================
-- triggers: ユーザー定義のトリガー
-- ============================================================
CREATE TABLE IF NOT EXISTS triggers (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    description     TEXT,
    kind            TEXT NOT NULL,
    config          JSONB NOT NULL DEFAULT '{}'::jsonb,
    actions         JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_enabled      BOOLEAN NOT NULL DEFAULT true,
    last_fired_at   TIMESTAMPTZ,
    fire_count      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT triggers_kind_check CHECK (kind IN (
        'gmail', 'calendar', 'file', 'cron', 'collab', 'chat_command'
    ))
);

CREATE INDEX IF NOT EXISTS idx_triggers_user ON triggers(user_id);
CREATE INDEX IF NOT EXISTS idx_triggers_kind ON triggers(kind, is_enabled);

DROP TRIGGER IF EXISTS trg_triggers_updated_at ON triggers;
CREATE TRIGGER trg_triggers_updated_at
    BEFORE UPDATE ON triggers
    FOR EACH ROW
    EXECUTE FUNCTION update_blocks_updated_at();

-- ============================================================
-- trigger_runs: トリガー実行履歴
-- ============================================================
CREATE TABLE IF NOT EXISTS trigger_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trigger_id      UUID NOT NULL REFERENCES triggers(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status          TEXT NOT NULL DEFAULT 'running',
    payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
    result          JSONB NOT NULL DEFAULT '{}'::jsonb,
    error           TEXT,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,

    CONSTRAINT trigger_runs_status_check CHECK (status IN (
        'running', 'succeeded', 'failed', 'cancelled'
    ))
);

CREATE INDEX IF NOT EXISTS idx_trigger_runs_trigger ON trigger_runs(trigger_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_trigger_runs_user ON trigger_runs(user_id, started_at DESC);

-- ============================================================
-- agent_traces: 自律エージェントのトレース (Phase 4 用)
-- ============================================================
CREATE TABLE IF NOT EXISTS agent_traces (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    trigger_run_id  UUID REFERENCES trigger_runs(id) ON DELETE SET NULL,
    agent_name      TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    content         JSONB NOT NULL DEFAULT '{}'::jsonb,
    parent_trace_id UUID REFERENCES agent_traces(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT agent_traces_event_check CHECK (event_type IN (
        'thinking', 'tool_call', 'tool_result', 'message',
        'decision', 'error', 'complete', 'sub_agent_start'
    ))
);

CREATE INDEX IF NOT EXISTS idx_agent_traces_user ON agent_traces(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_traces_run ON agent_traces(trigger_run_id, created_at);
CREATE INDEX IF NOT EXISTS idx_agent_traces_parent ON agent_traces(parent_trace_id);

-- ============================================================
-- RLS
-- ============================================================
ALTER TABLE triggers ENABLE ROW LEVEL SECURITY;
ALTER TABLE trigger_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_traces ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS triggers_own ON triggers;
CREATE POLICY triggers_own ON triggers
    FOR ALL USING (auth.uid() = user_id OR auth.role() = 'service_role');

DROP POLICY IF EXISTS trigger_runs_own ON trigger_runs;
CREATE POLICY trigger_runs_own ON trigger_runs
    FOR ALL USING (auth.uid() = user_id OR auth.role() = 'service_role');

DROP POLICY IF EXISTS agent_traces_own ON agent_traces;
CREATE POLICY agent_traces_own ON agent_traces
    FOR ALL USING (auth.uid() = user_id OR auth.role() = 'service_role');

COMMENT ON TABLE triggers IS 'Dan Workspace: ユーザー定義の自動化トリガー';
COMMENT ON COLUMN triggers.kind IS 'gmail/calendar/file/cron/collab/chat_command';
COMMENT ON COLUMN triggers.config IS 'kind依存の設定 (query, cron_expr, path_glob 等)';
COMMENT ON COLUMN triggers.actions IS '実行するアクションの配列 [{type: "classify"}, {type: "notify"}]';
COMMENT ON TABLE agent_traces IS 'Dan Workspace: 自律エージェントの思考・ツール呼び出しトレース';
