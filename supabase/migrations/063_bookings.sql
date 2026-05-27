-- 予約ブロック: クライアントHP/ツールに埋め込む「予約・カレンダー」機能ブロックの土台。
-- (create_feature 雛形を実装で置き換え)
--
-- 1テーブルで業種をまたいで使えるよう汎用設計（美容室=メニュー+指名スタッフ、
-- 飲食=人数、クリニック=メニュー等は任意カラムで吸収）。どの店舗/サイトの予約かは
-- artifact_slug で区別する。
--
-- backend (FastAPI) が service-role キーで読み書きする内部テーブル。エンドユーザー
-- (来店客) はアカウントを持たない (MVP) ため client-direct アクセス無し = RLS 不要
-- (既存の salonboard_credentials / pending_followups と同方針)。営業時間・枠長・定員・
-- メニュー/スタッフ一覧は <BookingCalendar> の props で持ち、空き枠は「その日の予約」を
-- 引いてフロントで算出する（API はステートレスに保つ）。

CREATE TABLE IF NOT EXISTS bookings (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_slug  TEXT NOT NULL,                      -- どの店舗/サイトの予約か
    customer_name  TEXT NOT NULL,
    contact        TEXT NOT NULL,                      -- 電話 or メール
    service        TEXT,                               -- メニュー（任意）
    staff          TEXT,                               -- 指名スタッフ（任意）
    booking_date   DATE NOT NULL,                      -- 予約日
    start_time     TEXT NOT NULL,                      -- 開始時刻 'HH:MM'（枠）
    duration_min   INT  NOT NULL DEFAULT 60,           -- 所要分
    party_size     INT  NOT NULL DEFAULT 1,            -- 人数（飲食等）
    notes          TEXT,
    status         TEXT NOT NULL DEFAULT 'confirmed',  -- confirmed | pending | cancelled
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 空き枠算出 / 管理一覧: 店舗×日付×状態で引く。
CREATE INDEX IF NOT EXISTS idx_bookings_slug_date
    ON bookings(artifact_slug, booking_date, status);

-- 枠の満席判定: 同じ店舗・日・時刻・スタッフの予約を素早く数える。
CREATE INDEX IF NOT EXISTS idx_bookings_slot
    ON bookings(artifact_slug, booking_date, start_time, staff);
