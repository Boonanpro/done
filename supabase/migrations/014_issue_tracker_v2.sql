-- Issue Tracker v2: スキル化のためのイシュー拡張
-- screenshots, html_snapshot, page_url, fallback_action を追加

-- issues テーブルに新カラム追加
ALTER TABLE issues ADD COLUMN IF NOT EXISTS screenshots JSONB DEFAULT '[]';
ALTER TABLE issues ADD COLUMN IF NOT EXISTS html_snapshot_path TEXT;
ALTER TABLE issues ADD COLUMN IF NOT EXISTS page_url TEXT;
ALTER TABLE issues ADD COLUMN IF NOT EXISTS fallback_action TEXT;

-- issue_occurrences テーブルにも同じカラム追加（各発生時の状態を記録）
ALTER TABLE issue_occurrences ADD COLUMN IF NOT EXISTS screenshots JSONB DEFAULT '[]';
ALTER TABLE issue_occurrences ADD COLUMN IF NOT EXISTS html_snapshot_path TEXT;
ALTER TABLE issue_occurrences ADD COLUMN IF NOT EXISTS page_url TEXT;

-- コメント追加
COMMENT ON COLUMN issues.screenshots IS 'スクリーンショットファイルパスの配列 ["sessions/xxx/screenshots/step_7.png"]';
COMMENT ON COLUMN issues.html_snapshot_path IS 'HTMLスナップショットのファイルパス';
COMMENT ON COLUMN issues.page_url IS 'エラー発生時のページURL（再現用）';
COMMENT ON COLUMN issues.fallback_action IS 'フォールバックアクションの説明（例: "Amazonに切り替えて完遂"）';

COMMENT ON COLUMN issue_occurrences.screenshots IS 'この発生時のスクリーンショット';
COMMENT ON COLUMN issue_occurrences.html_snapshot_path IS 'この発生時のHTMLスナップショット';
COMMENT ON COLUMN issue_occurrences.page_url IS 'この発生時のページURL';

-- page_url での検索用インデックス（同じページでのエラー検索）
CREATE INDEX IF NOT EXISTS idx_issues_page_url ON issues(page_url) WHERE page_url IS NOT NULL;

-- issue_typeの新しい値 'user_input_required' を許容（ENUMではなくTEXTなので制約なし）
-- Python側で IssueType.USER_INPUT_REQUIRED を追加
