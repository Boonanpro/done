/**
 * React Query Client Configuration
 */

import { QueryClient, isServer } from '@tanstack/react-query';
import { PERSISTED_QUERY_KEYS, PERSIST_MAX_AGE_MS } from '@/lib/query-persister';

function makeQueryClient() {
  const client = new QueryClient({
    defaultOptions: {
      queries: {
        // With SSR, we usually want to set some default staleTime
        // to avoid refetching immediately on the client
        staleTime: 60 * 1000, // 1 minute
        refetchOnWindowFocus: false,
        retry: 1,
      },
    },
  });
  // 永続化するキーは gcTime を保存期間以上にする（既定5分で消えると復元の意味が無い）。
  // 開いていない部屋のメッセージがメモリに残るが、1部屋20件×数十部屋で数MB程度。
  for (const key of PERSISTED_QUERY_KEYS) {
    client.setQueryDefaults([key], { gcTime: PERSIST_MAX_AGE_MS });
  }
  return client;
}

let browserQueryClient: QueryClient | undefined = undefined;

export function getQueryClient() {
  if (isServer) {
    // Server: always make a new query client
    return makeQueryClient();
  }
  // Browser: make a new query client if we don't already have one
  // This is very important, so we don't re-make a new client if React
  // suspends during the initial render. This may not be needed if we
  // have a suspense boundary BELOW the creation of the query client
  if (!browserQueryClient) browserQueryClient = makeQueryClient();
  return browserQueryClient;
}

