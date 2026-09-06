-- ポルノブロッカー: もう一つの領域（セキュアフォルダ）の有無と、運営への知らせの記録。
--
-- 【secure_space】
-- Galaxy のセキュアフォルダは端末の中の「別の携帯」で、こちらの遮断も見張りも効かない。
-- ふつうに入れたアプリの権限では消せないので、塞ぐのではなく運営に見えるようにする。
-- 端末が Health.State.secureSpace として送ってくる。
--
-- 【alert_state】
-- 「音沙汰が無い」「守りが外れた」を運営（みきさん）へ知らせたかどうかの記録。
-- ダン側の見回り（pornblocker_guard_beacon_service.watch_and_alert）が読み書きする。
-- ここに残しておかないと、ダンが再起動するたびに同じ知らせをもう一度送ってしまう。
--   例: {"silent": "2026-09-06T03:00:00+00:00", "unprotected": null, "secure_space": null}
--   値は「その状態で知らせた時刻」。null なら知らせていない（＝正常に戻っている）。

ALTER TABLE pornblocker_devices ADD COLUMN IF NOT EXISTS secure_space BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE pornblocker_events  ADD COLUMN IF NOT EXISTS secure_space BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE pornblocker_devices ADD COLUMN IF NOT EXISTS alert_state JSONB NOT NULL DEFAULT '{}'::jsonb;
