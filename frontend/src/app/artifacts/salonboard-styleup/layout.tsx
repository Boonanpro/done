import type { Metadata, Viewport } from 'next';

// このツール専用の「ホーム画面に追加」設定。
// サイト共通の manifest(/manifest.json, start_url=/chat) を上書きし、
// ホーム画面のアイコンから起動した時に必ずツール本体(/preview/salonboard-styleup)が
// 開くようにする。これによりダンのログイン画面に飛ぶのを防ぐ。
export const metadata: Metadata = {
  title: 'StyleSnap — サロンボード スタイル投稿',
  description: '写真を選ぶだけで、サロンボードのスタイル投稿が完成します。',
  manifest: '/artifacts/salonboard-styleup/manifest.webmanifest',
  icons: {
    icon: '/artifacts/salonboard-styleup/icon-192.png',
    apple: '/artifacts/salonboard-styleup/apple-touch-icon.png',
  },
  appleWebApp: {
    capable: true,
    title: 'StyleSnap',
    statusBarStyle: 'default',
  },
};

export const viewport: Viewport = {
  themeColor: '#e8607f',
};

export default function SalonboardStyleupLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
