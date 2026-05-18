-- Add delivery/handoff metadata for generated artifacts.
-- This lets DAN guide non-website artifacts through preview, limited sharing,
-- client handoff, and full production delivery without overloading publish_status.

ALTER TABLE chat_artifact
    ADD COLUMN IF NOT EXISTS delivery_status TEXT NOT NULL DEFAULT 'preview',
    ADD COLUMN IF NOT EXISTS delivery_mode TEXT NOT NULL DEFAULT 'preview',
    ADD COLUMN IF NOT EXISTS target_audience TEXT NOT NULL DEFAULT 'internal',
    ADD COLUMN IF NOT EXISTS requires_auth BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS payment_responsibility TEXT NOT NULL DEFAULT 'owner_pays',
    ADD COLUMN IF NOT EXISTS delivery_checklist JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS handoff_notes TEXT;

UPDATE chat_artifact
SET
    delivery_status = COALESCE(NULLIF(delivery_status, ''), 'preview'),
    delivery_mode = COALESCE(NULLIF(delivery_mode, ''), 'preview'),
    target_audience = COALESCE(NULLIF(target_audience, ''), 'internal'),
    payment_responsibility = COALESCE(NULLIF(payment_responsibility, ''), 'owner_pays'),
    delivery_checklist = COALESCE(delivery_checklist, '{}'::jsonb)
WHERE delivery_status IS NULL
   OR delivery_status = ''
   OR delivery_mode IS NULL
   OR delivery_mode = ''
   OR target_audience IS NULL
   OR target_audience = ''
   OR payment_responsibility IS NULL
   OR payment_responsibility = ''
   OR delivery_checklist IS NULL;

CREATE INDEX IF NOT EXISTS idx_chat_artifact_delivery_status
    ON chat_artifact(delivery_status);

CREATE INDEX IF NOT EXISTS idx_chat_artifact_delivery_mode
    ON chat_artifact(delivery_mode);
