-- 057_chat_artifact_room_scope.sql
--
-- chat_artifact のスコープを project_id から room_id (= chat_rooms.id) に切り替える。
--
-- 背景:
--   いまは project_id で一覧を引いているため、同一プロジェクトに属する複数のチャットが
--   同じ成果物タブを共有してしまう。あるチャットでダンが artifacts/<slug>/ 配下のファイル
--   を編集すると、別の関係ないチャットの成果物タブにもその成果物が出現する
--   ("kittoku" が salonboard チャットの成果物タブに出る) 問題が発生していた。
--
-- 設計:
--   - room_id NOT NULL を付与し、INSERT 時に必ず現在のチャット room_id を要求する。
--   - UNIQUE(room_id, slug) で同一チャット内の重複登録を DB レベルで防止。
--   - 既存行は message_id 経由で room_id を逆引きしてバックフィル。
--     逆引きできなかった行 (message_id NULL など) は削除する
--     (再編集すれば自動で再登録される)。

-- ============================================================
-- 1. room_id カラム追加 (一時的に NULLABLE)
-- ============================================================
ALTER TABLE chat_artifact
    ADD COLUMN IF NOT EXISTS room_id UUID REFERENCES chat_rooms(id) ON DELETE CASCADE;

-- ============================================================
-- 2. 既存行のバックフィル: message_id 経由で room_id を埋める
-- ============================================================
UPDATE chat_artifact AS ca
SET room_id = cm.room_id
FROM chat_messages AS cm
WHERE ca.message_id = cm.id
  AND ca.room_id IS NULL;

-- ============================================================
-- 3. バックフィルできなかった行は削除
--    (元のチャットを特定できない孤児データ。
--     ファイルを再編集すれば新スコープで再登録される)
-- ============================================================
DELETE FROM chat_artifact WHERE room_id IS NULL;

-- ============================================================
-- 4. NOT NULL 制約を付与 (以降、room_id 無しの INSERT は DB が拒否)
-- ============================================================
ALTER TABLE chat_artifact
    ALTER COLUMN room_id SET NOT NULL;

-- ============================================================
-- 5. インデックス & UNIQUE 制約
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_chat_artifact_room
    ON chat_artifact(room_id, created_at DESC);

-- 同一チャット内で同じ slug を二重登録できないようにする
-- (アプリ側の重複チェック忘れを DB レベルで保証する)
CREATE UNIQUE INDEX IF NOT EXISTS uniq_chat_artifact_room_slug
    ON chat_artifact(room_id, slug);
