-- Calendar feature, 2026-09-25: connected accounts. Any provider (google, microsoft, icloud, caldav, ...), any number per
-- user, each usable for one or more capabilities (calendar now; mail etc. later). Replaces calendar_connections (one
-- Google account per user: connecting a second account overwrote the first). calendar_connections is kept, unused,
-- for rollback.
CREATE TABLE IF NOT EXISTS connected_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    account TEXT NOT NULL,
    label TEXT,
    capabilities TEXT[] NOT NULL DEFAULT '{}',
    default_for TEXT[] NOT NULL DEFAULT '{}',
    encrypted_token TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (user_id, provider, account)
);

CREATE INDEX IF NOT EXISTS idx_connected_accounts_user ON connected_accounts(user_id);

DROP TRIGGER IF EXISTS update_connected_accounts_updated_at ON connected_accounts;
CREATE TRIGGER update_connected_accounts_updated_at
    BEFORE UPDATE ON connected_accounts
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

ALTER TABLE connected_accounts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Service role full access connected_accounts" ON connected_accounts;
CREATE POLICY "Service role full access connected_accounts"
    ON connected_accounts FOR ALL TO service_role USING (true);

-- The existing Google calendar connections move over, as each user's default calendar account.
INSERT INTO connected_accounts (user_id, provider, account, capabilities, default_for, encrypted_token, is_active, created_at)
SELECT user_id, 'google', email, '{calendar}', '{calendar}', encrypted_token, is_active, created_at
FROM calendar_connections
ON CONFLICT (user_id, provider, account) DO NOTHING;
