-- DX事業統合ダッシュボード Schema
-- Business slug: dx
-- Prefix: dx_

-- 1. Register DX business in hub
INSERT INTO dashboard_businesses (name, slug, description, icon, status)
VALUES ('DX事業', 'dx', 'HP制作・DXツール提供のクライアント・プロジェクト管理', 'layout-dashboard', 'active')
ON CONFLICT (slug) DO NOTHING;

-- 2. dx_clients (クライアント企業)
CREATE TABLE IF NOT EXISTS dx_clients (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  name TEXT NOT NULL,
  industry TEXT,
  contact_person TEXT,
  contact_email TEXT,
  contact_phone TEXT,
  address TEXT,
  website_url TEXT,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('lead', 'active', 'paused', 'churned')),
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT now() NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dx_clients_status ON dx_clients(status);
CREATE TRIGGER trg_dx_clients_updated_at BEFORE UPDATE ON dx_clients FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- 3. dx_projects (HP/DXプロジェクト)
CREATE TABLE IF NOT EXISTS dx_projects (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  client_id UUID NOT NULL REFERENCES dx_clients(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  project_type TEXT NOT NULL DEFAULT 'homepage' CHECK (project_type IN ('homepage', 'lp', 'ec', 'dx_tool', 'redesign', 'other')),
  tech_stack TEXT[] DEFAULT '{}',
  deploy_url TEXT,
  repo_url TEXT,
  status TEXT NOT NULL DEFAULT 'planning' CHECK (status IN ('planning', 'in_progress', 'review', 'deployed', 'maintenance', 'archived')),
  estimated_amount INTEGER DEFAULT 0,
  notes TEXT,
  started_at DATE,
  deployed_at DATE,
  created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT now() NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dx_projects_client ON dx_projects(client_id);
CREATE INDEX IF NOT EXISTS idx_dx_projects_status ON dx_projects(status);
CREATE TRIGGER trg_dx_projects_updated_at BEFORE UPDATE ON dx_projects FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- 4. dx_media (メディアファイル管理 - Phase 3用、テーブルだけ先に作成)
CREATE TABLE IF NOT EXISTS dx_media (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  project_id UUID REFERENCES dx_projects(id) ON DELETE SET NULL,
  filename TEXT NOT NULL,
  file_url TEXT NOT NULL,
  file_type TEXT NOT NULL DEFAULT 'image' CHECK (file_type IN ('image', 'video', 'document', 'other')),
  file_size INTEGER,
  mime_type TEXT,
  tags TEXT[] DEFAULT '{}',
  used_in TEXT[] DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT now() NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dx_media_project ON dx_media(project_id);

-- 5. Seed: 既存クライアント3社を登録
INSERT INTO dx_clients (name, industry, status, notes) VALUES
  ('吉川特装自動車', '自動車・特装車', 'active', 'HP納品済み: yoshikawa-tokuso.vercel.app'),
  ('OBANZAI bar 五条', '飲食・バー', 'active', 'HP納品済み: gojo-salon.vercel.app'),
  ('バードSTC', 'スポーツ・テニス', 'active', 'HP納品済み: bird-stc.vercel.app')
ON CONFLICT DO NOTHING;

-- 6. Seed: 既存プロジェクトを登録
INSERT INTO dx_projects (client_id, name, project_type, tech_stack, deploy_url, status, deployed_at)
SELECT c.id, c.name || ' ホームページ', 'homepage', ARRAY['Astro', 'Tailwind CSS'],
  CASE c.name
    WHEN '吉川特装自動車' THEN 'https://yoshikawa-tokuso.vercel.app'
    WHEN 'OBANZAI bar 五条' THEN 'https://gojo-salon.vercel.app'
    WHEN 'バードSTC' THEN 'https://bird-stc.vercel.app'
  END,
  'deployed', CURRENT_DATE
FROM dx_clients c
WHERE c.name IN ('吉川特装自動車', 'OBANZAI bar 五条', 'バードSTC')
ON CONFLICT DO NOTHING;
