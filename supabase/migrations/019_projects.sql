-- Projects System - プロジェクト管理基盤
-- メインチャットで受けた重いタスクを独立プロジェクトとして管理

-- ==================== Projects Table ====================
CREATE TABLE IF NOT EXISTS projects (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- プロジェクト基本情報
    title VARCHAR(255) NOT NULL,
    description TEXT,                    -- ユーザーの元リクエスト
    status VARCHAR(50) NOT NULL DEFAULT 'planning',
        -- planning: ダンがリサーチ・計画中
        -- proposed: 計画が提示され承認待ち
        -- approved: 承認済み、実行待ちまたは実行中
        -- in_progress: 実行中
        -- completed: 完了
        -- paused: 一時停止
        -- cancelled: キャンセル

    -- チャットルーム連携
    room_id UUID REFERENCES chat_rooms(id) ON DELETE SET NULL,
        -- プロジェクト専用チャットルーム（type='project'）
    origin_room_id UUID REFERENCES chat_rooms(id) ON DELETE SET NULL,
        -- このプロジェクトを生んだメインチャットのルーム

    -- メインチャット・音声から参照するためのサマリー
    summary TEXT,

    -- 柔軟なメタデータ（タグ、優先度、見積もり等）
    metadata JSONB DEFAULT '{}',

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_projects_user_id ON projects(user_id);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);
CREATE INDEX IF NOT EXISTS idx_projects_user_status ON projects(user_id, status);
CREATE INDEX IF NOT EXISTS idx_projects_room_id ON projects(room_id);
CREATE INDEX IF NOT EXISTS idx_projects_updated_at ON projects(updated_at DESC);

-- Updated_at trigger
CREATE TRIGGER update_projects_updated_at
    BEFORE UPDATE ON projects
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ==================== Project Proposals Table ====================
-- プロジェクト内の提案（計画）→ 承認フロー
CREATE TABLE IF NOT EXISTS project_proposals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    -- 提案内容
    content TEXT NOT NULL,               -- 計画の本文（Markdown）
    proposal_type VARCHAR(50) NOT NULL DEFAULT 'plan',
        -- plan: 初期計画
        -- revision: 修正計画
        -- heartbeat: ハートビートによる自律提案

    -- 承認状態
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
        -- pending: 承認待ち
        -- approved: 承認済み
        -- rejected: 却下
        -- superseded: 新しい提案で置き換え済み

    -- メタデータ（ステップ分解、見積もり等）
    steps JSONB DEFAULT '[]',            -- 実行ステップの配列
    metadata JSONB DEFAULT '{}',

    approved_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_project_proposals_project_id ON project_proposals(project_id);
CREATE INDEX IF NOT EXISTS idx_project_proposals_status ON project_proposals(status);

-- ==================== RLS Policies ====================
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE project_proposals ENABLE ROW LEVEL SECURITY;

-- Projects: ユーザーは自分のプロジェクトのみアクセス
CREATE POLICY "Users can view own projects"
    ON projects FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Service role full access projects"
    ON projects FOR ALL
    TO service_role
    USING (true);

-- Proposals: プロジェクト所有者のみアクセス
CREATE POLICY "Users can view own project proposals"
    ON project_proposals FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM projects
            WHERE projects.id = project_proposals.project_id
            AND projects.user_id = auth.uid()
        )
    );

CREATE POLICY "Service role full access project_proposals"
    ON project_proposals FOR ALL
    TO service_role
    USING (true);
