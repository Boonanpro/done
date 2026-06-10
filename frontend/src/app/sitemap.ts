import type { MetadataRoute } from 'next';
import { headers } from 'next/headers';

import { ARTIFACT_PAGES } from '@/lib/artifact-pages.generated';

export const dynamic = 'force-dynamic';

/** host → 成果物 slug を custom-domain マップ（DB由来）から解決する。 */
async function slugForHost(host: string, origin: string): Promise<string | null> {
  try {
    const res = await fetch(`${origin}/api/v1/publish/custom-domains`, {
      signal: AbortSignal.timeout(2500),
    });
    if (res.ok) {
      const json = (await res.json()) as { map?: Record<string, string> };
      return json?.map?.[host] ?? null;
    }
  } catch {
    // 取得失敗時はサイトマップ空（クロール側は再訪する）。
  }
  return null;
}

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const h = await headers();
  const host = (h.get('host') || '').split(':')[0].toLowerCase();
  const proto = h.get('x-forwarded-proto') || 'https';

  const slug = await slugForHost(host, `${proto}://${host}`);
  if (!slug) return [];

  const pages = ARTIFACT_PAGES[slug] ?? ['/'];
  const now = new Date();
  return pages.map((path) => ({
    url: `https://${host}${path === '/' ? '' : path}`,
    lastModified: now,
    changeFrequency: 'weekly' as const,
    priority: path === '/' ? 1 : 0.8,
  }));
}
