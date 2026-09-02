-- 電管ナレッジ 質問・相談掲示板（artifact用データ置き場・参照用）
-- 適用は apply_sql 経由（supabase/migrations には置かない＝ダン本体機能ではないため）
-- 登録不要・名前＋本文で投稿、メールは任意（回答時の通知用、非公開）
-- アクセスは frontend の route handler（service_role）経由のみ。RLS有効＋ポリシー無し＝anonキーからは不可視。

create table if not exists denki_qa_question (
  id          uuid primary key default gen_random_uuid(),
  created_at  timestamptz not null default now(),
  author_name text not null,
  email       text,
  title       text not null,
  body        text not null,
  is_hidden   boolean not null default false
);

create table if not exists denki_qa_answer (
  id          uuid primary key default gen_random_uuid(),
  created_at  timestamptz not null default now(),
  question_id uuid not null references denki_qa_question(id) on delete cascade,
  author_name text not null,
  body        text not null,
  notified    boolean not null default false,
  is_hidden   boolean not null default false
);

create index if not exists idx_denki_qa_answer_question on denki_qa_answer(question_id);
create index if not exists idx_denki_qa_answer_unnotified on denki_qa_answer(notified) where notified = false;
create index if not exists idx_denki_qa_question_created on denki_qa_question(created_at desc);

alter table denki_qa_question enable row level security;
alter table denki_qa_answer   enable row level security;
