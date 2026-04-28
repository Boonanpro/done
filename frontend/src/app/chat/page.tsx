'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';

import { MainLayout } from '@/components/layout/main-layout';
import { OWNER_USER_ID } from '@/lib/api-client';
import { usePreviewStore } from '@/stores/preview-store';

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
      // 幽霊プレビュー防止: 未ログイン検知時に preview state を確実にクリア
      try { usePreviewStore.getState().closePreview(); } catch {}
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

  // 全ホストで stale cache を除去。
  // 以前は localhost に限定していたが、モバイル (Tailscale IP 等) で古い JS が
  // 残ってチャット履歴が消える問題が起きたため全ホストに拡張。
  // SW 自体は push 通知に必要なので unregister しない (fetch handler なしなのでキャッシュは無関係)。
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

  return <MainLayout />;
}
