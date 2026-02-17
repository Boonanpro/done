-- Note投稿スケジューラー
-- 指定日時に自動投稿するためのスケジュール管理テーブル

CREATE TABLE IF NOT EXISTS note_schedules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    draft_id UUID NOT NULL REFERENCES note_drafts(id) ON DELETE CASCADE,
    user_id UUID NOT NULL,
    scheduled_at TIMESTAMP WITH TIME ZONE NOT NULL,
    status VARCHAR(50) DEFAULT 'scheduled' CHECK (status IN ('scheduled', 'publishing', 'published', 'failed', 'cancelled')),
    article_type VARCHAR(10) DEFAULT 'free' CHECK (article_type IN ('free', 'paid')),
    price INTEGER,
    error_message TEXT,
    published_url TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_note_schedules_user_id ON note_schedules(user_id);
CREATE INDEX IF NOT EXISTS idx_note_schedules_status ON note_schedules(status);
CREATE INDEX IF NOT EXISTS idx_note_schedules_scheduled_at ON note_schedules(scheduled_at);
CREATE INDEX IF NOT EXISTS idx_note_schedules_draft_id ON note_schedules(draft_id);

-- RLS
ALTER TABLE note_schedules ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own schedules" ON note_schedules
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can create own schedules" ON note_schedules
    FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own schedules" ON note_schedules
    FOR UPDATE USING (auth.uid() = user_id);

CREATE POLICY "Users can delete own schedules" ON note_schedules
    FOR DELETE USING (auth.uid() = user_id);

-- Service role full access
CREATE POLICY "Service role full access on schedules" ON note_schedules
    FOR ALL USING (auth.role() = 'service_role');
