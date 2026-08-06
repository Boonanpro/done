-- OTP: リンク形式のワンタイム認証に対応（既存 otp 機能の拡張）
-- 一部のサービス（Instagram のパスワードリセット等）は6桁コードではなく
-- タップ用のワンタイムURLをSMS/メールで送ってくる。数字コードしか保存できず
-- 取りこぼしていたため、リンクも同じ経路で保存できるようにする。

ALTER TABLE otp_extractions ADD COLUMN IF NOT EXISTS link_url TEXT;

-- リンクのみのメッセージはコードが存在しないので NOT NULL を外す
ALTER TABLE otp_extractions ALTER COLUMN otp_code DROP NOT NULL;

-- コードとリンクの少なくとも一方は必ず入っていること
ALTER TABLE otp_extractions DROP CONSTRAINT IF EXISTS otp_extractions_code_or_link;
ALTER TABLE otp_extractions ADD CONSTRAINT otp_extractions_code_or_link
    CHECK (otp_code IS NOT NULL OR link_url IS NOT NULL);

CREATE INDEX IF NOT EXISTS idx_otp_extractions_link
    ON otp_extractions(user_id, extracted_at DESC)
    WHERE link_url IS NOT NULL;
