-- Fix issues table to allow null user_id
-- user_idがnullの場合でもイシューを記録できるようにする

-- user_idカラムをNULLABLEに変更
ALTER TABLE issues ALTER COLUMN user_id DROP NOT NULL;

-- issue_occurrencesテーブルのuser_idもNULLABLEに変更
ALTER TABLE issue_occurrences ALTER COLUMN user_id DROP NOT NULL;

-- RLSポリシーを更新: user_idがnullでも挿入可能にする
DROP POLICY IF EXISTS "Users can create their own issues" ON issues;
CREATE POLICY "Users can create their own issues"
    ON issues FOR INSERT
    WITH CHECK (auth.uid() = user_id OR user_id IS NULL);

DROP POLICY IF EXISTS "Users can create occurrence records" ON issue_occurrences;
CREATE POLICY "Users can create occurrence records"
    ON issue_occurrences FOR INSERT
    WITH CHECK (auth.uid() = user_id OR user_id IS NULL);
