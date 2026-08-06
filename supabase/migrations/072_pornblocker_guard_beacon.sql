-- ポルノブロッカー: 端末の「守りが立っているか」を運営側で見えるようにする。
--
-- 【なぜ要るのか】
-- 遮断の精度をいくら上げても、遮断そのものが止まっていれば意味が無い。
-- 実際に一度そうなった。アプリを入れ直したときユーザー補助の許可が外れ、
-- 画面には「稼働中」と出たまま、X の公式アプリが素通しになっていた。
-- 端末の中だけで警告しても、警告を見ない人（＝自分で外した人）には届かない。
--
-- Android の作り上、「絶対に破れない」は作れない。
-- だから「破ったら必ず分かる」でふさぐ。その受け皿がこの 2 つのテーブル。
--
-- 【入れないもの】
-- 見たサイト・検索語・止めた画像は一切保存しない。守りが立っているかだけを持つ。
-- ここを越えると、守るための道具が覗くための道具になる。

-- 雛形で作られた空のテーブルは使わない。
DROP TABLE IF EXISTS pornblocker_guard_beacon CASCADE;
DROP FUNCTION IF EXISTS update_pornblocker_guard_beacon_updated_at() CASCADE;

-- 端末ごとの最新の状態。一覧はこれを見るだけで描ける。
CREATE TABLE IF NOT EXISTS pornblocker_devices (
    device_id       TEXT PRIMARY KEY,
    -- 運営が付ける呼び名（契約者名など）。端末側からは送られてこない。
    label           TEXT,
    -- 守りが外れたときや解除申請のときの連絡先。契約時に運営が入れる。
    contact         TEXT,

    first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- 端末が申告した時刻。端末の時計はずれることがあるので受信時刻と分けて持つ。
    reported_at     TIMESTAMPTZ,

    protected       BOOLEAN NOT NULL DEFAULT FALSE,
    guard           BOOLEAN NOT NULL DEFAULT FALSE,
    overlay         BOOLEAN NOT NULL DEFAULT FALSE,
    vpn             BOOLEAN NOT NULL DEFAULT FALSE,
    admin           BOOLEAN NOT NULL DEFAULT FALSE,
    notifications   BOOLEAN NOT NULL DEFAULT FALSE,
    locked          BOOLEAN NOT NULL DEFAULT FALSE,
    safe_mode       BOOLEAN NOT NULL DEFAULT FALSE,

    app_version     TEXT,
    model           TEXT,
    android         TEXT,

    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 状態が変わった履歴。「いつ外れて、いつ戻ったか」を後から追うため。
-- 最新だけ持っていると、外して見て戻した往復が消える。そこが一番見たい情報になる。
CREATE TABLE IF NOT EXISTS pornblocker_events (
    id              BIGSERIAL PRIMARY KEY,
    device_id       TEXT NOT NULL,
    reported_at     TIMESTAMPTZ,
    received_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    protected       BOOLEAN NOT NULL DEFAULT FALSE,
    guard           BOOLEAN NOT NULL DEFAULT FALSE,
    overlay         BOOLEAN NOT NULL DEFAULT FALSE,
    vpn             BOOLEAN NOT NULL DEFAULT FALSE,
    admin           BOOLEAN NOT NULL DEFAULT FALSE,
    notifications   BOOLEAN NOT NULL DEFAULT FALSE,
    locked          BOOLEAN NOT NULL DEFAULT FALSE,
    safe_mode       BOOLEAN NOT NULL DEFAULT FALSE,

    app_version     TEXT,
    model           TEXT,
    android         TEXT
);

CREATE INDEX IF NOT EXISTS idx_pornblocker_events_device
    ON pornblocker_events (device_id, received_at DESC);

-- 消息不明（連絡が途絶えた端末）を探す一覧で使う。
CREATE INDEX IF NOT EXISTS idx_pornblocker_devices_last_seen
    ON pornblocker_devices (last_seen_at DESC);

-- 端末からも運営画面からも、このテーブルは直接触らせない。
-- 受け口（バックエンド）が service-role キーで読み書きする。
ALTER TABLE pornblocker_devices ENABLE ROW LEVEL SECURITY;
ALTER TABLE pornblocker_events  ENABLE ROW LEVEL SECURITY;
