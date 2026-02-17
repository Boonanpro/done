-- Notes System - note投稿管理基盤
-- 下書き → AI清書 → note投稿の全フローを管理

-- ==================== Note Drafts Table ====================
CREATE TABLE IF NOT EXISTS note_drafts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    title VARCHAR(500) NOT NULL,
    content TEXT NOT NULL,
    tags JSONB DEFAULT '[]',          -- ["AI活用", "プログラミング"] etc.
    status VARCHAR(50) NOT NULL DEFAULT 'draft',
        -- draft: 下書き
        -- polished: AI清書済み
        -- posted: noteに投稿済み
        -- published: noteで公開済み

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_note_drafts_user_id ON note_drafts(user_id);
CREATE INDEX IF NOT EXISTS idx_note_drafts_status ON note_drafts(status);
CREATE INDEX IF NOT EXISTS idx_note_drafts_user_status ON note_drafts(user_id, status);
CREATE INDEX IF NOT EXISTS idx_note_drafts_created_at ON note_drafts(created_at DESC);

-- Updated_at trigger
CREATE TRIGGER update_note_drafts_updated_at
    BEFORE UPDATE ON note_drafts
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ==================== Note Polished Table ====================
CREATE TABLE IF NOT EXISTS note_polished (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    draft_id UUID NOT NULL REFERENCES note_drafts(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    title VARCHAR(500) NOT NULL,
    tags JSONB DEFAULT '[]',
    full_text TEXT NOT NULL,           -- 清書後の本文全体
    hook TEXT,                         -- 導入（フック）部分
    summary TEXT,                      -- 要約・説明

    status VARCHAR(50) NOT NULL DEFAULT 'polished',
    polished_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_note_polished_draft_id ON note_polished(draft_id);
CREATE INDEX IF NOT EXISTS idx_note_polished_user_id ON note_polished(user_id);

-- ==================== Note Posts Table ====================
CREATE TABLE IF NOT EXISTS note_posts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    draft_id UUID NOT NULL REFERENCES note_drafts(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    note_url TEXT,                     -- noteの記事URL
    title VARCHAR(500) NOT NULL,
    published BOOLEAN NOT NULL DEFAULT false,
    status VARCHAR(50) NOT NULL DEFAULT 'draft_on_note',
        -- draft_on_note: noteに下書き保存
        -- published: noteで公開済み

    posted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_note_posts_draft_id ON note_posts(draft_id);
CREATE INDEX IF NOT EXISTS idx_note_posts_user_id ON note_posts(user_id);
CREATE INDEX IF NOT EXISTS idx_note_posts_status ON note_posts(status);

-- ==================== RLS Policies ====================
ALTER TABLE note_drafts ENABLE ROW LEVEL SECURITY;
ALTER TABLE note_polished ENABLE ROW LEVEL SECURITY;
ALTER TABLE note_posts ENABLE ROW LEVEL SECURITY;

-- note_drafts
CREATE POLICY "Users can view own note_drafts"
    ON note_drafts FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Service role full access note_drafts"
    ON note_drafts FOR ALL
    TO service_role
    USING (true);

-- note_polished
CREATE POLICY "Users can view own note_polished"
    ON note_polished FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Service role full access note_polished"
    ON note_polished FOR ALL
    TO service_role
    USING (true);

-- note_posts
CREATE POLICY "Users can view own note_posts"
    ON note_posts FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Service role full access note_posts"
    ON note_posts FOR ALL
    TO service_role
    USING (true);
