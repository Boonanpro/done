import { NextRequest } from 'next/server';

// 株式会社パイナ 専用マニフェスト。
// 公開成果物が DAN 本体の識別情報を継承しないよう、paina 固有の値を返す。
export async function GET(_request: NextRequest) {
  const manifest = {
    name: '株式会社パイナ',
    short_name: 'PAINA',
    description: 'AIエージェント Done（ダン）を開発する株式会社パイナのコーポレートサイト。',
    start_url: '/preview/paina',
    scope: '/preview/paina',
    display: 'standalone',
    background_color: '#faf9f7',
    theme_color: '#1a1712',
    lang: 'ja-JP',
    icons: [
      {
        src: '/paina/icon-192.png',
        sizes: '192x192',
        type: 'image/png',
        purpose: 'any',
      },
      {
        src: '/paina/icon-512.png',
        sizes: '512x512',
        type: 'image/png',
        purpose: 'any',
      },
    ],
  };

  return new Response(JSON.stringify(manifest, null, 2), {
    headers: {
      'Content-Type': 'application/manifest+json',
      'Cache-Control': 'public, max-age=3600',
    },
  });
}
