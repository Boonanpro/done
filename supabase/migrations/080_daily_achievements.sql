-- 「今日やったこと」台帳 (daily_achievements)
--
-- ダンの各部屋・開発CLI(claude code)・git・見張りの証拠を achievement_poller が
-- ほぼリアルタイムに読み、判定基準 (~/.dan/workspace/ACHIEVEMENT_RULES.md) に照らして
-- 「成果 (done)」「進行中 (in_progress)」を1日単位で記録する。
-- day は JST の日付。過去日は消さず、ページが「今日」だけを見せる = 0時でまっさら。
--
-- 内部 infra テーブル (RLS なし / service-role キー経由でバックエンドだけが書く)。

CREATE TABLE IF NOT EXISTS daily_achievements (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    day         DATE NOT NULL,                        -- JST 日付
    title       TEXT NOT NULL,                        -- 1行見出し (何を成し遂げたか)
    detail      TEXT,                                 -- 補足 (1〜2行)
    status      TEXT NOT NULL DEFAULT 'in_progress',  -- done | in_progress | dismissed
    tags        TEXT[] NOT NULL DEFAULT '{}',         -- 例: 未コミット, push待ち, 要再起動
    evidence    JSONB NOT NULL DEFAULT '[]',          -- [{kind, label, ref}] kind: commit|room|cli|watch|url|mail
    sources     TEXT[] NOT NULL DEFAULT '{}',         -- dan | cli | git | watch
    first_seen  TIMESTAMPTZ NOT NULL DEFAULT now(),
    done_at     TIMESTAMPTZ,                          -- status が done になった時刻
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_daily_achievements_day
    ON daily_achievements(day, status, first_seen);

-- ポーラーの読み取り位置 (どこまで証拠を読んだか)。key ごとに JSON で保持。
CREATE TABLE IF NOT EXISTS achievement_cursors (
    key         TEXT PRIMARY KEY,
    value       JSONB NOT NULL DEFAULT '{}',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
