-- ============================================================
-- 035: documents.content を TEXT → JSONB に変更
-- BlockNoteのブロック構造をJSON配列で格納する
-- ============================================================

-- 1. content列の型をJSONBに変更（既存データなし前提）
ALTER TABLE documents
  ALTER COLUMN content TYPE JSONB USING COALESCE(content::JSONB, '[]'::JSONB),
  ALTER COLUMN content SET DEFAULT '[]'::JSONB;

-- 2. content内テキスト検索用のGINインデックス
--    JSONB内のテキストブロックからcontent[*].text を抽出して全文検索
CREATE OR REPLACE FUNCTION documents_content_text(content JSONB)
RETURNS TEXT
LANGUAGE sql IMMUTABLE AS $$
  SELECT string_agg(elem->>'text', ' ')
  FROM jsonb_array_elements(content) AS elem
  WHERE elem->>'text' IS NOT NULL;
$$;

CREATE INDEX IF NOT EXISTS idx_documents_content_text
  ON documents USING GIN(
    to_tsvector('simple', COALESCE(documents_content_text(content), ''))
  );

-- 3. 複合検索インデックス（title + content text）
CREATE INDEX IF NOT EXISTS idx_documents_fulltext
  ON documents USING GIN(
    to_tsvector('simple', title || ' ' || COALESCE(documents_content_text(content), ''))
  );
