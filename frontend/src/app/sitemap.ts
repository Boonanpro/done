import type { MetadataRoute } from 'next';
import { headers } from 'next/headers';

import { ARTIFACT_PAGES } from '@/lib/artifact-pages.generated';
import { ARTIFACT_SITEMAPS } from '@/lib/artifact-sitemaps.generated';
import { CUSTOM_DOMAIN_SLUG_MAP } from '@/lib/custom-domain-rewrites.generated';
import {
  deliverySlugFromHost,
  isPublicDeliveryHost,
  normalizeHost,
} from '@/lib/seo-host';

export const dynamic = 'force-dynamic';

// 独自ドメイン host → slug。接続時に生成される静的マップを反転しておく。
// 専用プロジェクトからは自宅バックエンドに到達できないため、DB 由来の
// 動的マップだけに頼るとサイトマップが恒久的に空になる。
const STATIC_HOST_TO_SLUG: Record<string, string> = (() => {
  const map: Record<string, string> = {};
  for (const [slug, domains] of Object.entries(CUSTOM_DOMAIN_SLUG_MAP)) {
    for (const domain of domains) map[domain] = slug;
  }
  return map;
})();

/** host → 成果物 slug を custom-domain マップ（DB由来）から解決する。 */
async function slugFromCustomDomain(host: string, origin: string): Promise<string | null> {
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
  const host = normalizeHost(h.get('host'));
  const proto = h.get('x-forwarded-proto') || 'https';

  // 内部ホストはそもそもクロールさせないので空を返す。
  if (!isPublicDeliveryHost(host)) return [];

  // 専用プロジェクト → 配信ホスト名 → 接続済み独自ドメインの静的マップ、の順に
  // 外部通信なしで解決する。どれにも当たらない時だけ DB へ問い合わせる。
  const slug =
    process.env.ARTIFACT_ONLY_SLUG?.trim() ||
    deliverySlugFromHost(host) ||
    STATIC_HOST_TO_SLUG[host] ||
    (await slugFromCustomDomain(host, `${proto}://${host}`));
  if (!slug) return [];

  // 成果物が自前の sitemap.ts を持つなら、そちらを正とする。
  // ARTIFACT_PAGES は page.tsx の静的走査なので、質問ページ (/qa/<id>) のように
  // 投稿のたびに増える動的ページが載らず、Google からは「増えないサイト」に見える。
  const loader = ARTIFACT_SITEMAPS[slug];
  if (loader) {
    try {
      const entries = await (await loader()).default();
      if (entries.length > 0) return entries;
    } catch {
      // 成果物側の取得失敗時は静的一覧へフォールバック（クロール側は再訪する）。
    }
  }

  const pages = ARTIFACT_PAGES[slug] ?? ['/'];
  const now = new Date();
  return pages.map((path) => ({
    url: `https://${host}${path === '/' ? '' : path}`,
    lastModified: now,
    changeFrequency: 'weekly' as const,
    priority: path === '/' ? 1 : 0.8,
  }));
}
