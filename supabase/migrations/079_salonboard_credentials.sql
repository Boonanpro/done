-- salonboard_credentials に login_id_hash 列を追加する。
--
-- 目的: 無料投稿枠(FREE_POST_LIMIT)を「端末」ではなく「サロンボードのログインID」に紐づける。
--
-- 経緯: 無料枠の判定は device_id (ブラウザのlocalStorage由来) 単位だったため、
-- ブラウザを変える・シークレットウィンドウを使うだけで無料枠が何度でも復活していた。
-- LPから誰でも「実際の1投稿を無料でプレゼント」する設計にするにあたり、
-- 同じサロンが何度も無料投稿できてしまう状態は塞いでおく必要がある。
--
-- encrypted_login_id は Fernet (非決定的暗号) なので、同じIDでも暗号文が毎回変わり
-- 照合に使えない。照合専用に SHA-256 ハッシュ列を持つ。
-- ハッシュなので、この列から元のログインIDは復元できない。

ALTER TABLE salonboard_credentials
    ADD COLUMN IF NOT EXISTS login_id_hash TEXT;

CREATE INDEX IF NOT EXISTS idx_salonboard_credentials_login_id_hash
    ON salonboard_credentials(login_id_hash);

COMMENT ON COLUMN salonboard_credentials.login_id_hash IS
    'サロンボードのログインIDのSHA-256ハッシュ(trim・小文字化後)。無料投稿枠の名寄せ専用。復号不可。';
