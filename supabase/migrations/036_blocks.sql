-- Migration 036: Blocks — AI Native Information Hub (Dan Workspace)
--
-- Notionライクな「全てがブロック」のデータモデル。
-- テキスト、画像、PDF、タスク、メールなどを全て単一の `blocks` テーブルで扱う。
-- 親子関係は Adjacency List、順序は Fractional Indexing で管理する。

-- ============================================================
-- blocks: コアテーブル
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
    deleted_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT blocks_type_check CHECK (type IN (
        'page', 'paragraph', 'heading', 'bullet_list', 'numbered_list',
        'checklist', 'task', 'quote', 'code', 'divider', 'callout',
        'image', 'video', 'audio', 'pdf', 'file', 'embed',
        'email', 'calendar_event', 'table', 'database', 'bookmark'
    )),
    CONSTRAINT blocks_created_by_check CHECK (created_by IN ('user', 'ai', 'system')),
    CONSTRAINT blocks_source_check CHECK (source IN (
        'manual', 'gmail', 'calendar', 'collab', 'chat', 'file_upload', 'agent'
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
CREATE OR REPLACE FUNCTION update_blocks_updated_at()
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
    EXECUTE FUNCTION update_blocks_updated_at();

-- ============================================================
-- block_files: ブロックに紐づくファイル実体(バージョン管理)
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
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_block_files_block_id ON block_files(block_id);
CREATE INDEX IF NOT EXISTS idx_block_files_current ON block_files(block_id, is_current) WHERE is_current = true;
CREATE INDEX IF NOT EXISTS idx_block_files_checksum ON block_files(checksum) WHERE checksum IS NOT NULL;

-- ============================================================
-- RLS: ユーザーは自分のブロックのみ操作可
-- ============================================================
ALTER TABLE blocks ENABLE ROW LEVEL SECURITY;
ALTER TABLE block_files ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS blocks_select_own ON blocks;
CREATE POLICY blocks_select_own ON blocks
    FOR SELECT USING (auth.uid() = user_id);

DROP POLICY IF EXISTS blocks_insert_own ON blocks;
CREATE POLICY blocks_insert_own ON blocks
    FOR INSERT WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS blocks_update_own ON blocks;
CREATE POLICY blocks_update_own ON blocks
    FOR UPDATE USING (auth.uid() = user_id);

DROP POLICY IF EXISTS blocks_delete_own ON blocks;
CREATE POLICY blocks_delete_own ON blocks
    FOR DELETE USING (auth.uid() = user_id);

DROP POLICY IF EXISTS blocks_service_all ON blocks;
CREATE POLICY blocks_service_all ON blocks
    FOR ALL USING (auth.role() = 'service_role');

DROP POLICY IF EXISTS block_files_select_own ON block_files;
CREATE POLICY block_files_select_own ON block_files
    FOR SELECT USING (
        EXISTS (SELECT 1 FROM blocks WHERE blocks.id = block_files.block_id AND blocks.user_id = auth.uid())
    );

DROP POLICY IF EXISTS block_files_service_all ON block_files;
CREATE POLICY block_files_service_all ON block_files
    FOR ALL USING (auth.role() = 'service_role');

COMMENT ON TABLE blocks IS 'Dan Workspace: 全てのコンテンツを統一管理するブロックテーブル';
COMMENT ON COLUMN blocks.order_key IS 'Fractional Index: 辞書順ソートで並び替え時の更新を1行に限定';
COMMENT ON COLUMN blocks.properties IS 'type別のプロパティ: {level:2} for heading, {checked:false} for task, など';
COMMENT ON COLUMN blocks.content IS 'リッチテキストコンテンツ (BlockNote/ProseMirror JSON)';
COMMENT ON COLUMN blocks.source IS '作成元: manual/gmail/calendar/collab/chat/file_upload/agent';
