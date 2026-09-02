-- 電管ナレッジ AI一次回答の知識基盤（artifact用データ置き場）
-- 適用は apply_sql 経由（supabase/migrations には置かない＝ダン本体機能ではないため）
-- ・denki_kb_doc   : ブログ本文（全文・上限なし）／YouTube字幕の原文
-- ・denki_kb_chunk : 検索用に分割した断片＋埋め込みベクトル（Gemini gemini-embedding-001, 768次元）
-- アクセスは frontend の route handler（service_role）経由のみ。RLS有効＋ポリシー無し＝anonキーからは不可視。

create extension if not exists vector;

create table if not exists denki_kb_doc (
  id           bigserial primary key,
  source_id    text not null,               -- 索引の source id（toaru-d, yt_yuji 等）
  source_name  text not null,
  kind         text not null,               -- 'blog' | 'youtube'
  url          text not null unique,
  title        text not null,
  published_on date,
  content      text not null,               -- 全文（切り詰めなし）
  char_count   integer not null default 0,
  content_hash text,                        -- 再取得時の差分判定
  fetched_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create index if not exists idx_denki_kb_doc_source on denki_kb_doc(source_id);
create index if not exists idx_denki_kb_doc_kind on denki_kb_doc(kind);

create table if not exists denki_kb_chunk (
  id          bigserial primary key,
  doc_id      bigint not null references denki_kb_doc(id) on delete cascade,
  chunk_index integer not null,
  content     text not null,
  embedding   vector(768),
  created_at  timestamptz not null default now(),
  unique (doc_id, chunk_index)
);

create index if not exists idx_denki_kb_chunk_doc on denki_kb_chunk(doc_id);
-- 近傍検索用。cosine距離。lists/m はデータ量に対して控えめな既定値。
create index if not exists idx_denki_kb_chunk_embedding
  on denki_kb_chunk using hnsw (embedding vector_cosine_ops);

alter table denki_kb_doc   enable row level security;
alter table denki_kb_chunk enable row level security;

-- 近傍検索RPC（service_role から呼ぶ）
create or replace function denki_kb_search(
  p_query_embedding vector(768),
  p_match_count     integer default 8,
  p_min_similarity  double precision default 0.0
)
returns table (
  chunk_id    bigint,
  doc_id      bigint,
  content     text,
  similarity  double precision,
  title       text,
  url         text,
  source_name text,
  kind        text,
  published_on date
)
language sql stable
as $$
  select c.id, d.id, c.content,
         1 - (c.embedding <=> p_query_embedding) as similarity,
         d.title, d.url, d.source_name, d.kind, d.published_on
  from denki_kb_chunk c
  join denki_kb_doc d on d.id = c.doc_id
  where c.embedding is not null
    and 1 - (c.embedding <=> p_query_embedding) >= p_min_similarity
  order by c.embedding <=> p_query_embedding
  limit p_match_count;
$$;

-- 掲示板側: AI一次回答をスレッドの回答として持つ
alter table denki_qa_answer add column if not exists is_ai boolean not null default false;
alter table denki_qa_answer add column if not exists citations jsonb;
