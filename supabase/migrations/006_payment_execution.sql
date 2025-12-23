-- Payment Execution - Database Schema
-- Phase 8: 支払い実行

-- ==================== Saved Bank Accounts Table ====================
-- 保存済み振込先
CREATE TABLE IF NOT EXISTS saved_bank_accounts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL,
    display_name VARCHAR(100) NOT NULL,           -- 表示名（例：「○○株式会社」）
    bank_name VARCHAR(100) NOT NULL,              -- 銀行名
    bank_code VARCHAR(4),                         -- 銀行コード（4桁）
    branch_name VARCHAR(100) NOT NULL,            -- 支店名
    branch_code VARCHAR(3),                       -- 支店コード（3桁）
    account_type VARCHAR(10) NOT NULL,            -- 普通/当座
    account_number VARCHAR(7) NOT NULL,           -- 口座番号（7桁）
    account_holder VARCHAR(100) NOT NULL,         -- 口座名義（カタカナ）
    is_verified BOOLEAN DEFAULT FALSE,            -- 検証済みフラグ
    last_used_at TIMESTAMP WITH TIME ZONE,        -- 最終使用日時
    use_count INTEGER DEFAULT 0,                  -- 使用回数
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_saved_bank_accounts_user_id ON saved_bank_accounts(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_saved_bank_accounts_unique 
    ON saved_bank_accounts(user_id, bank_code, branch_code, account_number);
CREATE INDEX IF NOT EXISTS idx_saved_bank_accounts_last_used ON saved_bank_accounts(user_id, last_used_at DESC);

-- ==================== Payment Execution Logs Table ====================
-- 支払い実行ログ
CREATE TABLE IF NOT EXISTS payment_execution_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    invoice_id UUID NOT NULL REFERENCES invoices(id),
    user_id UUID NOT NULL,
    execution_status VARCHAR(30) NOT NULL DEFAULT 'pending',  -- pending, executing, completed, failed
    current_step VARCHAR(50),
    steps_completed JSONB DEFAULT '[]'::jsonb,
    steps_remaining JSONB DEFAULT '[]'::jsonb,
    bank_type VARCHAR(50),                        -- simulation, sbi, mufg, etc.
    transaction_id VARCHAR(100),                  -- 振込完了時の取引ID
    transfer_amount INTEGER,                      -- 振込金額
    recipient_info JSONB,                         -- 振込先情報（実行時スナップショット）
    error_message TEXT,
    requires_otp BOOLEAN DEFAULT FALSE,
    otp_requested_at TIMESTAMP WITH TIME ZONE,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_payment_execution_logs_invoice_id ON payment_execution_logs(invoice_id);
CREATE INDEX IF NOT EXISTS idx_payment_execution_logs_user_id ON payment_execution_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_payment_execution_logs_status ON payment_execution_logs(execution_status);

-- ==================== User Bank Credentials Table ====================
-- ユーザーのネットバンキング認証情報（暗号化保存）
-- 既存のuser_credentialsを利用するが、bank固有のサービス名で保存
-- 例: service = "bank_sbi", "bank_mufg" など

-- ==================== Updated At Trigger ====================
CREATE TRIGGER update_saved_bank_accounts_updated_at
    BEFORE UPDATE ON saved_bank_accounts
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_payment_execution_logs_updated_at
    BEFORE UPDATE ON payment_execution_logs
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ==================== Row Level Security ====================
ALTER TABLE saved_bank_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE payment_execution_logs ENABLE ROW LEVEL SECURITY;

-- Service role bypass
CREATE POLICY "Service role full access saved_bank_accounts"
    ON saved_bank_accounts FOR ALL
    TO service_role
    USING (true);

CREATE POLICY "Service role full access payment_execution_logs"
    ON payment_execution_logs FOR ALL
    TO service_role
    USING (true);

-- User policies
CREATE POLICY "Users can manage own bank accounts"
    ON saved_bank_accounts
    FOR ALL
    USING (auth.uid()::text = user_id::text);

CREATE POLICY "Users can view own payment logs"
    ON payment_execution_logs
    FOR SELECT
    USING (auth.uid()::text = user_id::text);

-- ==================== Add payment fields to invoices ====================
-- invoicesテーブルに支払い実行関連のカラムを追加（存在しない場合）
DO $$
BEGIN
    -- execution_log_id カラム追加
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'invoices' AND column_name = 'execution_log_id'
    ) THEN
        ALTER TABLE invoices ADD COLUMN execution_log_id UUID REFERENCES payment_execution_logs(id);
    END IF;
    
    -- bank_type カラム追加
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'invoices' AND column_name = 'bank_type'
    ) THEN
        ALTER TABLE invoices ADD COLUMN bank_type VARCHAR(50);
    END IF;
END $$;

-- ==================== Comments ====================
COMMENT ON TABLE saved_bank_accounts IS '保存済み振込先情報';
COMMENT ON TABLE payment_execution_logs IS '支払い実行ログ';

COMMENT ON COLUMN saved_bank_accounts.display_name IS '表示名（会社名など）';
COMMENT ON COLUMN saved_bank_accounts.bank_code IS '銀行コード（4桁、例: 0005 = 三菱UFJ）';
COMMENT ON COLUMN saved_bank_accounts.branch_code IS '支店コード（3桁）';
COMMENT ON COLUMN saved_bank_accounts.account_type IS '口座種別: 普通, 当座';
COMMENT ON COLUMN saved_bank_accounts.account_holder IS '口座名義（全角カタカナ）';
COMMENT ON COLUMN saved_bank_accounts.is_verified IS '振込先として検証済みかどうか';

COMMENT ON COLUMN payment_execution_logs.bank_type IS '銀行タイプ: simulation, sbi, mufg, etc.';
COMMENT ON COLUMN payment_execution_logs.recipient_info IS '振込先情報のスナップショット（JSON）';

