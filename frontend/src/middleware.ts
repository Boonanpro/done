import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

import { CUSTOM_DOMAIN_SLUG_MAP } from './lib/custom-domain-rewrites.generated';
import { deliverySlugFromHost, isCustomDomainHost, normalizeHost } from './lib/seo-host';

const ACCESS_TOKEN_COOKIE = 'done_access_token';

const DEFAULT_CUSTOM_DOMAIN_MAP: Record<string, string[]> = {
  ...CUSTOM_DOMAIN_SLUG_MAP,
  kittoku: ['kittoku.vercel.app', 'yoshikawa-tokuso.vercel.app'],
};

function parseCustomDomainMap(): Record<string, string[]> {
  const configured = process.env.ARTIFACT_CUSTOM_DOMAINS || process.env.NEXT_PUBLIC_ARTIFACT_CUSTOM_DOMAINS;
  if (!configured) return DEFAULT_CUSTOM_DOMAIN_MAP;

  const map: Record<string, string[]> = { ...DEFAULT_CUSTOM_DOMAIN_MAP };
  for (const entry of configured.split(',')) {
    const [rawSlug, rawDomains] = entry.split('=');
    const slug = rawSlug?.trim();
    if (!slug || !rawDomains) continue;
    const domains = rawDomains
      .split('|')
      .map((s) => s.trim().toLowerCase())
      .filter(Boolean);
    if (domains.length) map[slug] = domains;
  }
  return map;
}

// 静的マップ (env + デフォルト) を host -> slug で1度だけ展開する。
const STATIC_DOMAIN_TO_ARTIFACT: Map<string, string> = (() => {
  const m = new Map<string, string>();
  for (const [slug, domains] of Object.entries(parseCustomDomainMap())) {
    for (const domain of domains) m.set(domain, slug);
  }
  return m;
})();

// DB 由来の接続済みカスタムドメインを TTL 付きでキャッシュする。
// オーナー/クライアントが新しい独自ドメインを接続したら、フロントエンドの
// 再デプロイ無しで数十秒以内に middleware が認識できる。
const DYNAMIC_DOMAIN_TTL_MS = 60_000;
let dynamicDomainCache: { map: Record<string, string>; at: number } = { map: {}, at: 0 };

async function fetchDynamicDomainMap(origin: string): Promise<Record<string, string>> {
  const now = Date.now();
  if (now - dynamicDomainCache.at <= DYNAMIC_DOMAIN_TTL_MS) {
    return dynamicDomainCache.map;
  }
  try {
    const res = await fetch(`${origin}/api/v1/publish/custom-domains`, {
      signal: AbortSignal.timeout(2500),
    });
    if (res.ok) {
      const json = (await res.json()) as { map?: Record<string, string> };
      dynamicDomainCache = { map: json?.map ?? {}, at: now };
    } else {
      // 失敗時も at を更新して TTL 内の再試行ストームを防ぐ。
      dynamicDomainCache = { ...dynamicDomainCache, at: now };
    }
  } catch {
    // バックエンド不達時は前回のキャッシュ (または空) のまま続行する。
    dynamicDomainCache = { ...dynamicDomainCache, at: now };
  }
  return dynamicDomainCache.map;
}

/**
 * 同じ成果物が複数の外部URLで見えるとき、検索エンジンに「こちらが正規」と伝える
 * ホストを決める。独自ドメインが接続済みならそれを優先し、無ければ現在のホスト。
 */
async function canonicalHostFor(
  slug: string,
  currentHost: string,
  origin: string,
  skipLookup = false,
): Promise<string> {
  if (isCustomDomainHost(currentHost)) return currentHost;
  // 専用プロジェクト（1プロジェクト=1成果物）では、この問い合わせ先はバックエンド
  // (自宅PC への tunnel) で、応答に 1.3〜2.5秒かかる。ページ表示の度にこれを待つと
  // TTFB が数秒になり、広告から来た人が白画面のまま離脱する。専用ホストで独自ドメインが
  // 未接続なら canonical は現在のホストで確定するので、問い合わせ自体を行わない。
  if (skipLookup) return currentHost;
  const map = await fetchDynamicDomainMap(origin);
  for (const [domain, mappedSlug] of Object.entries(map)) {
    if (mappedSlug === slug && isCustomDomainHost(domain)) return domain;
  }
  return currentHost;
}

/** 内部用URL（ダン本体ホストのプレビュー・編集画面）を検索対象から外す。 */
function markNoIndex(response: NextResponse): NextResponse {
  response.headers.set('X-Robots-Tag', 'noindex, nofollow');
  return response;
}

const DEFAULT_PUBLIC_ARTIFACT_SLUGS = [
  'kittoku',
  'test-edit',
  'salonboard-styleup',
  'bookings',
  'oku-yukadanbou',
  'oku-yukadanbou-real',
  'moonbox-jp',
  // 創業者に DM のリンクから開いてもらう提案ページ。ログイン不要で読めないと
  // 意味がない（noindex は markNoIndex で付く）。
  'moonbox-proposal',
  // 広告からの流入を受ける公開LP。タイル画像（/artifacts/<slug>/*.png）も
  // ここに入れないと認証リダイレクトされ、画像が1枚も出ない。
  'styleup-lp',
  'salonboard-monitor',
  // Safeguard（ポルノブロッカー）の販売ページ。YouTube・TikTok からの遷移先で、
  // タイル画像・法務ページ・ダウンロード案内すべてログイン不要で開く必要がある。
  'safeguard',
];

const PUBLIC_ARTIFACT_SLUGS = new Set<string>([
  ...DEFAULT_PUBLIC_ARTIFACT_SLUGS,
  ...(process.env.NEXT_PUBLIC_ARTIFACT_SLUGS || '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean),
]);

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const host = normalizeHost(request.headers.get('host'));
  const deliverySlug = deliverySlugFromHost(host);
  // A dedicated project serves exactly one artifact. Unlike the legacy shared
  // host, it needs neither a database lookup nor a generated global rewrite.
  const dedicatedArtifactSlug = process.env.ARTIFACT_ONLY_SLUG?.trim() || null;

  // ホスト解決: 静的マップ → 納品ホスト → DB 由来の動的マップ の順に確認する。
  // 静的マップ / 納品ホストで決まる場合は外部 fetch を避ける。
  let customDomainSlug: string | null = dedicatedArtifactSlug ?? STATIC_DOMAIN_TO_ARTIFACT.get(host) ?? deliverySlug ?? null;
  if (!customDomainSlug && isCustomDomainHost(host)) {
    const dynamicMap = await fetchDynamicDomainMap(request.nextUrl.origin);
    customDomainSlug = dynamicMap[host] ?? null;
  }

  if (customDomainSlug) {
    const segments = pathname.split('/').filter(Boolean);
    const first = segments[0];
    const slug = segments[1];

    if (pathname === '/manifest.webmanifest') {
      const url = request.nextUrl.clone();
      url.pathname = `/artifacts/${customDomainSlug}/manifest.webmanifest`;
      return NextResponse.rewrite(url);
    }

    // SEO: /robots.txt と /sitemap.xml はアプリ直下の host 判定 robots.ts /
    // sitemap.ts に素通しさせる（独自ドメイン直下で確実に配信する）。
    if (pathname === '/robots.txt' || pathname === '/sitemap.xml') {
      return NextResponse.next();
    }

    if (first === 'preview' && slug === customDomainSlug) {
      const url = request.nextUrl.clone();
      const rest = segments.slice(2).join('/');
      url.pathname = rest
        ? `/artifacts/${customDomainSlug}/${rest}`
        : `/artifacts/${customDomainSlug}`;
      return NextResponse.rewrite(url);
    }

    if (first === 'artifacts' && slug === customDomainSlug) {
      const rest = segments.slice(2).join('/');
      // 成果物の静的アセット（画像・動画・フォント・manifest 等、拡張子を持つもの）は
      // clean path へ redirect せずそのまま配信する。ページだけを clean path に寄せる。
      // ここを redirect にすると /artifacts/<slug>/tiles/t1.webp が /tiles/t1.webp へ
      // 飛ばされて 404 になり、画像ファーストLPのタイルが公開サイトで全滅する。
      if (/\.[a-z0-9]+$/i.test(rest)) {
        return NextResponse.next();
      }
      const url = request.nextUrl.clone();
      url.pathname = rest ? `/${rest}` : '/';
      return NextResponse.redirect(url);
    }

    // ここから先は外部公開ホスト（<slug>-done.vercel.app / 独自ドメイン）で
    // 実際に成果物を配信する経路。検索エンジンに開放し、同一内容が複数URLで
    // 見えても評価が割れないよう正規URL（canonical）を明示する。
    const canonicalHost = await canonicalHostFor(
      customDomainSlug,
      host,
      request.nextUrl.origin,
      Boolean(dedicatedArtifactSlug),
    );
    const withCanonical = (response: NextResponse): NextResponse => {
      response.headers.append(
        'Link',
        `<https://${canonicalHost}${pathname === '/' ? '/' : pathname}>; rel="canonical"`,
      );
      return response;
    };

    // ルート (/) は /artifacts/<slug>（[slug]動的ルートが解決）に rewrite。
    // サブパス (/business 等) は middleware が直接 /artifacts/<slug>/<sub> に rewrite
    // するとネスト静的ルートが解決されず404になるため、ここでは next() で素通しし、
    // next.config の host条件付き rewrite（custom-domain-rewrites.generated）に
    // 振り分けを任せる。接続済みドメインは再デプロイ後にクリーンURLで配信される。
    if (pathname === '/') {
      const url = request.nextUrl.clone();
      url.pathname = `/artifacts/${customDomainSlug}`;
      return withCanonical(NextResponse.rewrite(url));
    }
    return withCanonical(NextResponse.next());
  }

  if (pathname === '/') {
    return NextResponse.redirect(new URL('/login', request.url));
  }

  // ここから先はダン本体ホスト（localhost 等）。
  // /preview/<slug> はチャット横の編集用プレビュー、/artifacts/<slug> はその実体で、
  // どちらも内部用URL。外部公開URLと中身が重複するため必ず検索対象から外す。
  if (pathname.startsWith('/preview/')) {
    const segments = pathname.split('/').filter(Boolean);
    if (segments.length >= 2) {
      const url = request.nextUrl.clone();
      url.pathname = `/artifacts/${segments.slice(1).join('/')}`;
      return markNoIndex(NextResponse.rewrite(url));
    }
  }

  if (pathname.startsWith('/artifacts/')) {
    const segments = pathname.split('/').filter(Boolean);
    const slug = segments[1];
    if (slug && PUBLIC_ARTIFACT_SLUGS.has(slug)) {
      return markNoIndex(NextResponse.next());
    }

    const token = request.cookies.get(ACCESS_TOKEN_COOKIE)?.value;
    if (!token) {
      const loginUrl = new URL('/login', request.url);
      loginUrl.searchParams.set('redirect', pathname);
      return NextResponse.redirect(loginUrl);
    }
    return markNoIndex(NextResponse.next());
  }

  return NextResponse.next();
}

export const config = {
  matcher: ['/', '/artifacts/:path*', '/preview/:path*', '/manifest.webmanifest'],
};
