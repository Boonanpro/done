'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';

import { MainLayout } from '@/components/layout/main-layout';
import { OWNER_USER_ID } from '@/lib/api-client';

/**
 * /chat - メインページ
 * プロジェクト一覧 + 選択したプロジェクトのチャットを表示
 */
export default function ChatPage() {
  const router = useRouter();
  const [checked, setChecked] = useState(false);
  const [hasToken, setHasToken] = useState(true); // SSR中はtrueで初期化（リダイレクト防止）

  // クライアントサイドでトークンとオーナー権限を確認
  useEffect(() => {
    const token = localStorage.getItem('done-token');
    setHasToken(!!token);
    setChecked(true);
    if (!token) {
      router.push('/login');
      return;
    }
    // Decode JWT to check user_id - non-owner users go to /collab
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

  // On localhost, clear stale PWA cache/service-worker state that can hide new UI.
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const host = window.location.hostname;
    if (host !== 'localhost' && host !== '127.0.0.1') return;

    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.getRegistrations().then((registrations) => {
        registrations.forEach((registration) => {
          registration.unregister();
        });
      });
    }

    if ('caches' in window) {
      caches.keys().then((keys) => {
        keys.forEach((key) => {
          caches.delete(key);
        });
      });
    }
  }, []);

  if (!checked || !hasToken) return null;

  return <MainLayout />;
}
