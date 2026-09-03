import type { ReactNode } from 'react';

// ゲスト専用マニフェストを当てる（本体アプリの start_url:/chat を継承すると、
// ホーム画面追加したアイコンがログイン画面に飛んでしまうため）。
export async function generateMetadata({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return {
    title: 'チャット',
    manifest: `/collab/join/${token}/manifest.webmanifest`,
  };
}

export default function GuestLayout({ children }: { children: ReactNode }) {
  // Guest pages have no sidebar - standalone view
  return <>{children}</>;
}
