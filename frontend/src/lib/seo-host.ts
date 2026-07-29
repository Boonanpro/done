/**
 * 検索エンジンにクロールさせてよいホストかどうかを判定する唯一の場所。
 *
 * robots.ts / sitemap.ts / middleware.ts はすべてここを参照する。
 * 「外部公開用は検索に載せる・内部用はブロックする」を成果物ごとの設定なしで
 * 全体に適用するための基準。
 *
 * 外部公開ホスト（クロール許可）:
 *   - `<slug>-done.vercel.app` … 成果物の配信ホスト（ユーザーに案内する公開URL）
 *   - 独自ドメイン            … 成果物に接続されたドメイン
 *
 * 内部ホスト（クロール禁止）:
 *   - localhost / 127.0.0.1
 *   - ダン本体の *.vercel.app（done-studio.vercel.app / frontend-xxxx.vercel.app 等）
 *     ここにはチャットシェル・管理画面・編集用プレビューが同居するため丸ごと塞ぐ。
 */

const DELIVERY_HOST_SUFFIX = '-done.vercel.app';

/** Host ヘッダからポートを落として小文字化する。 */
export function normalizeHost(rawHost: string | null | undefined): string {
  return (rawHost || '').split(':')[0].trim().toLowerCase();
}

export function isLocalHost(host: string): boolean {
  return (
    host === 'localhost' ||
    host.startsWith('localhost') ||
    host === '127.0.0.1' ||
    host.startsWith('127.0.0.1') ||
    host.endsWith('.localhost')
  );
}

/** `<slug>-done.vercel.app` なら slug を返す。配信ホストでなければ null。 */
export function deliverySlugFromHost(host: string): string | null {
  if (!host.endsWith(DELIVERY_HOST_SUFFIX)) return null;
  const slug = host.slice(0, -DELIVERY_HOST_SUFFIX.length);
  return slug || null;
}

/** localhost でも *.vercel.app でもない = 成果物に接続された独自ドメイン。 */
export function isCustomDomainHost(host: string): boolean {
  if (!host) return false;
  if (isLocalHost(host)) return false;
  if (host.endsWith('.vercel.app') || host === 'vercel.app') return false;
  return true;
}

/**
 * 外部公開用ホストか。true ならクロール許可、false ならダン内部として全面ブロック。
 */
export function isPublicDeliveryHost(host: string): boolean {
  if (!host) return false;
  if (deliverySlugFromHost(host)) return true;
  return isCustomDomainHost(host);
}

/**
 * 外部公開ホストでも検索対象にしないパス。
 * `/preview/` はダン内部の編集用、`/api/` は実データなので常に除外する。
 */
export const NON_INDEXABLE_PATH_PREFIXES = ['/api/', '/preview/'];
