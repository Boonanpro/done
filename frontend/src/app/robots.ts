import type { MetadataRoute } from 'next';
import { headers } from 'next/headers';

export const dynamic = 'force-dynamic';

/**
 * 独自ドメイン = localhost でも *.vercel.app（本体/プレビュー/納品）でもないホスト。
 * 本番の独自ドメインでだけ検索クロールを許可し、それ以外は noindex に倒す。
 */
function isPublicCustomDomain(host: string): boolean {
  if (!host) return false;
  if (host.startsWith('localhost') || host.startsWith('127.0.0.1')) return false;
  if (host.endsWith('.vercel.app')) return false;
  return true;
}

export default async function robots(): Promise<MetadataRoute.Robots> {
  const h = await headers();
  const host = (h.get('host') || '').split(':')[0].toLowerCase();

  if (isPublicCustomDomain(host)) {
    return {
      rules: { userAgent: '*', allow: '/' },
      sitemap: `https://${host}/sitemap.xml`,
      host: `https://${host}`,
    };
  }
  // 本体ダッシュボード・プレビュー・納品 URL は検索インデックスから除外する。
  return { rules: { userAgent: '*', disallow: '/' } };
}
