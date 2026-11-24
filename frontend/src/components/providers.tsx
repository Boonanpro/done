/**
 * App Providers - Wraps the app with necessary providers
 */

'use client';

import { IsRestoringProvider } from '@tanstack/react-query';
import { PersistQueryClientProvider } from '@tanstack/react-query-persist-client';
import { useMemo } from 'react';
import { Toaster } from '@/components/ui/sonner';
import { getQueryClient } from '@/lib/query-client';
import { PERSIST_BUSTER, PERSIST_MAX_AGE_MS, makeQueryPersister, shouldPersistQuery } from '@/lib/query-persister';
import { PwaNotificationBadgeSync } from '@/components/pwa-notification-badge-sync';
import { CallProvider } from '@/components/voice/call-provider';

interface ProvidersProps {
  children: React.ReactNode;
}

export function Providers({ children }: ProvidersProps) {
  const queryClient = getQueryClient();
  // 部屋の一式をブラウザ内(IndexedDB)に残し、次回は手元の写しを即描いてから裏で同期する
  const persister = useMemo(() => makeQueryPersister(), []);

  return (
    <PersistQueryClientProvider
      client={queryClient}
      persistOptions={{
        persister: persister ?? { persistClient: async () => {}, restoreClient: async () => undefined, removeClient: async () => {} },
        maxAge: PERSIST_MAX_AGE_MS,
        buster: PERSIST_BUSTER,
        dehydrateOptions: { shouldDehydrateQuery: shouldPersistQuery },
      }}
    >
      {/* 画面は端末の控えの読み戻しを待たずにネットから読み始める。控えが先に読めればそれを先に描き、新しい答えは控えで
          上書きされない（hydrate は新しい時だけ）。本人の Chrome では読み戻しに5〜30秒かかり、その間チャットが空のままだった（2026-11-21） */}
      <IsRestoringProvider value={false}>
        <PwaNotificationBadgeSync />
        {/* 通話は画面全体で1つ。部屋・タイムラインを移っても切れない（components/voice/call-provider.tsx） */}
        <CallProvider>{children}</CallProvider>
      </IsRestoringProvider>
      <Toaster
        position="bottom-right"
        toastOptions={{
          style: {
            background: 'oklch(0.15 0 0)',
            border: '1px solid oklch(0.22 0 0)',
            color: 'oklch(0.98 0 0)',
          },
        }}
      />
    </PersistQueryClientProvider>
  );
}

