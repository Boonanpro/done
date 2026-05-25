// このツール専用の「ホーム画面に追加」設定（Web App Manifest）。
//
// サイト共通の /manifest.json は start_url が /chat（ダンのチャット）なので、
// ホーム画面アイコンから起動するとダンのログイン画面に飛んでしまう。
// このツールのページ(layout.tsx)からはこの manifest を参照させ、
// 起動先をツール本体(/preview/salonboard-styleup)に固定する。
//
// 成果物フォルダ内のルートハンドラとして配信することで、ダン共通の
// public/ 資産には手を加えず、このツール単体の変更として完結させている。
const MANIFEST = {
  name: 'StyleSnap — スタイル投稿',
  short_name: 'StyleSnap',
  description: '写真を選ぶだけで、サロンボードのスタイル投稿が完成します。',
  start_url: '/preview/salonboard-styleup',
  scope: '/preview/salonboard-styleup',
  display: 'standalone',
  background_color: '#ffffff',
  theme_color: '#e8607f',
  lang: 'ja-JP',
  icons: [
    {
      src: '/artifacts/salonboard-styleup/icon-192.png',
      sizes: '192x192',
      type: 'image/png',
      purpose: 'any maskable',
    },
    {
      src: '/artifacts/salonboard-styleup/icon-512.png',
      sizes: '512x512',
      type: 'image/png',
      purpose: 'any maskable',
    },
  ],
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
