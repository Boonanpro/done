-- Phase 2 Revision: User Table Unification
-- chat_users テーブルを廃止し、users テーブルに統合する
-- 
-- 背景:
-- - 全員がDoneユーザーであるという前提
-- - 1つのユーザーテーブルで全機能を管理
-- - chat_usersとusersの分離は不要
--
-- 実行日: 2024年12月26日
-- 状態: 適用済み

-- ==================== Step 1: users テーブル拡張 ====================

-- password_hash カラムを追加（チャット認証用）
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255);

-- avatar_url カラムを追加
ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url TEXT;

-- ==================== Step 2: chat_users から users へデータ移行 ====================

-- 既存のchat_usersデータをusersに移行（emailが重複しない場合のみ）
INSERT INTO users (id, email, password_hash, display_name, avatar_url, created_at, updated_at)
SELECT 
    cu.id, 
    cu.email, 
    cu.password_hash, 
    cu.display_name, 
    cu.avatar_url, 
    cu.created_at, 
    cu.updated_at
FROM chat_users cu
WHERE NOT EXISTS (
    SELECT 1 FROM users u WHERE u.email = cu.email
)
ON CONFLICT (id) DO NOTHING;

-- ==================== Step 3: データクリーンアップ ====================

-- users に存在しない参照を持つレコードを削除
DELETE FROM chat_invites WHERE creator_id NOT IN (SELECT id FROM users);
DELETE FROM chat_friendships WHERE user_id NOT IN (SELECT id FROM users) OR friend_id NOT IN (SELECT id FROM users);
DELETE FROM chat_room_members WHERE user_id NOT IN (SELECT id FROM users);
UPDATE chat_messages SET sender_id = NULL WHERE sender_id IS NOT NULL AND sender_id NOT IN (SELECT id FROM users);

-- ==================== Step 4: 外部キー参照の変更 ====================

-- chat_invites: creator_id を users に変更
ALTER TABLE chat_invites DROP CONSTRAINT IF EXISTS chat_invites_creator_id_fkey;
ALTER TABLE chat_invites ADD CONSTRAINT chat_invites_creator_id_fkey 
    FOREIGN KEY (creator_id) REFERENCES users(id) ON DELETE CASCADE;

-- chat_friendships: user_id, friend_id を users に変更
ALTER TABLE chat_friendships DROP CONSTRAINT IF EXISTS chat_friendships_user_id_fkey;
ALTER TABLE chat_friendships DROP CONSTRAINT IF EXISTS chat_friendships_friend_id_fkey;
ALTER TABLE chat_friendships ADD CONSTRAINT chat_friendships_user_id_fkey 
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE chat_friendships ADD CONSTRAINT chat_friendships_friend_id_fkey 
    FOREIGN KEY (friend_id) REFERENCES users(id) ON DELETE CASCADE;

-- chat_room_members: user_id を users に変更
ALTER TABLE chat_room_members DROP CONSTRAINT IF EXISTS chat_room_members_user_id_fkey;
ALTER TABLE chat_room_members ADD CONSTRAINT chat_room_members_user_id_fkey 
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;

-- chat_messages: sender_id を users に変更
ALTER TABLE chat_messages DROP CONSTRAINT IF EXISTS chat_messages_sender_id_fkey;
ALTER TABLE chat_messages ADD CONSTRAINT chat_messages_sender_id_fkey 
    FOREIGN KEY (sender_id) REFERENCES users(id) ON DELETE SET NULL;

-- ==================== Step 5: chat_users テーブル削除 ====================

DROP TABLE IF EXISTS chat_users CASCADE;

-- ==================== 完了 ====================
-- 
-- 変更後の users テーブル構造:
-- - id UUID
-- - email VARCHAR(255) UNIQUE
-- - password_hash VARCHAR(255)  ← 追加
-- - line_user_id VARCHAR(255)
-- - display_name VARCHAR(255)
-- - avatar_url TEXT  ← 追加
-- - created_at TIMESTAMP
-- - updated_at TIMESTAMP
