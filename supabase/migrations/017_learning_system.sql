-- Learning System: スキル最適化のための学習基盤
-- アクション単位の実行記録とパターンから学習したルールを管理

-- ============================================
-- 学習イベント（アクション単位の実行記録）
-- ============================================
CREATE TABLE IF NOT EXISTS learning_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    session_id TEXT NOT NULL,              -- AgentRunner のセッションID
    browser_session_id TEXT,               -- VisualAgent のセッションID

    -- アクション情報
    site TEXT,                             -- ドメイン（amazon.co.jp 等）
    skill_name TEXT,                       -- スキル名（amazon 等）
    action_name TEXT NOT NULL,             -- アクション名（add-to-cart 等）
    action_params JSONB DEFAULT '{}',      -- アクションのパラメータ

    -- 結果
    technical_success BOOLEAN NOT NULL,    -- 技術的に成功したか
    user_value_success BOOLEAN,            -- ユーザーにとって価値があったか（後で判定）
    user_value_evaluated_at TIMESTAMPTZ,   -- user_value_success を判定した時刻
    user_value_reason TEXT,                -- 判定理由

    -- コンテキスト（汎用的に様々な状態を記録）
    context JSONB DEFAULT '{}',
    -- 例:
    -- {
    --   "logged_in": true,
    --   "page_url": "https://...",
    --   "page_type": "product_detail",
    --   "cart_items": 3,
    --   "selected_items": ["item-1"],
    --   "form_filled": true,
    --   "previous_actions": ["search", "click"]
    -- }

    -- 期待と実際の結果
    expected_outcome JSONB,                -- 期待した結果
    actual_outcome JSONB,                  -- 実際の結果

    -- メタデータ
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_learning_events_session
    ON learning_events(session_id);
CREATE INDEX IF NOT EXISTS idx_learning_events_browser_session
    ON learning_events(browser_session_id);
CREATE INDEX IF NOT EXISTS idx_learning_events_site_action
    ON learning_events(site, action_name);
CREATE INDEX IF NOT EXISTS idx_learning_events_skill_action
    ON learning_events(skill_name, action_name);
CREATE INDEX IF NOT EXISTS idx_learning_events_user
    ON learning_events(user_id);
CREATE INDEX IF NOT EXISTS idx_learning_events_created
    ON learning_events(created_at DESC);

-- ============================================
-- 学習したルール
-- ============================================
CREATE TABLE IF NOT EXISTS learned_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- パターン種別（拡張可能）
    pattern_type TEXT NOT NULL,
    -- 'state_requirement'  : アクションに必要な状態
    -- 'action_sequence'    : アクションの順序（将来用）
    -- 'state_invalidation' : 状態を無効化するアクション（将来用）

    -- スコープ（どこで適用されるか）
    scope JSONB NOT NULL,
    -- 例:
    -- { "site": "amazon.co.jp", "action": "add-to-cart" }
    -- { "site_pattern": "*.rakuten.co.jp", "action": "add-to-cart" }
    -- { "action_category": "cart_operation" }

    -- 観察されたパターン
    observed_pattern JSONB NOT NULL,
    -- 例:
    -- {
    --   "condition": { "logged_in": false },
    --   "action": "add-to-cart",
    --   "outcome": { "later_state_mismatch": true, "cart_empty": true }
    -- }

    -- 推論されたルール
    inferred_rule JSONB NOT NULL,
    -- 例:
    -- { "requires_state": { "logged_in": true } }
    -- { "should_do_first": ["login"] }

    -- 信頼度と根拠
    confidence FLOAT DEFAULT 0.5,          -- 0.0 〜 1.0
    evidence_count INT DEFAULT 1,          -- 根拠となるイベント数
    last_evidence_at TIMESTAMPTZ,          -- 最後に根拠が追加された時刻

    -- ルールの状態
    is_active BOOLEAN DEFAULT TRUE,        -- 有効かどうか
    manually_verified BOOLEAN DEFAULT FALSE, -- 人間が確認したか

    -- メタデータ
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_learned_rules_pattern_type
    ON learned_rules(pattern_type);
CREATE INDEX IF NOT EXISTS idx_learned_rules_scope
    ON learned_rules USING GIN(scope);
CREATE INDEX IF NOT EXISTS idx_learned_rules_active
    ON learned_rules(is_active) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_learned_rules_confidence
    ON learned_rules(confidence DESC);

-- ============================================
-- イベント間のリンク（因果関係の記録、将来用）
-- ============================================
CREATE TABLE IF NOT EXISTS event_links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_event_id UUID REFERENCES learning_events(id) ON DELETE CASCADE,
    target_event_id UUID REFERENCES learning_events(id) ON DELETE CASCADE,

    link_type TEXT NOT NULL,
    -- 'caused_by'      : target が source の原因
    -- 'followed_by'    : source の後に target が発生
    -- 'invalidated_by' : target が source を無効化
    -- 'retry_of'       : target は source のリトライ

    confidence FLOAT DEFAULT 0.5,
    metadata JSONB DEFAULT '{}',

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_event_links_source
    ON event_links(source_event_id);
CREATE INDEX IF NOT EXISTS idx_event_links_target
    ON event_links(target_event_id);
CREATE INDEX IF NOT EXISTS idx_event_links_type
    ON event_links(link_type);

-- ============================================
-- 更新トリガー
-- ============================================
CREATE OR REPLACE FUNCTION update_learned_rules_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_learned_rules_updated ON learned_rules;
CREATE TRIGGER trigger_learned_rules_updated
    BEFORE UPDATE ON learned_rules
    FOR EACH ROW
    EXECUTE FUNCTION update_learned_rules_timestamp();
