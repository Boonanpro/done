-- Real schema for client_messaging feature.
-- (055_client_messaging.sql was a placeholder scaffold from create_feature.)
--
-- Goal: enable LINE-like friend-add UX where clients log into a PWA via magic
-- link and have a stable identity across sessions/devices, replacing the
-- ephemeral guest_token model from collab_invites for direct (1 owner +
-- 1 client) chats.

-- ==================== Drop unused scaffold ====================
DROP TRIGGER IF EXISTS client_messaging_updated_at ON client_messaging;
DROP FUNCTION IF EXISTS update_client_messaging_updated_at();
DROP TABLE IF EXISTS client_messaging;

-- ==================== Client Accounts ====================
CREATE TABLE IF NOT EXISTS client_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    display_name TEXT,
    avatar_url TEXT,
    locale TEXT DEFAULT 'ja',
    last_login_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (email)
);

CREATE INDEX IF NOT EXISTS idx_client_accounts_client ON client_accounts(client_id);
CREATE INDEX IF NOT EXISTS idx_client_accounts_email ON client_accounts(email);

CREATE OR REPLACE FUNCTION client_accounts_set_updated_at()
RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS client_accounts_updated_at ON client_accounts;
CREATE TRIGGER client_accounts_updated_at
    BEFORE UPDATE ON client_accounts
    FOR EACH ROW EXECUTE FUNCTION client_accounts_set_updated_at();

-- ==================== Magic Link Tokens ====================
CREATE TABLE IF NOT EXISTS client_magic_links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_account_id UUID NOT NULL REFERENCES client_accounts(id) ON DELETE CASCADE,
    token TEXT UNIQUE NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    request_ip TEXT,
    request_user_agent TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_client_magic_links_token ON client_magic_links(token);
CREATE INDEX IF NOT EXISTS idx_client_magic_links_account ON client_magic_links(client_account_id);
CREATE INDEX IF NOT EXISTS idx_client_magic_links_expires ON client_magic_links(expires_at) WHERE consumed_at IS NULL;

-- ==================== Client Sessions ====================
CREATE TABLE IF NOT EXISTS client_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_account_id UUID NOT NULL REFERENCES client_accounts(id) ON DELETE CASCADE,
    refresh_token_hash TEXT NOT NULL,
    user_agent TEXT,
    ip_address TEXT,
    last_active_at TIMESTAMPTZ DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_client_sessions_account ON client_sessions(client_account_id);
CREATE INDEX IF NOT EXISTS idx_client_sessions_token_hash ON client_sessions(refresh_token_hash);

-- ==================== Extend collab_rooms ====================
-- Add client_account_id + room_type so a collab_room can represent either:
--   - 'direct' room: 1 owner + 1 client_account (= persistent friend relationship)
--   - 'group' room: existing collab_invites guest-token style (unchanged)
ALTER TABLE collab_rooms
    ADD COLUMN IF NOT EXISTS client_account_id UUID REFERENCES client_accounts(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS room_type TEXT NOT NULL DEFAULT 'group';

CREATE UNIQUE INDEX IF NOT EXISTS uniq_collab_rooms_owner_client_direct
    ON collab_rooms(owner_id, client_account_id)
    WHERE room_type = 'direct' AND client_account_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_collab_rooms_client_account ON collab_rooms(client_account_id);

-- ==================== Extend collab_messages ====================
-- Track which client_account_id sent the message (when sender_type='client').
ALTER TABLE collab_messages
    ADD COLUMN IF NOT EXISTS client_account_id UUID REFERENCES client_accounts(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_collab_messages_client_account ON collab_messages(client_account_id);

-- ==================== Row Level Security ====================
ALTER TABLE client_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE client_magic_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE client_sessions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role full access client_accounts"
    ON client_accounts FOR ALL TO service_role USING (true);
CREATE POLICY "Service role full access client_magic_links"
    ON client_magic_links FOR ALL TO service_role USING (true);
CREATE POLICY "Service role full access client_sessions"
    ON client_sessions FOR ALL TO service_role USING (true);
