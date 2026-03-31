-- 034: ダッシュボードテーブルにowner_id追加 + collab_invitesにuser_id追加

-- ============================================================
-- 1. ダッシュボードテーブルにowner_idカラム追加
-- ============================================================

-- dashboard_businesses
ALTER TABLE dashboard_businesses ADD COLUMN IF NOT EXISTS owner_id UUID REFERENCES users(id);
UPDATE dashboard_businesses SET owner_id = '2582a188-ff24-4a4f-b989-6063034d90b2' WHERE owner_id IS NULL;

-- b2b_companies
ALTER TABLE b2b_companies ADD COLUMN IF NOT EXISTS owner_id UUID REFERENCES users(id);
UPDATE b2b_companies SET owner_id = '2582a188-ff24-4a4f-b989-6063034d90b2' WHERE owner_id IS NULL;

-- b2b_deals
ALTER TABLE b2b_deals ADD COLUMN IF NOT EXISTS owner_id UUID REFERENCES users(id);
UPDATE b2b_deals SET owner_id = '2582a188-ff24-4a4f-b989-6063034d90b2' WHERE owner_id IS NULL;

-- b2b_contracts
ALTER TABLE b2b_contracts ADD COLUMN IF NOT EXISTS owner_id UUID REFERENCES users(id);
UPDATE b2b_contracts SET owner_id = '2582a188-ff24-4a4f-b989-6063034d90b2' WHERE owner_id IS NULL;

-- b2b_emails
ALTER TABLE b2b_emails ADD COLUMN IF NOT EXISTS owner_id UUID REFERENCES users(id);
UPDATE b2b_emails SET owner_id = '2582a188-ff24-4a4f-b989-6063034d90b2' WHERE owner_id IS NULL;

-- dx_clients
ALTER TABLE dx_clients ADD COLUMN IF NOT EXISTS owner_id UUID REFERENCES users(id);
UPDATE dx_clients SET owner_id = '2582a188-ff24-4a4f-b989-6063034d90b2' WHERE owner_id IS NULL;

-- dx_projects
ALTER TABLE dx_projects ADD COLUMN IF NOT EXISTS owner_id UUID REFERENCES users(id);
UPDATE dx_projects SET owner_id = '2582a188-ff24-4a4f-b989-6063034d90b2' WHERE owner_id IS NULL;

-- ============================================================
-- 2. collab_invitesにuser_idカラム追加（ゲスト→ログインユーザー紐づけ用）
-- ============================================================

ALTER TABLE collab_invites ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id);
