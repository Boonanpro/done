CREATE TABLE IF NOT EXISTS domain_setup_registrant (
    domain_setup_token TEXT PRIMARY KEY,
    encrypted_contact TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
ALTER TABLE domain_setup_registrant ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Service role manages domain setup registrants" ON domain_setup_registrant FOR ALL TO service_role USING (true) WITH CHECK (true);
DROP TRIGGER IF EXISTS update_domain_setup_registrant_updated_at ON domain_setup_registrant;
CREATE TRIGGER update_domain_setup_registrant_updated_at BEFORE UPDATE ON domain_setup_registrant FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
