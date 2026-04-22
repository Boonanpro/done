-- video_generation: Veo 3.1 Fast で生成した動画の履歴
-- 生成物は Supabase Storage bucket 'generated-videos' に保存される。

CREATE TABLE IF NOT EXISTS generated_videos (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    project_id UUID,
    message_id UUID,
    prompt TEXT NOT NULL,
    url TEXT NOT NULL,
    storage_path TEXT,
    model TEXT DEFAULT 'veo-3.1-fast-generate-preview',
    kind TEXT NOT NULL DEFAULT 'text-to-video',
    reference_url TEXT,
    mime_type TEXT DEFAULT 'video/mp4',
    duration_seconds INT,
    aspect_ratio TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by UUID
);

CREATE INDEX IF NOT EXISTS idx_generated_videos_project
    ON generated_videos(project_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_generated_videos_message
    ON generated_videos(message_id);

ALTER TABLE generated_videos ENABLE ROW LEVEL SECURITY;

CREATE POLICY "generated_videos_owner" ON generated_videos
    FOR ALL USING (created_by = auth.uid());
