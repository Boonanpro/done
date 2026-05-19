-- クライアント所有ドメインのセットアップ案内フロー用カラム。
--
-- オーナーが公開時に「クライアントが用意する」を選ぶと domain_setup_token を発行し、
-- クライアントは /domain-setup/<token> の公開ページから
-- ドメイン購入 → DNS設定 → 所有権検証 までを自分で進められる。
-- これによりオーナーが代理決済する必要がなく、ドメインはクライアント資産になる。
--
-- domain_setup (JSONB) の構造:
--   {
--     "domain": "example.com",
--     "vercel_project": "frontend",
--     "slug": "<artifact slug>",
--     "status": "pending" | "dns_pending" | "live" | "failed",
--     "dns_records": [ {"type","name","value","purpose"} ],
--     "availability": { "registrable": true, "pricing": {...} },
--     "registrar_links": [ {"label","url"} ],
--     "created_at": "ISO8601",
--     "verified_at": "ISO8601" | null,
--     "last_error": null,
--     "search_console": { "configured": bool, "verified": bool, "sitemap_submitted": bool, "detail": "" }
--   }

ALTER TABLE chat_artifact
    ADD COLUMN IF NOT EXISTS domain_setup_token TEXT,
    ADD COLUMN IF NOT EXISTS domain_setup JSONB;

-- トークンは公開ページの引き当てキー。NULL を許しつつ、値があれば一意。
CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_artifact_domain_setup_token
    ON chat_artifact(domain_setup_token)
    WHERE domain_setup_token IS NOT NULL;
