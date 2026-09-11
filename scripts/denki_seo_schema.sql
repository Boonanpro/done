-- 電気主任技術者応援サイト（denkiouen.com）検索対策の自動エンジン用テーブル
-- 適用は apply_sql 経由（supabase/migrations には置かない＝ダン本体機能ではないため）
-- アクセス:
--   ・書き込みは scripts/denki_seo_engines.py（service_role）だけ
--   ・読み出しは成果物のサーバー側（service_role）だけ。RLS有効＋ポリシー無し＝anonキーからは不可視
--
-- denki_seo_guide      : 自動で増やす解説ページ（/guides/<slug>）。本文は構造化JSON
-- denki_seo_experiment : 順位を磨く作業の記録（変更前の数字・7日後の判定・元に戻したか）

create table if not exists denki_seo_guide (
  id            uuid primary key default gen_random_uuid(),
  slug          text not null unique,
  keyword       text not null,              -- 狙った検索語
  title         text not null,
  description   text not null,
  answer        text not null,              -- 冒頭の結論（出典番号つき）
  sections      jsonb not null default '[]'::jsonb,   -- [{heading, paragraphs: [text]}]
  checklist     jsonb not null default '[]'::jsonb,   -- [text] 現場で確かめること
  faq           jsonb not null default '[]'::jsonb,   -- [{q, a}]
  citations     jsonb not null default '[]'::jsonb,   -- [{n, title, url, source_name, kind, published_on}]
  status        text not null default 'published',    -- published | hidden
  revision      integer not null default 1,
  history       jsonb not null default '[]'::jsonb,   -- 直前までの版（元に戻す用）
  check_result  jsonb,                                -- 公開前チェックの結果
  meta          jsonb not null default '{}'::jsonb,   -- 選んだ理由・検索候補の出どころ等
  published_at  timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  created_at    timestamptz not null default now()
);

create index if not exists idx_denki_seo_guide_status on denki_seo_guide(status, published_at desc);

create table if not exists denki_seo_experiment (
  id             uuid primary key default gen_random_uuid(),
  guide_slug     text not null,
  page_url       text not null,
  query          text not null,
  started_on     date not null,
  evaluate_on    date not null,           -- この日以降に判定する（変更後7日分の数字がそろう日）
  baseline       jsonb not null,          -- 変更前14日: {position, impressions, clicks, ctr}
  change_summary text not null,
  from_revision  integer not null,
  to_revision    integer not null,
  status         text not null default 'running',   -- running | won | neutral | lost
  result         jsonb,
  evaluated_at   timestamptz,
  created_at     timestamptz not null default now()
);

create index if not exists idx_denki_seo_experiment_status on denki_seo_experiment(status, evaluate_on);

alter table denki_seo_guide      enable row level security;
alter table denki_seo_experiment enable row level security;
