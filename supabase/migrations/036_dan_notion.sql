-- Migration 036: ダン用Notion (Dan Notion)
--
-- 統一されたBlockベース情報管理基盤 + 自律エージェント (CMAライク) のスキーマ。
-- 旧マイグレーション 036_blocks.sql / 037_triggers.sql の内容を統合・拡張する。
--
-- 構成:
--   1. pgvector 拡張
--   2. blocks            … 全コンテンツの統一テーブル (page/text/image/pdf/task/...)
--   3. block_files       … ブロックに紐づくファイル実体 (バージョン管理)
--   4. block_versions    … blocks.content の変更履歴 (自動世代管理)
--   5. block_embeddings  … 自然言語検索用 (pgvector)
--   6. triggers          … ユーザー定義の自動化トリガー
--   7. trigger_runs      … トリガー実行履歴
--   8. agent_traces      … 自律エージェントの思考プロセス トレース
--   9. dan_notifications … 通知センター
--
-- 適用方法: Supabase Management API 経由で query エンドポイントに POST する。
--           手順は MEMORY.md の「Supabase DDL実行手順」を参照。

-- ============================================================
-- 0. 拡張
-- ============================================================
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================
-- 1. blocks: コアテーブル
-- ============================================================
CREATE TABLE IF NOT EXISTS blocks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    parent_id       UUID REFERENCES blocks(id) ON DELETE CASCADE,
    type            TEXT NOT NULL,
    order_key       TEXT NOT NULL,
    properties      JSONB NOT NULL DEFAULT '{}'::jsonb,
    content         JSONB NOT NULL DEFAULT '[]'::jsonb,
    icon            TEXT,
    cover_url       TEXT,
    is_starred      BOOLEAN NOT NULL DEFAULT false,
    tags            TEXT[] NOT NULL DEFAULT '{}',
    created_by      TEXT NOT NULL DEFAULT 'user',
    source          TEXT NOT NULL DEFAULT 'manual',
    source_id       TEXT,
    version         INTEGER NOT NULL DEFAULT 1,
    deleted_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT blocks_type_check CHECK (type IN (
        'page', 'paragraph', 'heading', 'bullet_list', 'numbered_list',
        'checklist', 'task', 'quote', 'code', 'divider', 'callout',
        'image', 'video', 'audio', 'pdf', 'file', 'embed',
        'email', 'calendar_event', 'table', 'database', 'bookmark',
        'invoice', 'meeting_note', 'proposal_ref'
    )),
    CONSTRAINT blocks_created_by_check CHECK (created_by IN ('user', 'ai', 'system')),
    CONSTRAINT blocks_source_check CHECK (source IN (
        'manual', 'gmail', 'calendar', 'collab', 'chat', 'file_upload', 'agent', 'autopilot'
    ))
);

CREATE INDEX IF NOT EXISTS idx_blocks_user_id ON blocks(user_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_blocks_parent_order ON blocks(parent_id, order_key) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_blocks_type ON blocks(type) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_blocks_source ON blocks(source, source_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_blocks_starred ON blocks(user_id, is_starred) WHERE is_starred = true AND deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_blocks_tags ON blocks USING gin(tags) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_blocks_updated_at ON blocks(user_id, updated_at DESC) WHERE deleted_at IS NULL;

-- updated_at 自動更新
CREATE OR REPLACE FUNCTION update_dan_notion_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_blocks_updated_at ON blocks;
CREATE TRIGGER trg_blocks_updated_at
    BEFORE UPDATE ON blocks
    FOR EACH ROW
    EXECUTE FUNCTION update_dan_notion_updated_at();

-- ============================================================
-- 2. block_files: ファイル実体 (バージョン管理)
-- ============================================================
CREATE TABLE IF NOT EXISTS block_files (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    block_id        UUID NOT NULL REFERENCES blocks(id) ON DELETE CASCADE,
    storage_path    TEXT NOT NULL,
    original_name   TEXT NOT NULL,
    mime_type       TEXT NOT NULL,
    file_size       BIGINT NOT NULL,
    version         INTEGER NOT NULL DEFAULT 1,
    is_current      BOOLEAN NOT NULL DEFAULT true,
    checksum        TEXT,
    thumbnail_path  TEXT,
    width           INTEGER,
    height          INTEGER,
    duration_ms     INTEGER,
    ocr_text        TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_block_files_block_id ON block_files(block_id);
CREATE INDEX IF NOT EXISTS idx_block_files_current ON block_files(block_id, is_current) WHERE is_current = true;
CREATE INDEX IF NOT EXISTS idx_block_files_checksum ON block_files(checksum) WHERE checksum IS NOT NULL;

-- ============================================================
-- 3. block_versions: blocks.content の世代管理
-- ============================================================
CREATE TABLE IF NOT EXISTS block_versions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    block_id        UUID NOT NULL REFERENCES blocks(id) ON DELETE CASCADE,
    version         INTEGER NOT NULL,
    content         JSONB NOT NULL,
    properties      JSONB NOT NULL DEFAULT '{}'::jsonb,
    changed_by      TEXT NOT NULL DEFAULT 'user',
    change_summary  TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (block_id, version)
);

CREATE INDEX IF NOT EXISTS idx_block_versions_block ON block_versions(block_id, version DESC);

-- 自動世代保存トリガー: blocks の content / properties が変更されたら旧版を保存
CREATE OR REPLACE FUNCTION save_block_version()
RETURNS TRIGGER AS $$
BEGIN
    IF (OLD.content IS DISTINCT FROM NEW.content)
       OR (OLD.properties IS DISTINCT FROM NEW.properties) THEN
        INSERT INTO block_versions (block_id, version, content, properties, changed_by)
        VALUES (OLD.id, OLD.version, OLD.content, OLD.properties, OLD.created_by);
        NEW.version := OLD.version + 1;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_blocks_save_version ON blocks;
CREATE TRIGGER trg_blocks_save_version
    BEFORE UPDATE ON blocks
    FOR EACH ROW
    EXECUTE FUNCTION save_block_version();

-- ============================================================
-- 4. block_embeddings: 自然言語検索 (pgvector)
-- ============================================================
-- multilingual-e5-small は 384 次元
CREATE TABLE IF NOT EXISTS block_embeddings (
    block_id        UUID PRIMARY KEY REFERENCES blocks(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    embedding       vector(384) NOT NULL,
    summary         TEXT,
    auto_tags       TEXT[] NOT NULL DEFAULT '{}',
    auto_category   TEXT,
    entities        JSONB NOT NULL DEFAULT '{}'::jsonb,
    model           TEXT NOT NULL DEFAULT 'multilingual-e5-small',
    text_hash       TEXT NOT NULL,
    indexed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_block_embeddings_user ON block_embeddings(user_id);
CREATE INDEX IF NOT EXISTS idx_block_embeddings_vec
    ON block_embeddings USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- ============================================================
-- 5. triggers: 自動化トリガー
-- ============================================================
CREATE TABLE IF NOT EXISTS triggers (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    description     TEXT,
    kind            TEXT NOT NULL,
    config          JSONB NOT NULL DEFAULT '{}'::jsonb,
    logic           JSONB NOT NULL DEFAULT '{}'::jsonb,
    actions         JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_enabled      BOOLEAN NOT NULL DEFAULT true,
    last_fired_at   TIMESTAMPTZ,
    fire_count      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT triggers_kind_check CHECK (kind IN (
        'gmail', 'calendar', 'file', 'cron', 'collab', 'chat_command', 'block_changed', 'manual'
    ))
);

CREATE INDEX IF NOT EXISTS idx_triggers_user ON triggers(user_id);
CREATE INDEX IF NOT EXISTS idx_triggers_kind ON triggers(kind, is_enabled);

DROP TRIGGER IF EXISTS trg_triggers_updated_at ON triggers;
CREATE TRIGGER trg_triggers_updated_at
    BEFORE UPDATE ON triggers
    FOR EACH ROW
    EXECUTE FUNCTION update_dan_notion_updated_at();

-- ============================================================
-- 6. trigger_runs: 実行履歴
-- ============================================================
CREATE TABLE IF NOT EXISTS trigger_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trigger_id      UUID NOT NULL REFERENCES triggers(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status          TEXT NOT NULL DEFAULT 'running',
    payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
    result          JSONB NOT NULL DEFAULT '{}'::jsonb,
    error           TEXT,
    cli_session_id  TEXT,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,

    CONSTRAINT trigger_runs_status_check CHECK (status IN (
        'running', 'succeeded', 'failed', 'cancelled'
    ))
);

CREATE INDEX IF NOT EXISTS idx_trigger_runs_trigger ON trigger_runs(trigger_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_trigger_runs_user ON trigger_runs(user_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_trigger_runs_status ON trigger_runs(status) WHERE status = 'running';

-- ============================================================
-- 7. agent_traces: 自律エージェントの思考プロセス
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
        'decision', 'error', 'complete', 'sub_agent_start', 'self_repair'
    ))
);

CREATE INDEX IF NOT EXISTS idx_agent_traces_user ON agent_traces(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_traces_run ON agent_traces(trigger_run_id, created_at);
CREATE INDEX IF NOT EXISTS idx_agent_traces_parent ON agent_traces(parent_trace_id);

-- ============================================================
-- 8. dan_notifications: 通知センター
-- ============================================================
CREATE TABLE IF NOT EXISTS dan_notifications (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind            TEXT NOT NULL,
    title           TEXT NOT NULL,
    body            TEXT,
    block_id        UUID REFERENCES blocks(id) ON DELETE SET NULL,
    trigger_run_id  UUID REFERENCES trigger_runs(id) ON DELETE SET NULL,
    severity        TEXT NOT NULL DEFAULT 'info',
    due_at          TIMESTAMPTZ,
    read_at         TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT dan_notifications_severity_check CHECK (severity IN ('info', 'warning', 'urgent'))
);

CREATE INDEX IF NOT EXISTS idx_dan_notifications_user_unread
    ON dan_notifications(user_id, created_at DESC) WHERE read_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_dan_notifications_due
    ON dan_notifications(user_id, due_at) WHERE due_at IS NOT NULL AND read_at IS NULL;

-- ============================================================
-- RLS
-- ============================================================
ALTER TABLE blocks            ENABLE ROW LEVEL SECURITY;
ALTER TABLE block_files       ENABLE ROW LEVEL SECURITY;
ALTER TABLE block_versions    ENABLE ROW LEVEL SECURITY;
ALTER TABLE block_embeddings  ENABLE ROW LEVEL SECURITY;
ALTER TABLE triggers          ENABLE ROW LEVEL SECURITY;
ALTER TABLE trigger_runs      ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_traces      ENABLE ROW LEVEL SECURITY;
ALTER TABLE dan_notifications ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS blocks_own ON blocks;
CREATE POLICY blocks_own ON blocks
    FOR ALL USING (auth.uid() = user_id OR auth.role() = 'service_role');

DROP POLICY IF EXISTS block_files_own ON block_files;
CREATE POLICY block_files_own ON block_files
    FOR ALL USING (
        auth.role() = 'service_role'
        OR EXISTS (SELECT 1 FROM blocks b WHERE b.id = block_files.block_id AND b.user_id = auth.uid())
    );

DROP POLICY IF EXISTS block_versions_own ON block_versions;
CREATE POLICY block_versions_own ON block_versions
    FOR ALL USING (
        auth.role() = 'service_role'
        OR EXISTS (SELECT 1 FROM blocks b WHERE b.id = block_versions.block_id AND b.user_id = auth.uid())
    );

DROP POLICY IF EXISTS block_embeddings_own ON block_embeddings;
CREATE POLICY block_embeddings_own ON block_embeddings
    FOR ALL USING (auth.uid() = user_id OR auth.role() = 'service_role');

DROP POLICY IF EXISTS triggers_own ON triggers;
CREATE POLICY triggers_own ON triggers
    FOR ALL USING (auth.uid() = user_id OR auth.role() = 'service_role');

DROP POLICY IF EXISTS trigger_runs_own ON trigger_runs;
CREATE POLICY trigger_runs_own ON trigger_runs
    FOR ALL USING (auth.uid() = user_id OR auth.role() = 'service_role');

DROP POLICY IF EXISTS agent_traces_own ON agent_traces;
CREATE POLICY agent_traces_own ON agent_traces
    FOR ALL USING (auth.uid() = user_id OR auth.role() = 'service_role');

DROP POLICY IF EXISTS dan_notifications_own ON dan_notifications;
CREATE POLICY dan_notifications_own ON dan_notifications
    FOR ALL USING (auth.uid() = user_id OR auth.role() = 'service_role');

-- ============================================================
-- ヘルパー関数: 自然言語検索 (cosine similarity)
-- ============================================================
CREATE OR REPLACE FUNCTION search_blocks_by_embedding(
    p_user_id UUID,
    p_query_embedding vector(384),
    p_limit INT DEFAULT 20
)
RETURNS TABLE (
    block_id UUID,
    similarity FLOAT,
    summary TEXT
) AS $$
    SELECT
        be.block_id,
        1 - (be.embedding <=> p_query_embedding) AS similarity,
        be.summary
    FROM block_embeddings be
    JOIN blocks b ON b.id = be.block_id
    WHERE be.user_id = p_user_id
      AND b.deleted_at IS NULL
    ORDER BY be.embedding <=> p_query_embedding
    LIMIT p_limit;
$$ LANGUAGE sql STABLE;

-- ============================================================
-- コメント
-- ============================================================
COMMENT ON TABLE blocks IS 'ダン用Notion: 全コンテンツの統一ブロックテーブル';
COMMENT ON TABLE block_versions IS 'ダン用Notion: blocks.content の自動世代管理';
COMMENT ON TABLE block_embeddings IS 'ダン用Notion: pgvector による自然言語検索インデックス';
COMMENT ON TABLE triggers IS 'ダン用Notion: ユーザー定義の自動化トリガー (CMAライク)';
COMMENT ON TABLE agent_traces IS 'ダン用Notion: 自律エージェントの思考プロセス トレース (UI可視化用)';
COMMENT ON TABLE dan_notifications IS 'ダン用Notion: 通知センター (請求書期限・自動処理結果など)';
