/**
 * App Providers - Wraps the app with necessary providers
 */

'use client';

import { QueryClientProvider } from '@tanstack/react-query';
import { Toaster } from '@/components/ui/sonner';
import { getQueryClient } from '@/lib/query-client';
import { PwaNotificationBadgeSync } from '@/components/pwa-notification-badge-sync';

interface ProvidersProps {
  children: React.ReactNode;
}

export function Providers({ children }: ProvidersProps) {
  const queryClient = getQueryClient();

  return (
    <QueryClientProvider client={queryClient}>
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
    </QueryClientProvider>
  );
}

