import { headers } from 'next/headers';

/**
 * 成果物が独自ドメインで公開されたとき、JSON-LD 構造化データ
 * (WebSite + Organization) を自動で <head> に埋め込むサーバーコンポーネント。
 *
 * - 独自ドメイン (localhost / *.vercel.app 以外) のときだけ出力する。
 *   納品/プレビューURL では検索インデックス対象にしないため出さない。
 * - 会社名(name)は host から site-meta API を引く（成果物ごとの焼き込み不要 ＝
 *   どの成果物が独自ドメインを取得しても自動で構造化データが付く）。
 * - 取得に失敗しても name=host で最低限の WebSite/Organization は出す（落とさない）。
 */

type SiteMeta = { slug: string; name: string; type: string; url: string };

function isPublicCustomDomainHost(host: string): boolean {
  if (!host) return false;
  if (host.startsWith('localhost') || host.startsWith('127.0.0.1')) return false;
  if (host.endsWith('.vercel.app')) return false;
  return true;
}

async function fetchSiteMeta(origin: string, host: string): Promise<SiteMeta | null> {
  try {
    const res = await fetch(
      `${origin}/api/v1/publish/site-meta?host=${encodeURIComponent(host)}`,
      { next: { revalidate: 300 } },
    );
    if (!res.ok) return null;
    const json = (await res.json()) as { meta?: SiteMeta | null };
    return json?.meta ?? null;
  } catch {
    return null;
  }
}

export async function ArtifactStructuredData() {
  const h = await headers();
  const rawHost = h.get('host') || '';
  const host = rawHost.split(':')[0].toLowerCase();
  if (!isPublicCustomDomainHost(host)) return null;

  const proto = h.get('x-forwarded-proto') || 'https';
  const origin = `${proto}://${rawHost}`;
  const meta = await fetchSiteMeta(origin, host);

  const url = `https://${host}`;
  const name = meta?.name || host;
  const jsonLd = {
    '@context': 'https://schema.org',
    '@graph': [
      { '@type': 'WebSite', '@id': `${url}#website`, url, name },
      { '@type': 'Organization', '@id': `${url}#organization`, url, name },
    ],
  };

  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
    />
  );
}
