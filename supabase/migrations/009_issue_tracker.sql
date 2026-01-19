-- Issue Tracker for Development Prioritization
-- 実装すべき機能のイシューを記録し、優先度を追跡する

-- issuesテーブル
CREATE TABLE IF NOT EXISTS issues (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id),

    -- イシュー情報
    issue_type TEXT NOT NULL, -- 'executor_missing', 'selector_outdated', 'execution_failed', 'search_failed'
    status TEXT DEFAULT 'open', -- 'open', 'in_progress', 'resolved', 'wont_fix'
    priority INT DEFAULT 1, -- 発生回数（同じイシューが発生するたびに+1）

    -- リクエスト情報
    original_wish TEXT NOT NULL, -- ユーザーの元のリクエスト
    research_result JSONB, -- AIの推論結果（service_type, service_name, params等）

    -- 失敗情報
    service_type TEXT, -- airline, train, bus, hotel, product, voice等
    service_name TEXT, -- jal, ex_reservation, willer, amazon等
    error_message TEXT,
    error_details JSONB,

    -- 提案される解決策
    suggested_solutions JSONB, -- [{type: 'create_executor', description: '...', estimated_effort: 'medium'}, ...]

    -- タイムスタンプ
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    resolved_at TIMESTAMPTZ,

    -- 最後に発生した時刻（priorityカウント用）
    last_occurred_at TIMESTAMPTZ DEFAULT now()
);

-- インデックス
-- 同じイシューの検索用（重複検出）
CREATE INDEX idx_issues_type_service ON issues(issue_type, service_type, service_name, status);

-- 優先度順ソート用
CREATE INDEX idx_issues_priority ON issues(priority DESC, created_at DESC) WHERE status = 'open';

-- ステータス検索用
CREATE INDEX idx_issues_status ON issues(status, priority DESC);

-- サービスタイプ検索用
CREATE INDEX idx_issues_service_type ON issues(service_type, priority DESC) WHERE status = 'open';

-- RLS (Row Level Security) ポリシー
ALTER TABLE issues ENABLE ROW LEVEL SECURITY;

-- 全ユーザーが自分のイシューを作成できる
CREATE POLICY "Users can create their own issues"
    ON issues FOR INSERT
    WITH CHECK (auth.uid() = user_id);

-- 全ユーザーが全イシューを閲覧できる（開発の透明性のため）
CREATE POLICY "Anyone can view all issues"
    ON issues FOR SELECT
    USING (true);

-- 管理者のみがイシューを更新できる（将来的に管理者ロールを追加する想定）
CREATE POLICY "Admins can update issues"
    ON issues FOR UPDATE
    USING (true); -- TODO: 管理者チェックを追加

-- updated_at自動更新トリガー
CREATE OR REPLACE FUNCTION update_issues_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_issues_updated_at
    BEFORE UPDATE ON issues
    FOR EACH ROW
    EXECUTE FUNCTION update_issues_updated_at();

-- issue_occurrences テーブル（各発生の詳細履歴）
CREATE TABLE IF NOT EXISTS issue_occurrences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    issue_id UUID REFERENCES issues(id) ON DELETE CASCADE,
    user_id UUID REFERENCES auth.users(id),

    -- 発生時の詳細情報
    original_wish TEXT NOT NULL,
    research_result JSONB,
    error_message TEXT,
    error_details JSONB,

    occurred_at TIMESTAMPTZ DEFAULT now()
);

-- インデックス
CREATE INDEX idx_issue_occurrences_issue_id ON issue_occurrences(issue_id, occurred_at DESC);

-- RLS
ALTER TABLE issue_occurrences ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can create occurrence records"
    ON issue_occurrences FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Anyone can view occurrence records"
    ON issue_occurrences FOR SELECT
    USING (true);

-- 便利なビュー: 最近のオープンイシューを優先度順に表示
CREATE OR REPLACE VIEW open_issues_by_priority AS
SELECT
    i.*,
    COUNT(io.id) as occurrence_count,
    MAX(io.occurred_at) as last_occurrence
FROM issues i
LEFT JOIN issue_occurrences io ON i.id = io.issue_id
WHERE i.status = 'open'
GROUP BY i.id
ORDER BY i.priority DESC, i.created_at DESC;
