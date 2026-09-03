-- One verified registrant profile per DAN owner.  The complete contact is
-- encrypted; the public UI/API may expose only the masked label.
CREATE TABLE IF NOT EXISTS domain_registrant_profile (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    encrypted_contact TEXT NOT NULL,
    masked_label TEXT NOT NULL,
    source_domain TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

ALTER TABLE domain_registrant_profile ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own domain registrant profile"
    ON domain_registrant_profile FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Service role manages domain registrant profiles"
    ON domain_registrant_profile FOR ALL TO service_role
    USING (true) WITH CHECK (true);

DROP TRIGGER IF EXISTS update_domain_registrant_profile_updated_at ON domain_registrant_profile;
CREATE TRIGGER update_domain_registrant_profile_updated_at
    BEFORE UPDATE ON domain_registrant_profile
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
