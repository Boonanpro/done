'use client';

import { useEffect } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { Loader2 } from 'lucide-react';

import { api } from '@/lib/api-client';
import { useAuthStore } from '@/stores/auth-store';

/**
 * /chat へのアクセスを最新のセッションにリダイレクト
 */
export default function ChatRedirectPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const isLoading = useAuthStore((state) => state.isLoading);

  const hasToken = typeof window !== 'undefined' && !!localStorage.getItem('done-token');

  // 認証チェック
  useEffect(() => {
    if (!isLoading && !isAuthenticated && !hasToken) {
      router.push('/login');
    }
  }, [isLoading, isAuthenticated, hasToken, router]);

  // 現在のDanルームを取得
  const { data: danRoom, isLoading: isLoadingRoom } = useQuery({
    queryKey: ['dan-room'],
    queryFn: () => api.dan.getRoom(),
    enabled: isAuthenticated || hasToken,
    retry: 2,
  });

  // ルームが取得できたらリダイレクト（query paramsを維持）
  useEffect(() => {
    if (danRoom?.id) {
      const params = searchParams.toString();
      router.replace(`/chat/${danRoom.id}${params ? `?${params}` : ''}`);
    }
  }, [danRoom, router, searchParams]);

  // ローディング表示
  return (
    <div className="flex items-center justify-center h-screen bg-background">
      <div className="flex flex-col items-center gap-4">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
        <p className="text-muted-foreground">読み込み中...</p>
      </div>
    </div>
  );
}
