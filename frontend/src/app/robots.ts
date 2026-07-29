import type { MetadataRoute } from 'next';
import { headers } from 'next/headers';

import {
  NON_INDEXABLE_PATH_PREFIXES,
  isPublicDeliveryHost,
  normalizeHost,
} from '@/lib/seo-host';

export const dynamic = 'force-dynamic';

/**
 * ホスト単位でクロールの可否を決める。
 *
 *   外部公開ホスト（<slug>-done.vercel.app / 独自ドメイン）→ 許可
 *   ダン本体ホスト（done-studio.vercel.app / localhost 等）→ 全面拒否
 *
 * 判定は @/lib/seo-host に集約してあり、成果物ごとの設定は要らない。
 */
export default async function robots(): Promise<MetadataRoute.Robots> {
  const h = await headers();
  const host = normalizeHost(h.get('host'));

  if (isPublicDeliveryHost(host)) {
    return {
      rules: {
        userAgent: '*',
        allow: '/',
        disallow: NON_INDEXABLE_PATH_PREFIXES,
      },
      sitemap: `https://${host}/sitemap.xml`,
      host: `https://${host}`,
    };
  }

  // ダン本体（チャットシェル・管理画面・編集用プレビュー）は検索対象外。
  return { rules: { userAgent: '*', disallow: '/' } };
}
