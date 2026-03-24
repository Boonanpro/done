-- Studio Schema - AI Vlog Production Dashboard
-- Run this in Supabase SQL editor

-- ==================== Studio Channels ====================
CREATE TABLE IF NOT EXISTS studio_channels (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    concept TEXT,
    character_name VARCHAR(100),
    character_description TEXT,
    character_image_url TEXT,
    youtube_channel_id VARCHAR(100),
    youtube_channel_url TEXT,
    status VARCHAR(50) DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_studio_channels_user_id ON studio_channels(user_id);

-- ==================== Studio Episodes ====================
CREATE TABLE IF NOT EXISTS studio_episodes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    channel_id UUID NOT NULL REFERENCES studio_channels(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    episode_number INTEGER,
    title VARCHAR(300) NOT NULL,
    description TEXT,
    script TEXT,
    script_messages JSONB DEFAULT '[]'::jsonb,
    status VARCHAR(50) DEFAULT 'draft',
    youtube_video_id VARCHAR(100),
    youtube_url TEXT,
    scheduled_at TIMESTAMP WITH TIME ZONE,
    published_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_studio_episodes_channel_id ON studio_episodes(channel_id);
CREATE INDEX IF NOT EXISTS idx_studio_episodes_user_id ON studio_episodes(user_id);

-- ==================== Studio Voice Tracks ====================
CREATE TABLE IF NOT EXISTS studio_voice_tracks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    episode_id UUID NOT NULL REFERENCES studio_episodes(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    label VARCHAR(200),
    text_content TEXT NOT NULL,
    voice_id VARCHAR(100),
    model_id VARCHAR(100),
    file_url TEXT,
    duration_seconds FLOAT,
    status VARCHAR(50) DEFAULT 'pending',
    elevenlabs_history_id VARCHAR(200),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_studio_voice_tracks_episode_id ON studio_voice_tracks(episode_id);

-- ==================== Studio Video Clips ====================
CREATE TABLE IF NOT EXISTS studio_video_clips (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    episode_id UUID NOT NULL REFERENCES studio_episodes(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    label VARCHAR(200),
    prompt TEXT NOT NULL,
    negative_prompt TEXT,
    duration INTEGER DEFAULT 5,
    mode VARCHAR(50) DEFAULT 'std',
    file_url TEXT,
    thumbnail_url TEXT,
    kling_task_id VARCHAR(200),
    kling_status VARCHAR(50) DEFAULT 'pending',
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_studio_video_clips_episode_id ON studio_video_clips(episode_id);
