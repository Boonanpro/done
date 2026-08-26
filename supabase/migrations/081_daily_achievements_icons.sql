-- 「今日やったこと」台帳に種別アイコンとイラスト状態を追加。
--   icon: 判定LLMが固定集合から選ぶ種別 (mail|publish|fix|build|research|money|doc|talk|design|video|login|other)
--   illustration_status: none | pending | done | failed  (画像本体は data/today_illust/<id>.png、APIで配信)

ALTER TABLE daily_achievements ADD COLUMN IF NOT EXISTS icon TEXT NOT NULL DEFAULT 'other';
ALTER TABLE daily_achievements ADD COLUMN IF NOT EXISTS illustration_status TEXT NOT NULL DEFAULT 'none';
ALTER TABLE daily_achievements ADD COLUMN IF NOT EXISTS illustration_at TIMESTAMPTZ;
