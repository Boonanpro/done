'use client';

import { ArrowLeft, BookOpen, ChevronRight } from 'lucide-react';
import type { PromptSummary } from '@/lib/prompts-api';
import type { ArchNode } from './architecture';

// These are examples of requests, not rules for choosing a skill. Chat and job
// workers share the catalogue. The editor shows the skills relevant to production.
const GROUPS = [
  { title: '動画の企画・編集', production: true, requests: {
    'talking-demo-editing': 'インタビューに実演を差し込む', 'talk-script': '話す動画の台本を書く',
    'video-direction': '見せる場面と絵コンテを決める', 'creative-studio': '動画の作り方を企画する',
    'video-draft': 'エディターで動画の下書きを作る', 'explainer-video': 'ナレーションに合わせて解説動画を作る',
    'post-production': '撮った映像の字幕や音を整える', studio: '実際の操作画面を収録する',
    popout: '話す人が画面の枠から飛び出すようにする',
  } },
  { title: '画像・映像の素材', production: true, requests: {
    'media-gen': '画像や動画に使う生成手段を選ぶ', 'brand-asset-kit': '公式ロゴやブランドの素材をそろえる',
    'higgsfield-generate': 'Higgsfieldで画像や動画を生成する', 'higgsfield-product-photoshoot': '商品写真を作る',
    'higgsfield-marketplace-cards': '販売ページの商品紹介画像を作る', 'higgsfield-soul-id': '同じ人物で複数の画像を作る',
  } },
  { title: '予定・連絡・顧客対応', requests: {
    calendar: '空いている日時を調べる', 'email-send': '確認済みのメールを送る',
    'fukurou-client-operations': 'ふくろうPの相談や納品を進める', 'fukurou-script-handoff': 'お客さんの台本を直して納品用に整える',
    'instagram-dm': 'InstagramのDMに返事をする', 'phone-operation': 'スマホのアプリを実機で操作する',
  } },
  { title: '集客・アカウントの準備', requests: {
    'x-operation': 'Xに載せる記事を書く', 'meta-ads': 'InstagramやFacebookの広告を運用する',
    'dry-test-launcher': '広告を小さく出して需要を調べる', 'instagram-account-setup': 'Instagramのアカウントを用意する',
    'line-official-account-setup': '公式LINEのあいさつやメニューを作る', 'stripe-account-setup': 'Stripeで決済の受付を準備する',
  } },
  { title: 'サイト・画面の動き', requests: {
    build: '編集できるサイトを作る', 'vercel-react-best-practices': 'Reactの画面表示を速くする',
    'gsap-core': '画面の部品を滑らかに動かす', 'gsap-timeline': '複数の動きを順番に再生する',
    'gsap-scrolltrigger': 'スクロールに合わせて絵を動かす', 'gsap-plugins': 'GSAPのプラグインで動きを加える',
    'gsap-react': 'Reactの中でGSAPを使う', 'gsap-performance': 'アニメーションのかくつきを直す',
  } },
  { title: 'ダンの開発・検証', requests: {
    'goal-test': '直した機能を実際の使い方で試す', 'self-dev': 'ダンのプログラムを改修する',
    'skill-creator': 'スキルを作り、指示が効くか比べる', 'supabase-ddl': 'データベースの表や列を変更する',
  } },
] satisfies { title: string; production?: boolean; requests: Record<string, string> }[];

export const READER_EXAMPLES: Record<string, string> = {
  chat: 'calendar', editor: 'talking-demo-editing', editorTalk: 'video-direction',
  parallel: 'build', codex: 'x-operation',
};

type Entry = { page: PromptSummary; request: string };
export function readerGroups(reader: string, pages: PromptSummary[]) {
  const manuals = new Map(pages.filter(p => p.id.split('/').length === 2).map(p => [p.id.slice(6), p]));
  const production = reader === 'editor' || reader === 'editorTalk';
  const groups = GROUPS.filter(g => !production || g.production).map(group => {
    const entries: Entry[] = [];
    for (const [key, request] of Object.entries(group.requests)) {
      const page = manuals.get(key);
      if (page) entries.push({ page, request });
      manuals.delete(key);
    }
    return { title: group.title, entries };
  }).filter(g => g.entries.length);
  if (!production && manuals.size) groups.push({ title: 'その他の頼み', entries: Array.from(manuals.values(), page => ({ page, request: page.when })) });
  return groups;
}

export function ReaderSkills({ node, groups, onBack, onPick }: {
  node: ArchNode; groups: ReturnType<typeof readerGroups>; onBack: () => void; onPick: (id: string) => void;
}) {
  return <section aria-label={node.name + 'のスキルの構成図'} className="rounded-xl border border-stone-200 bg-white p-3 text-stone-900 sm:p-5">
    <button type="button" onClick={onBack} className="mb-4 inline-flex items-center gap-1 py-1 text-sm text-stone-600 hover:underline"><ArrowLeft size={16} />構成図全体に戻る</button>
    <div className="flex w-fit items-center gap-3 rounded-xl border-2 border-teal-700 bg-teal-50 px-3 py-2">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={'/prompts/arch/' + node.icon + '.webp'} alt="" width="50" height="50" className="rounded-lg" />
      <div><h2 className="font-bold">{node.name}</h2><p className="text-sm text-teal-900">頼みに合わせて読むスキル</p></div>
    </div>
    <div className="ml-4 border-l-2 border-teal-200 pb-1 pl-4 sm:ml-7 sm:pl-6">
      {groups.map(g => <div key={g.title} className="relative pt-4">
        <h3 className="mb-2 text-sm font-bold text-teal-900 before:absolute before:-left-4 before:top-[26px] before:w-3 before:border-t-2 before:border-teal-200 sm:before:-left-6 sm:before:w-5">{g.title}</h3>
        <div className="grid gap-2" style={{gridTemplateColumns:'repeat(auto-fit,minmax(min(100%,220px),1fr))'}}>
          {g.entries.map(({page, request}) => <button key={page.id} type="button" onClick={() => onPick(page.id)} className="flex items-center gap-2 rounded-lg border border-stone-200 bg-stone-50 px-3 py-2 text-left hover:border-teal-600 hover:bg-teal-50">
            <span className="min-w-0 flex-1"><span className="block text-sm font-semibold">{request}</span>
              <span className="mt-1 flex items-center gap-1 break-words text-xs text-teal-800"><BookOpen size={13} className="shrink-0" />{page.title}</span></span>
            <ChevronRight size={15} className="shrink-0 text-stone-400" />
          </button>)}
        </div></div>)}
    </div>
  </section>;
}
