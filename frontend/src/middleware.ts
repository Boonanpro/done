import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

const ACCESS_TOKEN_COOKIE = 'done_access_token';

const DEFAULT_CUSTOM_DOMAIN_MAP: Record<string, string[]> = {
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

function deliverySlugFromHost(host: string): string | null {
  if (!host.endsWith('-done.vercel.app')) return null;
  const slug = host.slice(0, -'-done.vercel.app'.length);
  return slug || null;
}

const DEFAULT_PUBLIC_ARTIFACT_SLUGS = ['kittoku', 'test-edit', 'salonboard-styleup', 'bookings'];

const PUBLIC_ARTIFACT_SLUGS = new Set<string>([
  ...DEFAULT_PUBLIC_ARTIFACT_SLUGS,
  ...(process.env.NEXT_PUBLIC_ARTIFACT_SLUGS || '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean),
]);

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const host = (request.headers.get('host') || '').split(':')[0].toLowerCase();
  const deliverySlug = deliverySlugFromHost(host);

  // ホスト解決: 静的マップ → 納品ホスト → DB 由来の動的マップ の順に確認する。
  // 静的マップ / 納品ホストで決まる場合は外部 fetch を避ける。
  let customDomainSlug: string | null = STATIC_DOMAIN_TO_ARTIFACT.get(host) ?? deliverySlug ?? null;
  if (!customDomainSlug) {
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
      if (rest === 'manifest.webmanifest' || /^icon-\d+\.png$/.test(rest)) {
        return NextResponse.next();
      }
      const url = request.nextUrl.clone();
      url.pathname = rest ? `/${rest}` : '/';
      return NextResponse.redirect(url);
    }

    const url = request.nextUrl.clone();
    url.pathname =
      pathname === '/' ? `/artifacts/${customDomainSlug}` : `/artifacts/${customDomainSlug}${pathname}`;
    const response = NextResponse.rewrite(url);
    // 納品URL (<slug>-done.vercel.app) は確認用なので検索インデックスから除外する。
    // 本番の独自ドメインで公開した時のみ検索に載るようにする。
    if (deliverySlug) {
      response.headers.set('X-Robots-Tag', 'noindex, nofollow');
    }
    return response;
  }

  if (pathname === '/') {
    return NextResponse.redirect(new URL('/login', request.url));
  }

  if (pathname.startsWith('/preview/')) {
    const segments = pathname.split('/').filter(Boolean);
    if (segments.length >= 2) {
      const url = request.nextUrl.clone();
      url.pathname = `/artifacts/${segments.slice(1).join('/')}`;
      return NextResponse.rewrite(url);
    }
  }

  if (pathname.startsWith('/artifacts/')) {
    const segments = pathname.split('/').filter(Boolean);
    const slug = segments[1];
    if (slug && PUBLIC_ARTIFACT_SLUGS.has(slug)) {
      return NextResponse.next();
    }

    const token = request.cookies.get(ACCESS_TOKEN_COOKIE)?.value;
    if (!token) {
      const loginUrl = new URL('/login', request.url);
      loginUrl.searchParams.set('redirect', pathname);
      return NextResponse.redirect(loginUrl);
    }
    return NextResponse.next();
  }

  return NextResponse.next();
}

export const config = {
  matcher: ['/', '/artifacts/:path*', '/preview/:path*', '/manifest.webmanifest'],
};
