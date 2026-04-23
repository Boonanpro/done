-- AIX事業ダッシュボード — 7テーブル構成
-- AIで企業のDX支援を行うAIX事業の運営管理。
-- 課題分析 → 提案 → 営業 → 商談 → 契約 → 運用 → ダンタスクハブ
--
-- 生成日時: 2026-04-23

-- ==========================================
-- 1. クライアント
-- ==========================================
CREATE TABLE IF NOT EXISTS aix_clients (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    name TEXT NOT NULL,                       -- 会社名
    industry TEXT,                             -- 業界
    region TEXT,                               -- 地域
    size TEXT,                                 -- 規模（small/medium/large）
    website TEXT,
    contact_name TEXT,                         -- 担当者名
    contact_role TEXT,                         -- 役職
    contact_email TEXT,
    contact_phone TEXT,
    -- パイプラインステージ
    stage TEXT DEFAULT 'research'
      CHECK (stage IN ('research', 'proposal', 'negotiation', 'contracted', 'live', 'paused', 'lost')),
    health_score INT DEFAULT 50 CHECK (health_score BETWEEN 0 AND 100),
    estimated_value INT,                       -- 想定収益（円）
    notes TEXT,
    tags TEXT[] DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_by UUID REFERENCES auth.users(id)
);
CREATE INDEX IF NOT EXISTS idx_aix_clients_stage ON aix_clients(stage);
CREATE INDEX IF NOT EXISTS idx_aix_clients_owner ON aix_clients(created_by);

-- ==========================================
-- 2. 課題分析（仮説）
-- ==========================================
CREATE TABLE IF NOT EXISTS aix_hypotheses (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    client_id UUID NOT NULL REFERENCES aix_clients(id) ON DELETE CASCADE,
    title TEXT NOT NULL,                       -- 仮説タイトル
    pain_point TEXT,                           -- 課題（顧客の困りごと）
    proposed_solution TEXT,                    -- ダンが提案する解決策
    confidence INT DEFAULT 50 CHECK (confidence BETWEEN 0 AND 100),
    status TEXT DEFAULT 'draft'
      CHECK (status IN ('draft', 'validated', 'rejected', 'on_hold')),
    research_notes TEXT,                       -- リサーチメモ
    sources JSONB DEFAULT '[]',                -- 参照ソース（URLなど）
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_by UUID REFERENCES auth.users(id)
);
CREATE INDEX IF NOT EXISTS idx_aix_hypotheses_client ON aix_hypotheses(client_id);

-- ==========================================
-- 3. 提案アセット
-- ==========================================
CREATE TABLE IF NOT EXISTS aix_proposals (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    client_id UUID NOT NULL REFERENCES aix_clients(id) ON DELETE CASCADE,
    hypothesis_id UUID REFERENCES aix_hypotheses(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    summary TEXT,
    -- アセットへのリンク
    proposal_html_path TEXT,                   -- 提案HTML（D:/dan-workspace/proposals/xxx.html）
    proposal_video_path TEXT,                  -- 提案動画
    prototype_url TEXT,                        -- プロトタイプURL
    deck_url TEXT,                             -- スライド（外部）
    -- ステータス
    status TEXT DEFAULT 'draft'
      CHECK (status IN ('draft', 'ready', 'sent', 'viewed', 'replied', 'won', 'lost')),
    sent_at TIMESTAMPTZ,
    viewed_at TIMESTAMPTZ,
    response_summary TEXT,                     -- 反応要約
    estimated_value INT,                       -- 想定金額
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_by UUID REFERENCES auth.users(id)
);
CREATE INDEX IF NOT EXISTS idx_aix_proposals_client ON aix_proposals(client_id);
CREATE INDEX IF NOT EXISTS idx_aix_proposals_status ON aix_proposals(status);

-- ==========================================
-- 4. 営業・商談ログ
-- ==========================================
CREATE TABLE IF NOT EXISTS aix_activities (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    client_id UUID NOT NULL REFERENCES aix_clients(id) ON DELETE CASCADE,
    proposal_id UUID REFERENCES aix_proposals(id) ON DELETE SET NULL,
    activity_type TEXT NOT NULL
      CHECK (activity_type IN ('email_sent', 'email_received', 'call', 'meeting', 'note', 'task')),
    subject TEXT NOT NULL,
    body TEXT,
    occurred_at TIMESTAMPTZ DEFAULT NOW(),
    next_action TEXT,                          -- 次アクション
    next_action_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}',               -- email_id, calendar_event_id等
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by UUID REFERENCES auth.users(id)
);
CREATE INDEX IF NOT EXISTS idx_aix_activities_client ON aix_activities(client_id);
CREATE INDEX IF NOT EXISTS idx_aix_activities_occurred ON aix_activities(occurred_at DESC);

-- ==========================================
-- 5. 契約
-- ==========================================
CREATE TABLE IF NOT EXISTS aix_contracts (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    client_id UUID NOT NULL REFERENCES aix_clients(id) ON DELETE CASCADE,
    proposal_id UUID REFERENCES aix_proposals(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    contract_type TEXT,                        -- 'one_time' / 'subscription' / 'retainer'
    initial_value INT,                         -- 一時金（円）
    monthly_value INT,                         -- 月次（円）
    start_date DATE,
    end_date DATE,
    status TEXT DEFAULT 'draft'
      CHECK (status IN ('draft', 'pending_signature', 'active', 'completed', 'cancelled')),
    contract_file_url TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_by UUID REFERENCES auth.users(id)
);
CREATE INDEX IF NOT EXISTS idx_aix_contracts_client ON aix_contracts(client_id);

-- ==========================================
-- 6. 運用（提供中の成果物・KPI）
-- ==========================================
CREATE TABLE IF NOT EXISTS aix_engagements (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    client_id UUID NOT NULL REFERENCES aix_clients(id) ON DELETE CASCADE,
    contract_id UUID REFERENCES aix_contracts(id) ON DELETE SET NULL,
    deliverable_name TEXT NOT NULL,            -- "吉川特装HP"等
    deliverable_type TEXT,                     -- 'website' / 'tool' / 'dashboard' / 'other'
    deliverable_url TEXT,                      -- 提供中の成果物URL
    repo_path TEXT,                            -- ローカルリポジトリパス
    status TEXT DEFAULT 'live'
      CHECK (status IN ('building', 'live', 'maintenance', 'paused', 'sunset')),
    health_score INT DEFAULT 80 CHECK (health_score BETWEEN 0 AND 100),
    kpis JSONB DEFAULT '{}',                   -- 任意のKPI（visitors, conversions等）
    last_review_at TIMESTAMPTZ,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_by UUID REFERENCES auth.users(id)
);
CREATE INDEX IF NOT EXISTS idx_aix_engagements_client ON aix_engagements(client_id);

-- ==========================================
-- 7. ダンタスクハブ（Green/Yellow/Red ゾーン）
-- ==========================================
CREATE TABLE IF NOT EXISTS aix_tasks (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    client_id UUID REFERENCES aix_clients(id) ON DELETE SET NULL,
    proposal_id UUID REFERENCES aix_proposals(id) ON DELETE SET NULL,
    engagement_id UUID REFERENCES aix_engagements(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    description TEXT,
    -- 自律性ゾーン
    zone TEXT DEFAULT 'green'
      CHECK (zone IN ('green', 'yellow', 'red')),
    -- ステータス
    status TEXT DEFAULT 'todo'
      CHECK (status IN ('todo', 'in_progress', 'awaiting_approval', 'done', 'cancelled')),
    priority TEXT DEFAULT 'normal'
      CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
    requested_action TEXT,                     -- ダンに依頼した内容
    result_summary TEXT,                       -- 結果要約
    artifact_urls JSONB DEFAULT '[]',          -- 生成した成果物のURL
    due_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_by UUID REFERENCES auth.users(id)
);
CREATE INDEX IF NOT EXISTS idx_aix_tasks_status ON aix_tasks(status);
CREATE INDEX IF NOT EXISTS idx_aix_tasks_zone ON aix_tasks(zone);
CREATE INDEX IF NOT EXISTS idx_aix_tasks_client ON aix_tasks(client_id);

-- ==========================================
-- RLS（みきさん専用 = created_byスコープ）
-- ==========================================
ALTER TABLE aix_clients ENABLE ROW LEVEL SECURITY;
ALTER TABLE aix_hypotheses ENABLE ROW LEVEL SECURITY;
ALTER TABLE aix_proposals ENABLE ROW LEVEL SECURITY;
ALTER TABLE aix_activities ENABLE ROW LEVEL SECURITY;
ALTER TABLE aix_contracts ENABLE ROW LEVEL SECURITY;
ALTER TABLE aix_engagements ENABLE ROW LEVEL SECURITY;
ALTER TABLE aix_tasks ENABLE ROW LEVEL SECURITY;

CREATE POLICY "aix_clients_owner" ON aix_clients FOR ALL USING (created_by = auth.uid());
CREATE POLICY "aix_hypotheses_owner" ON aix_hypotheses FOR ALL USING (created_by = auth.uid());
CREATE POLICY "aix_proposals_owner" ON aix_proposals FOR ALL USING (created_by = auth.uid());
CREATE POLICY "aix_activities_owner" ON aix_activities FOR ALL USING (created_by = auth.uid());
CREATE POLICY "aix_contracts_owner" ON aix_contracts FOR ALL USING (created_by = auth.uid());
CREATE POLICY "aix_engagements_owner" ON aix_engagements FOR ALL USING (created_by = auth.uid());
CREATE POLICY "aix_tasks_owner" ON aix_tasks FOR ALL USING (created_by = auth.uid());

-- ==========================================
-- updated_at トリガー
-- ==========================================
CREATE OR REPLACE FUNCTION update_aix_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER aix_clients_updated_at      BEFORE UPDATE ON aix_clients      FOR EACH ROW EXECUTE FUNCTION update_aix_updated_at();
CREATE TRIGGER aix_hypotheses_updated_at   BEFORE UPDATE ON aix_hypotheses   FOR EACH ROW EXECUTE FUNCTION update_aix_updated_at();
CREATE TRIGGER aix_proposals_updated_at    BEFORE UPDATE ON aix_proposals    FOR EACH ROW EXECUTE FUNCTION update_aix_updated_at();
CREATE TRIGGER aix_contracts_updated_at    BEFORE UPDATE ON aix_contracts    FOR EACH ROW EXECUTE FUNCTION update_aix_updated_at();
CREATE TRIGGER aix_engagements_updated_at  BEFORE UPDATE ON aix_engagements  FOR EACH ROW EXECUTE FUNCTION update_aix_updated_at();
CREATE TRIGGER aix_tasks_updated_at        BEFORE UPDATE ON aix_tasks        FOR EACH ROW EXECUTE FUNCTION update_aix_updated_at();
