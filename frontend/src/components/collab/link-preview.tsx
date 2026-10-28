'use client';

import { useQuery } from '@tanstack/react-query';

export function CollabLinkPreview({ text, roomId, guestToken }: { text: string; roomId: string; guestToken?: string }) {
  const url = text.match(/https:\/\/[^\s<>「」]+/)?.[0]?.replace(/[.,、。)）]+$/, '');
  const { data } = useQuery<{ url: string; title: string; description: string; site: string } | null>({
    queryKey: ['collab-link-preview', roomId, url],
    enabled: !!url,
    staleTime: 60 * 60_000,
    retry: false,
    queryFn: async () => {
      const headers: Record<string, string> = {};
      if (guestToken) headers['X-Guest-Token'] = guestToken;
      else { const token = localStorage.getItem('done-token'); if (token) headers.Authorization = `Bearer ${token}`; }
      const response = await fetch(`/api/v1/collab/rooms/${roomId}/link-preview?url=${encodeURIComponent(url!)}`, { headers, credentials: 'include' });
      if (!response.ok) return null;
      return response.json();
    },
  });
  if (!data || data.url !== url) return null;
  return <a href={data.url} target="_blank" rel="noopener noreferrer" className="mt-2 block max-w-sm rounded-lg border border-current/20 p-3 text-left no-underline" aria-label={`リンクのプレビュー: ${data.title}`}>
    <p className="text-xs opacity-70">{data.site}</p>
    <p className="mt-1 text-sm font-semibold line-clamp-2">{data.title}</p>
    {data.description && <p className="mt-1 text-xs opacity-80 line-clamp-3">{data.description}</p>}
  </a>;
}
