import type { Metadata, Viewport } from 'next';

// この募集ページ専用のメタ情報。サイト共通の manifest(start_url=/chat) を上書きし、
// 公開ページがダンのアプリ識別を継承しないようにする。
export const metadata: Metadata = {
  title: 'スタイルアップ — 美容師モニター募集',
  description:
    '写真を選ぶだけ。AIがスタイル名・説明文・タグを下書きして、サロンボードのスタイル投稿を手伝います。先着10名モニター募集中。',
  manifest: '/artifacts/salonboard-monitor/manifest.webmanifest',
  appleWebApp: {
    capable: true,
    title: 'スタイルアップ',
    statusBarStyle: 'default',
  },
};

export const viewport: Viewport = {
  themeColor: '#e8607f',
};

export default function SalonboardMonitorLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
