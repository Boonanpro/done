import { NextRequest, NextResponse } from 'next/server';

// ゲスト窓口専用の PWA マニフェスト。
// ホーム画面に追加したアイコンは招待URL（＝この窓口）を開く。
// 本体アプリの manifest.json（start_url: /chat）を継承させない。
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ token: string }> },
) {
  const { token } = await params;
  const manifest = {
    name: 'チャット',
    short_name: 'チャット',
    start_url: `/collab/join/${token}`,
    scope: `/collab/join/${token}`,
    display: 'standalone',
    background_color: '#0a0a0a',
    theme_color: '#0a0a0a',
    lang: 'ja-JP',
    icons: [
      { src: '/icon-192x192.png', sizes: '192x192', type: 'image/png', purpose: 'any maskable' },
      { src: '/icon-512x512.png', sizes: '512x512', type: 'image/png', purpose: 'any maskable' },
    ],
  };
  return NextResponse.json(manifest, {
    headers: { 'Content-Type': 'application/manifest+json' },
  });
}
