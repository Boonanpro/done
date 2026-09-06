-- artifact_documents: 成果物ページ（ロードマップ等）の「本文＋作業チェック」の正本。
--
-- 背景: 2026-09-05 ポルノブロッカー事業ロードマップ。チェック状態がブラウザ内
-- (localStorage) にしか無く、別端末で消える・ダンから見えない、という問題を解消する。
-- 本文は BlockNote (Notion 風エディタ) のブロック配列を JSONB でそのまま保持する。
-- ダンは API / scripts/artifact_doc.py で同じ JSON を読み書きする。
--
-- backend (FastAPI) が service-role キーで読み書きする内部テーブル。公開ページからの
-- 読み取りは slug だけで可能、書き込みは edit_key かオーナーのアクセストークンが要る。
-- 編集はページ側からの保存ごとに差分を pending_changes に積み、一定時間静かになったら
-- 部屋 (room_id) へ 1 通にまとめて通知する（ポーラーは app.services.artifact_documents_service）。
--
-- create_feature の雛形 (id/created_at/updated_at/created_by) は先に適用済みなので、
-- 追加カラムは ALTER TABLE ... ADD COLUMN IF NOT EXISTS で足す（再適用しても壊れない）。

CREATE TABLE IF NOT EXISTS artifact_documents (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_by UUID  -- users.id（auth.users ではない。雛形の FK は下で外す）
);

-- 雛形が張った auth.users への FK はこのアプリの users.id と合わないので外す
ALTER TABLE artifact_documents DROP CONSTRAINT IF EXISTS artifact_documents_created_by_fkey;

ALTER TABLE artifact_documents ADD COLUMN IF NOT EXISTS artifact_slug TEXT;                       -- どの成果物の本文か
ALTER TABLE artifact_documents ADD COLUMN IF NOT EXISTS room_id UUID;                             -- 編集通知を出す部屋
ALTER TABLE artifact_documents ADD COLUMN IF NOT EXISTS title TEXT NOT NULL DEFAULT '';
ALTER TABLE artifact_documents ADD COLUMN IF NOT EXISTS blocks JSONB NOT NULL DEFAULT '[]'::jsonb; -- BlockNote ブロック配列
ALTER TABLE artifact_documents ADD COLUMN IF NOT EXISTS version INT NOT NULL DEFAULT 1;           -- 保存ごとに +1
ALTER TABLE artifact_documents ADD COLUMN IF NOT EXISTS edit_key TEXT;                            -- 公開URLから編集するための鍵
ALTER TABLE artifact_documents ADD COLUMN IF NOT EXISTS last_editor TEXT;                         -- page | owner | dan
ALTER TABLE artifact_documents ADD COLUMN IF NOT EXISTS last_saved_at TIMESTAMPTZ;
ALTER TABLE artifact_documents ADD COLUMN IF NOT EXISTS pending_changes JSONB NOT NULL DEFAULT '{}'::jsonb; -- 未通知の差分 (block_id -> before/after)
ALTER TABLE artifact_documents ADD COLUMN IF NOT EXISTS pending_since TIMESTAMPTZ;
ALTER TABLE artifact_documents ADD COLUMN IF NOT EXISTS pending_from_version INT;                 -- 通知メッセージに載せる「v何から」

CREATE UNIQUE INDEX IF NOT EXISTS idx_artifact_documents_slug ON artifact_documents(artifact_slug);
CREATE INDEX IF NOT EXISTS idx_artifact_documents_pending ON artifact_documents(pending_since) WHERE pending_since IS NOT NULL;

-- 版履歴: 保存のたびに 1 行。ダンが「何がどう変わったか」を後から追える。
CREATE TABLE IF NOT EXISTS artifact_document_revisions (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES artifact_documents(id) ON DELETE CASCADE,
    version INT NOT NULL,
    editor TEXT,
    summary TEXT,
    blocks JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_artifact_document_revisions_doc
    ON artifact_document_revisions(document_id, version DESC);

-- RLS: backend は service-role なので影響しない。クライアント直アクセスは閉じておく。
ALTER TABLE artifact_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE artifact_document_revisions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "artifact_documents_owner" ON artifact_documents;
CREATE POLICY "artifact_documents_owner" ON artifact_documents
    FOR ALL USING (created_by = auth.uid());

-- updated_at の自動更新
CREATE OR REPLACE FUNCTION update_artifact_documents_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS artifact_documents_updated_at ON artifact_documents;
CREATE TRIGGER artifact_documents_updated_at
    BEFORE UPDATE ON artifact_documents
    FOR EACH ROW EXECUTE FUNCTION update_artifact_documents_updated_at();
