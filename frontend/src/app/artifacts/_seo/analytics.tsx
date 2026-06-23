import { headers } from 'next/headers';

/**
 * 独自ドメインで公開された成果物に、Umami 計測スクリプトを自動で差し込む
 * サーバーコンポーネント。
 *
 * - 独自ドメイン (localhost / *.vercel.app 以外) のときだけ出力する。
 *   納品/プレビューURL では計測しない（構造化データと同じ判定）。
 * - host から website_id を引く（publish/analytics-tag）。公開時に Umami へ
 *   website 登録されていれば id が返り、計測タグが入る。未登録なら何も出さない。
 * - 取得失敗・未設定でも落とさない（return null）。
 */

type Tag = { website_id: string; src: string };

function isPublicCustomDomainHost(host: string): boolean {
  if (!host) return false;
  if (host.startsWith('localhost') || host.startsWith('127.0.0.1')) return false;
  if (host.endsWith('.vercel.app')) return false;
  return true;
}

async function fetchTag(origin: string, host: string): Promise<Tag | null> {
  try {
    const res = await fetch(
      `${origin}/api/v1/publish/analytics-tag?host=${encodeURIComponent(host)}`,
      { next: { revalidate: 300 } },
    );
    if (!res.ok) return null;
    const json = (await res.json()) as { tag?: Tag | null };
    return json?.tag ?? null;
  } catch {
    return null;
  }
}

export async function ArtifactAnalytics() {
  const h = await headers();
  const rawHost = h.get('host') || '';
  const host = rawHost.split(':')[0].toLowerCase();
  if (!isPublicCustomDomainHost(host)) return null;

  const proto = h.get('x-forwarded-proto') || 'https';
  const origin = `${proto}://${rawHost}`;
  const tag = await fetchTag(origin, host);
  if (!tag?.website_id || !tag?.src) return null;

  // Umami の標準計測タグ。data-website-id でテナントを識別する。
  return <script defer src={tag.src} data-website-id={tag.website_id} />;
}
