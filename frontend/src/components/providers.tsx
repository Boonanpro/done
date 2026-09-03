/**
 * App Providers - Wraps the app with necessary providers
 */

'use client';

import { PersistQueryClientProvider } from '@tanstack/react-query-persist-client';
import { useMemo } from 'react';
import { Toaster } from '@/components/ui/sonner';
import { getQueryClient } from '@/lib/query-client';
import { PERSIST_BUSTER, PERSIST_MAX_AGE_MS, makeQueryPersister, shouldPersistQuery } from '@/lib/query-persister';
import { PwaNotificationBadgeSync } from '@/components/pwa-notification-badge-sync';

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
      <PwaNotificationBadgeSync />
      {children}
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

