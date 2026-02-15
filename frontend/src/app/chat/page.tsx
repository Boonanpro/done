'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { Loader2 } from 'lucide-react';

import { MainLayout } from '@/components/layout/main-layout';
import { ChatView } from '@/components/chat/chat-view';
import { api } from '@/lib/api-client';
import { useAuthStore } from '@/stores/auth-store';

/**
 * /chat - メインチャットページ
 * 単一のDANルームを自動解決してChatViewを表示
 */
export default function ChatPage() {
  const router = useRouter();
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const isLoading = useAuthStore((state) => state.isLoading);

  const hasToken = typeof window !== 'undefined' && !!localStorage.getItem('done-token');

  // 認証チェック
  useEffect(() => {
    if (!isLoading && !isAuthenticated && !hasToken) {
      router.push('/login');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoading, isAuthenticated, hasToken]);

  // DANルームを取得
  const { data: danRoom, isLoading: isLoadingRoom } = useQuery({
    queryKey: ['dan-room'],
    queryFn: () => api.dan.getRoom(),
    enabled: isAuthenticated || hasToken,
    retry: 2,
  });

  // ローディング中
  if (isLoadingRoom || !danRoom?.id) {
    return (
      <div className="flex items-center justify-center h-screen bg-background">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
          <p className="text-muted-foreground">読み込み中...</p>
        </div>
      </div>
    );
  }

  return (
    <MainLayout>
      <ChatView sessionId={danRoom.id} />
    </MainLayout>
  );
}
