-- 解約の申し出を、運営（人間）を介さずに進めるための台帳。
--
-- 【なぜ「ボタン1つで解約」にしないのか】
-- 打つ手間そのものが商品の一部。ボタンなら迷わず押せるが、
-- 文章を打って送るまでの数十秒で我に返る人がいる。そこを消してはいけない。
--
-- 【なぜ人間が出ないのか】
-- 鍵を外せるのが運営だけである以上、やめたい人は必ずここへ来る。
-- 運営が 1 人なら、契約者が増えた時点で深夜の依頼に潰れる。
-- 返せなければ「抜けられないアプリ」になり、即返せば商品が消える。
-- だから受付・会話・解除コードの発行までをこちら側で完結させる。
--
-- 【1 台につき 1 行】
-- 解約は同時に何本も走らない。やりとりの履歴は pornblocker_messages に残るので、
-- ここは「いま何合目か」だけを持つ。

CREATE TABLE IF NOT EXISTS pornblocker_cancellations (
    device_id           TEXT PRIMARY KEY,

    -- none      … 申し出ていない（引き止めに応じて撤回した場合もここへ戻す）
    -- requested … 申し出を受けた。返事待ち。
    -- released  … 解除コードを渡した。鍵は外れる。
    state               TEXT NOT NULL DEFAULT 'none'
                        CHECK (state IN ('none', 'requested', 'released')),

    -- 何回「やめたい」と言われたか。
    -- 1 回目は引き止める。2 回目は必ず通す。ここを人（や AI）の裁量にしない。
    -- 何度でも引き止める作りは、解約を著しく困難にする行為として問題になる。
    attempts            INT NOT NULL DEFAULT 0,

    -- 最初に申し出た時刻。滞留の検知に使う。
    first_requested_at  TIMESTAMPTZ,
    -- 直近の申し出。
    last_requested_at   TIMESTAMPTZ,

    -- 返事を出す時刻。ここが来るまで返さない。
    --
    -- 即答すると機械だと分かるだけでなく、衝動が冷める時間も奪う。
    -- 深夜の申し出は翌朝まで持ち越す。人が寝ている時間に返らないのは自然だし、
    -- 衝動が一番強い時間帯を、そのまま待ち時間に変えられる。
    reply_due_at        TIMESTAMPTZ,
    -- 期限が来たときに流す本文。申し出を受けた時点で作っておく。
    -- 期限の側で作ると、その瞬間に文章が作れなければ返事が出せなくなる。
    pending_reply       TEXT,
    -- pending_reply を流し終えた時刻。二重に流さないための印。
    replied_at          TIMESTAMPTZ,

    -- 渡した解除コードと、その計算に使った申請番号。
    -- 申請番号は端末が持っていて、解除するまで変わらない。
    released_request_id TEXT,
    released_code       TEXT,
    released_at         TIMESTAMPTZ,

    -- 課金を止めた時刻。
    --
    -- 申し出を受けた瞬間に止める。返事より先に止める。
    -- 「解約したいと言ったのに、返事が遅れて次の請求が来た」を構造から消すため。
    -- 金の心配が消えた状態のほうが、引き止めの言葉も届く。
    billing_stopped_at  TIMESTAMPTZ,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 期限が来た返事を拾うための索引。端末が来るたびに引く。
CREATE INDEX IF NOT EXISTS idx_pornblocker_cancel_due
    ON pornblocker_cancellations (reply_due_at)
    WHERE replied_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_pornblocker_cancel_state
    ON pornblocker_cancellations (state);
