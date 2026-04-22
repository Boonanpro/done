-- image_generation: Nano Banana で生成した画像の履歴
-- 生成物は Supabase Storage bucket 'generated-images' に保存される。この表はメタ履歴

CREATE TABLE IF NOT EXISTS generated_images (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    project_id UUID,
    message_id UUID,
    prompt TEXT NOT NULL,
    url TEXT NOT NULL,
    storage_path TEXT,
    model TEXT DEFAULT 'gemini-2.5-flash-image-preview',
    kind TEXT NOT NULL DEFAULT 'generate',
    reference_url TEXT,
    mime_type TEXT DEFAULT 'image/png',
    size TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by UUID
);

CREATE INDEX IF NOT EXISTS idx_generated_images_project
    ON generated_images(project_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_generated_images_message
    ON generated_images(message_id);

ALTER TABLE generated_images ENABLE ROW LEVEL SECURITY;

CREATE POLICY "generated_images_owner" ON generated_images
    FOR ALL USING (created_by = auth.uid());
