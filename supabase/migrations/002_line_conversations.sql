-- AI Secretary System - LINE Conversation Management Schema
-- This migration creates tables for LINE proxy communication feature

-- ==================== LINE Sessions Table ====================
-- Stores LINE login session information
CREATE TABLE IF NOT EXISTS line_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_data TEXT, -- Encrypted session/cookie data
    login_status VARCHAR(50) NOT NULL DEFAULT 'logged_out', -- logged_out, pending_qr, logged_in
    last_activity_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id)
);

-- Index for session lookup
CREATE INDEX IF NOT EXISTS idx_line_sessions_user_id ON line_sessions(user_id);

-- ==================== LINE Contacts Table ====================
-- Stores LINE friends/contacts information
CREATE TABLE IF NOT EXISTS line_contacts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    line_contact_id VARCHAR(255) NOT NULL, -- LINE internal identifier
    display_name VARCHAR(255),
    profile_image_url TEXT,
    contact_type VARCHAR(50) DEFAULT 'personal', -- personal, official_account, group
    is_friend BOOLEAN DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id, line_contact_id)
);

-- Indexes for contact lookup
CREATE INDEX IF NOT EXISTS idx_line_contacts_user_id ON line_contacts(user_id);
CREATE INDEX IF NOT EXISTS idx_line_contacts_display_name ON line_contacts(display_name);

-- ==================== LINE Conversations Table ====================
-- Stores conversation context between user and external party via LINE
CREATE TABLE IF NOT EXISTS line_conversations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    line_contact_id UUID NOT NULL REFERENCES line_contacts(id) ON DELETE CASCADE,
    original_task_id UUID REFERENCES tasks(id) ON DELETE SET NULL, -- The task that initiated this conversation
    
    -- Conversation context (AI-generated)
    original_wish TEXT, -- User's original request that started this conversation
    context_summary TEXT, -- AI-generated summary of conversation so far
    
    -- Status tracking
    status VARCHAR(50) NOT NULL DEFAULT 'active',
    -- active: Conversation ongoing
    -- waiting_user: Waiting for user input/decision
    -- waiting_reply: Waiting for external party's reply
    -- resolved: Conversation completed successfully
    -- closed: Conversation closed (manually or auto)
    
    last_message_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for conversation queries
CREATE INDEX IF NOT EXISTS idx_line_conversations_user_id ON line_conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_line_conversations_status ON line_conversations(status);
CREATE INDEX IF NOT EXISTS idx_line_conversations_last_message ON line_conversations(last_message_at DESC);

-- ==================== LINE Messages Table ====================
-- Stores individual messages in LINE conversations
CREATE TABLE IF NOT EXISTS line_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id UUID NOT NULL REFERENCES line_conversations(id) ON DELETE CASCADE,
    
    -- Message content
    direction VARCHAR(20) NOT NULL, -- sent, received
    content TEXT NOT NULL,
    message_type VARCHAR(50) DEFAULT 'text', -- text, image, sticker, file, etc.
    
    -- AI processing
    ai_summary TEXT, -- AI-generated summary of this message
    ai_intent VARCHAR(100), -- AI-detected intent (question, confirmation, information, etc.)
    ai_action_taken VARCHAR(50), -- reported_to_user, auto_replied, pending, ignored
    ai_action_detail TEXT, -- Details of action taken (e.g., auto-reply content)
    
    -- Metadata
    line_message_id VARCHAR(255), -- Original LINE message ID if available
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for message queries
CREATE INDEX IF NOT EXISTS idx_line_messages_conversation_id ON line_messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_line_messages_direction ON line_messages(direction);
CREATE INDEX IF NOT EXISTS idx_line_messages_created_at ON line_messages(created_at);

-- ==================== LINE Auto-Reply Rules Table ====================
-- Stores rules for autonomous replies (configurable by user)
CREATE TABLE IF NOT EXISTS line_auto_reply_rules (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    rule_type VARCHAR(50) NOT NULL, -- clarification, acknowledgment, escalation
    trigger_pattern TEXT, -- Pattern or description of when to trigger
    response_template TEXT, -- Template for auto-reply
    is_enabled BOOLEAN DEFAULT true,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Index for rule lookup
CREATE INDEX IF NOT EXISTS idx_line_auto_reply_rules_user_id ON line_auto_reply_rules(user_id);

-- ==================== Triggers ====================
-- Apply updated_at triggers to new tables

CREATE TRIGGER update_line_sessions_updated_at
    BEFORE UPDATE ON line_sessions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_line_contacts_updated_at
    BEFORE UPDATE ON line_contacts
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_line_conversations_updated_at
    BEFORE UPDATE ON line_conversations
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_line_auto_reply_rules_updated_at
    BEFORE UPDATE ON line_auto_reply_rules
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ==================== Row Level Security ====================
-- Enable RLS on new tables
ALTER TABLE line_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE line_contacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE line_conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE line_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE line_auto_reply_rules ENABLE ROW LEVEL SECURITY;

-- Policies for authenticated users
CREATE POLICY "Users can manage own LINE sessions"
    ON line_sessions FOR ALL
    USING (auth.uid() = user_id);

CREATE POLICY "Users can manage own LINE contacts"
    ON line_contacts FOR ALL
    USING (auth.uid() = user_id);

CREATE POLICY "Users can manage own LINE conversations"
    ON line_conversations FOR ALL
    USING (auth.uid() = user_id);

CREATE POLICY "Users can view own LINE messages"
    ON line_messages FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM line_conversations
            WHERE line_conversations.id = line_messages.conversation_id
            AND line_conversations.user_id = auth.uid()
        )
    );

CREATE POLICY "Users can insert LINE messages"
    ON line_messages FOR INSERT
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM line_conversations
            WHERE line_conversations.id = line_messages.conversation_id
            AND line_conversations.user_id = auth.uid()
        )
    );

CREATE POLICY "Users can manage own auto-reply rules"
    ON line_auto_reply_rules FOR ALL
    USING (auth.uid() = user_id);

-- Service role bypass policies
CREATE POLICY "Service role full access line_sessions"
    ON line_sessions FOR ALL
    TO service_role
    USING (true);

CREATE POLICY "Service role full access line_contacts"
    ON line_contacts FOR ALL
    TO service_role
    USING (true);

CREATE POLICY "Service role full access line_conversations"
    ON line_conversations FOR ALL
    TO service_role
    USING (true);

CREATE POLICY "Service role full access line_messages"
    ON line_messages FOR ALL
    TO service_role
    USING (true);

CREATE POLICY "Service role full access line_auto_reply_rules"
    ON line_auto_reply_rules FOR ALL
    TO service_role
    USING (true);
