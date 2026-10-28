import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

import { CUSTOM_DOMAIN_SLUG_MAP } from './lib/custom-domain-rewrites.generated';
import { deliverySlugFromHost, isCustomDomainHost, normalizeHost } from './lib/seo-host';

const ACCESS_TOKEN_COOKIE = 'done_access_token';

// /preview/<slug> は成果物のファイルそのものを見せる場所。本番ビルド（3000）が持つ
// 成果物はビルドした時点の写しなので、ファイルを読む開発サーバー（3001）へ中継する。
// 開発サーバーは部品を /_live/_next/... に出す（NEXT_ASSET_PREFIX=/_live）ので、
// 本番ビルド自身の /_next と混ざらない。中継先は frontend_prod.py が本番ビルドの時だけ
// 渡す（開発サーバー自身と Vercel の専用サイトには無いので、そこでは今までどおり）。
const LIVE_PREVIEW_ORIGIN = (process.env.DAN_LIVE_PREVIEW_ORIGIN || '').replace(/\/+$/, '');
const LIVE_ASSET_PREFIX = '/_live';
let liveAlive: { ok: boolean; at: number } = { ok: false, at: 0 };

async function livePreviewAvailable(): Promise<boolean> {
  if (!LIVE_PREVIEW_ORIGIN) return false;
  const now = Date.now();
  if (now - liveAlive.at < (liveAlive.ok ? 15_000 : 5_000)) return liveAlive.ok;
  let ok = false;
  try {
    const res = await fetch(`${LIVE_PREVIEW_ORIGIN}/manifest.json`, { method: 'HEAD', signal: AbortSignal.timeout(1500), cache: 'no-store' });
    ok = res.status < 500;
  } catch {
    ok = false;
  }
  liveAlive = { ok, at: now };
  return ok;
}

function rewriteToLive(request: NextRequest): NextResponse {
  const target = new URL(request.nextUrl.pathname + request.nextUrl.search, LIVE_PREVIEW_ORIGIN);
  const response = NextResponse.rewrite(target);
  response.headers.set('x-dan-preview-source', 'files');
  return response;
}

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
      // 恒久転送（308）。既定の一時転送（307）だと、検索エンジンが転送元の
      // /artifacts/<slug>/... を別ページとして持ち続け、評価が正規URLへ移らない。
      return NextResponse.redirect(url, 308);
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
  if (pathname.startsWith(`${LIVE_ASSET_PREFIX}/`) && LIVE_PREVIEW_ORIGIN) {
    return rewriteToLive(request);
  }
  if (pathname.startsWith('/preview/')) {
    const segments = pathname.split('/').filter(Boolean);
    if (segments.length >= 2 && await livePreviewAvailable()) {
      return markNoIndex(rewriteToLive(request));
    }
    if (segments.length >= 2) {
      // 開発サーバーが止まっている間だけ、ビルド時点の写しで代わりに見せる（印を付ける）。
      const url = request.nextUrl.clone();
      url.pathname = `/artifacts/${segments.slice(1).join('/')}`;
      const response = NextResponse.rewrite(url);
      if (LIVE_PREVIEW_ORIGIN) response.headers.set('x-dan-preview-source', 'build');
      return markNoIndex(response);
    }
  }

  if (pathname.startsWith('/artifacts/')) {
    const segments = pathname.split('/').filter(Boolean);
    const slug = segments[1];
    const isPublic = Boolean(slug && PUBLIC_ARTIFACT_SLUGS.has(slug));
    const token = request.cookies.get(ACCESS_TOKEN_COOKIE)?.value;
    if (!isPublic && !token) {
      const loginUrl = new URL('/login', request.url);
      loginUrl.searchParams.set('redirect', pathname);
      return NextResponse.redirect(loginUrl);
    }
    // 全画面（/artifacts/<slug>）も成果物タブと同じくファイルそのものを見せる。
    // ビルドの写しのままだと、直した後もここだけ古い画面が出る（10/28 本人「全画面ではまだ送るのまま」）。
    if (slug && await livePreviewAvailable()) {
      return markNoIndex(rewriteToLive(request));
    }
    return markNoIndex(NextResponse.next());
  }

  return NextResponse.next();
}

export const config = {
  matcher: ['/', '/artifacts/:path*', '/preview/:path*', '/_live/:path*', '/manifest.webmanifest'],
};
