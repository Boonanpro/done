-- ポルノブロッカーの課金と連絡。
--
-- 【何にお金をもらうのか】
-- 遮断そのものは無料。お金をもらうのは「本人が自分で外せなくすること」に対して。
-- 自分で外せる鍵は、夜中に思い立てば 30 秒で外せる。外す手段をこちらが預かる、そこが商品。
--
-- 【個人を特定できるものを置かない】
-- 端末の呼び名（device_id）は端末が作った乱数。氏名もメールもここには持たない。
-- 支払いに要る情報は Stripe 側にあり、こちらは「生きているか」だけを見る。

-- 雛形が作った空のテーブルは使わない。中身が無いうちに落とす。
DROP TABLE IF EXISTS pornblocker_billing CASCADE;

CREATE TABLE IF NOT EXISTS pornblocker_subscriptions (
    device_id               TEXT PRIMARY KEY,
    -- Stripe 側の状態をそのまま入れる。こちらで意味を作り直さない。
    -- active / trialing / past_due / canceled / pending / none
    status                  TEXT NOT NULL DEFAULT 'none',
    stripe_customer_id      TEXT,
    stripe_subscription_id  TEXT,
    -- 支払いページを作った時点で残す。webhook が届かなかったときの手掛かり。
    checkout_session_id     TEXT,
    current_period_end      TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pornblocker_subs_status
    ON pornblocker_subscriptions (status);

-- 解約も問い合わせも、この 1 本のやりとりに集める。
--
-- 鍵を外せるのが運営だけである以上、やめたい人は必ずここへ来る。
-- 一方通行のフォームにすると送って終わりになり、話が途切れる。
CREATE TABLE IF NOT EXISTS pornblocker_messages (
    id          BIGSERIAL PRIMARY KEY,
    device_id   TEXT NOT NULL,
    -- user … 端末から / admin … 運営から
    sender      TEXT NOT NULL CHECK (sender IN ('user', 'admin')),
    text        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pornblocker_messages_device
    ON pornblocker_messages (device_id, created_at);
