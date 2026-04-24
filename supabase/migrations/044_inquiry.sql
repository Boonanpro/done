-- inquiry: クライアントHPの問い合わせフォーム送信先
-- 公開エンドポイント (POST /api/v1/inquiries) が直接insertする。RLSは運用側(select/update)のみ。

CREATE TABLE IF NOT EXISTS inquiries (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    scope TEXT NOT NULL,                         -- 'yoshikawa', 'gojo' 等のクライアント識別子
    name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    company TEXT,
    message TEXT NOT NULL,
    source_url TEXT,                             -- どのページから送信されたか
    user_agent TEXT,
    client_ip TEXT,
    status TEXT DEFAULT 'new',                   -- new / read / replied / archived
    notified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS inquiries_scope_created_at_idx
    ON inquiries (scope, created_at DESC);

CREATE INDEX IF NOT EXISTS inquiries_status_idx
    ON inquiries (status);

ALTER TABLE inquiries ENABLE ROW LEVEL SECURITY;

-- 公開endpointはservice roleで書き込むためRLSを通さない。
-- 管理画面のselect/updateのみ認証ユーザーに許可。
CREATE POLICY "inquiries_authenticated_select" ON inquiries
    FOR SELECT TO authenticated USING (true);

CREATE POLICY "inquiries_authenticated_update" ON inquiries
    FOR UPDATE TO authenticated USING (true);
