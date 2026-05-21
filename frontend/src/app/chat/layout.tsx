'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';

import { MainLayout } from '@/components/layout/main-layout';
import { OWNER_USER_ID } from '@/lib/api-client';
import { usePreviewStore } from '@/stores/preview-store';

/**
 * /chat 配下の共有レイアウト。
 * MainLayout（サイドバー + メインペイン）をここで一度だけマウントすることで、
 * /chat と /chat/[projectId] 間の遷移でサイドバー全体が再マウントされる
 * （＝ガタッと再描画される）のを防ぐ。
 *
 * 実コンテンツは MainLayout が `selectedProjectId` ストアに基づいて自前で出すので、
 * page.tsx 側は null を返すだけでよい。
 */
export default function ChatLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [checked, setChecked] = useState(false);
  const [hasToken, setHasToken] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem('done-token');
    setHasToken(!!token);
    setChecked(true);
    if (!token) {
      try { usePreviewStore.getState().closePreview(); } catch {}
      router.push('/login');
      return;
    }
    try {
      const payload = JSON.parse(atob(token.split('.')[1]));
      if (payload.sub !== OWNER_USER_ID) {
        router.replace('/collab');
        return;
      }
    } catch {
      // Invalid token, let auth handle it
    }
  }, [router]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    if ('caches' in window) {
      caches.keys().then((keys) => {
        keys.forEach((key) => {
          caches.delete(key);
        });
      });
    }
  }, []);

  if (!checked || !hasToken) return null;

  return (
    <>
      {children}
      <MainLayout />
    </>
  );
}
