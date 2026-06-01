-- Android APK direct SMS OTP forwarding.
-- Raw device tokens are stored only on-device; the server stores SHA-256 hashes.

CREATE TABLE IF NOT EXISTS apk_otp_devices (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL UNIQUE,
    device_name VARCHAR(120),
    token_hash VARCHAR(64) NOT NULL UNIQUE,
    is_active BOOLEAN DEFAULT TRUE,
    last_received_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_apk_otp_devices_token_hash
    ON apk_otp_devices(token_hash);

ALTER TABLE apk_otp_devices ENABLE ROW LEVEL SECURITY;

CREATE POLICY apk_otp_devices_user_policy ON apk_otp_devices
    FOR ALL
    USING (auth.uid() = user_id OR auth.role() = 'service_role');

COMMENT ON TABLE apk_otp_devices IS
    'Android APK installations allowed to forward SMS OTP messages directly';
