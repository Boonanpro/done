-- ============================================================
-- Document Management System (Dan版Notion)
-- ============================================================

-- 1. Register "資料管理" business in hub
INSERT INTO dashboard_businesses (name, slug, description, icon, status)
VALUES ('資料管理', 'documents', '全ファイルの一元管理・自動分類・バージョン管理', 'file-stack', 'active')
ON CONFLICT (slug) DO NOTHING;

-- 2. document_categories (カテゴリ定義 — LLMが動的に追加・整理)
CREATE TABLE IF NOT EXISTS document_categories (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  name TEXT NOT NULL,
  slug TEXT NOT NULL UNIQUE,
  icon TEXT DEFAULT 'folder',
  parent_id UUID REFERENCES document_categories(id) ON DELETE SET NULL,
  description TEXT,
  sort_order INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT now() NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_doc_categories_parent ON document_categories(parent_id);
CREATE INDEX IF NOT EXISTS idx_doc_categories_slug ON document_categories(slug);
CREATE TRIGGER trg_doc_categories_updated_at BEFORE UPDATE ON document_categories
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- 3. documents (中心テーブル — Notionのページに相当)
CREATE TABLE IF NOT EXISTS documents (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  parent_id UUID REFERENCES documents(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  description TEXT,
  content TEXT,                -- Markdown本文 (Notionインポート対応)
  doc_type TEXT NOT NULL DEFAULT 'file'
    CHECK (doc_type IN ('folder', 'file', 'collection')),
  category_id UUID REFERENCES document_categories(id) ON DELETE SET NULL,
  icon TEXT,
  tags TEXT[] DEFAULT '{}',
  project_id UUID,             -- dx_projects等への任意リンク
  business_slug TEXT,           -- ビジネス横断の関連付け
  metadata JSONB DEFAULT '{}', -- 拡張用メタデータ
  sort_order INTEGER DEFAULT 0,
  is_starred BOOLEAN DEFAULT false,
  is_deleted BOOLEAN DEFAULT false, -- ソフトデリート
  deleted_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT now() NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_documents_parent ON documents(parent_id);
CREATE INDEX IF NOT EXISTS idx_documents_category ON documents(category_id);
CREATE INDEX IF NOT EXISTS idx_documents_tags ON documents USING GIN(tags);
CREATE INDEX IF NOT EXISTS idx_documents_type ON documents(doc_type);
CREATE INDEX IF NOT EXISTS idx_documents_deleted ON documents(is_deleted);
CREATE INDEX IF NOT EXISTS idx_documents_starred ON documents(is_starred) WHERE is_starred = true;
CREATE INDEX IF NOT EXISTS idx_documents_title_search ON documents USING GIN(to_tsvector('simple', title));
CREATE TRIGGER trg_documents_updated_at BEFORE UPDATE ON documents
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- 4. document_files (ファイル実体 — バージョン管理付き)
CREATE TABLE IF NOT EXISTS document_files (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  filename TEXT NOT NULL,       -- ストレージ上のファイル名 (UUID.ext)
  original_name TEXT NOT NULL,  -- 元のファイル名
  storage_path TEXT NOT NULL,   -- ローカルファイルパス
  file_url TEXT NOT NULL,       -- API経由のアクセスURL
  mime_type TEXT,
  file_size BIGINT DEFAULT 0,
  version INTEGER DEFAULT 1,
  is_current BOOLEAN DEFAULT true,
  thumbnail_path TEXT,          -- サムネイルのローカルパス
  checksum TEXT,                -- ファイルハッシュ (重複検出用)
  created_at TIMESTAMPTZ DEFAULT now() NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_doc_files_document ON document_files(document_id);
CREATE INDEX IF NOT EXISTS idx_doc_files_current ON document_files(document_id, is_current) WHERE is_current = true;
CREATE INDEX IF NOT EXISTS idx_doc_files_checksum ON document_files(checksum);

-- 5. document_relations (ドキュメント間のリンク — Notionのrelation相当)
CREATE TABLE IF NOT EXISTS document_relations (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  source_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  target_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  relation_type TEXT DEFAULT 'related'
    CHECK (relation_type IN ('related', 'parent', 'reference', 'version_of')),
  created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
  UNIQUE(source_id, target_id, relation_type)
);
CREATE INDEX IF NOT EXISTS idx_doc_relations_source ON document_relations(source_id);
CREATE INDEX IF NOT EXISTS idx_doc_relations_target ON document_relations(target_id);

-- 6. document_shares (共有リンク — 将来の外部共有用)
CREATE TABLE IF NOT EXISTS document_shares (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  share_token TEXT NOT NULL UNIQUE,
  permission TEXT DEFAULT 'view'
    CHECK (permission IN ('view', 'edit')),
  expires_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now() NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_doc_shares_token ON document_shares(share_token);
CREATE INDEX IF NOT EXISTS idx_doc_shares_document ON document_shares(document_id);
