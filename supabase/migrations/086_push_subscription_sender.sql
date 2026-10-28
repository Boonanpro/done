-- 通知の購読に購読者の身元を持たせる（2026-10-28）
-- ゲストが複数いる窓口で、ゲストの発言を他のゲストにも届け、本人だけを除くため。
-- 従来の行は NULL のままでよい（種類で判定する従来の動きに戻る）。
ALTER TABLE push_subscriptions ADD COLUMN IF NOT EXISTS sender_id TEXT;
