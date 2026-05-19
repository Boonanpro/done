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

const DOMAIN_TO_ARTIFACT = new Map<string, string>();
for (const [slug, domains] of Object.entries(parseCustomDomainMap())) {
  for (const domain of domains) DOMAIN_TO_ARTIFACT.set(domain, slug);
}

function deliverySlugFromHost(host: string): string | null {
  if (!host.endsWith('-done.vercel.app')) return null;
  const slug = host.slice(0, -'-done.vercel.app'.length);
  return slug || null;
}

const DEFAULT_PUBLIC_ARTIFACT_SLUGS = ['kittoku', 'test-edit', 'salonboard-styleup'];

const PUBLIC_ARTIFACT_SLUGS = new Set<string>([
  ...DEFAULT_PUBLIC_ARTIFACT_SLUGS,
  ...(process.env.NEXT_PUBLIC_ARTIFACT_SLUGS || '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean),
]);

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const host = (request.headers.get('host') || '').split(':')[0].toLowerCase();
  const customDomainSlug = DOMAIN_TO_ARTIFACT.get(host) || deliverySlugFromHost(host);

  if (customDomainSlug) {
    const segments = pathname.split('/').filter(Boolean);
    const first = segments[0];
    const slug = segments[1];

    if ((first === 'preview' || first === 'artifacts') && slug === customDomainSlug) {
      const url = request.nextUrl.clone();
      const rest = segments.slice(2).join('/');
      url.pathname = rest ? `/${rest}` : '/';
      return NextResponse.redirect(url);
    }

    const url = request.nextUrl.clone();
    url.pathname =
      pathname === '/' ? `/artifacts/${customDomainSlug}` : `/artifacts/${customDomainSlug}${pathname}`;
    return NextResponse.rewrite(url);
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
  matcher: ['/', '/artifacts/:path*', '/preview/:path*'],
};
