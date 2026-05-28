// この募集ページ専用の Web App Manifest。
// サイト共通の /manifest.json は start_url が /chat（ダンのチャット）なので、
// 公開ページがそれを継承しないよう、このページ専用の manifest を配信する。
const MANIFEST = {
  name: 'スタイルアップ — 美容師モニター募集',
  short_name: 'スタイルアップ',
  description:
    '写真を選ぶだけで、サロンボードのスタイル投稿が完成。先着10名モニター募集中。',
  start_url: '/preview/salonboard-monitor',
  scope: '/preview/salonboard-monitor',
  display: 'standalone',
  background_color: '#ffffff',
  theme_color: '#e8607f',
  lang: 'ja-JP',
};

export const dynamic = 'force-static';

export function GET() {
  return new Response(JSON.stringify(MANIFEST, null, 2), {
    headers: {
      'Content-Type': 'application/manifest+json',
      'Cache-Control': 'public, max-age=3600',
    },
  });
}
