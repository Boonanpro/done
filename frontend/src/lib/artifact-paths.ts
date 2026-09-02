import { CUSTOM_DOMAIN_SLUG_MAP } from './custom-domain-rewrites.generated';

const DEFAULT_CUSTOM_DOMAINS: Record<string, string[]> = {
  ...CUSTOM_DOMAIN_SLUG_MAP,
  kittoku: ['kittoku.vercel.app', 'yoshikawa-tokuso.vercel.app'],
};

const DELIVERY_DOMAIN_SUFFIX =
  process.env.NEXT_PUBLIC_ARTIFACT_DELIVERY_SUFFIX || '-done.vercel.app';

function parseCustomDomains(): Record<string, string[]> {
  const configured = process.env.NEXT_PUBLIC_ARTIFACT_CUSTOM_DOMAINS;
  if (!configured) return DEFAULT_CUSTOM_DOMAINS;

  const map: Record<string, string[]> = { ...DEFAULT_CUSTOM_DOMAINS };
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

export const KNOWN_CUSTOM_DOMAINS: Record<string, string[]> = parseCustomDomains();

function isInternalVercelUrl(value?: string | null): boolean {
  if (!value) return false;
  try {
    const host = new URL(value).hostname;
    return /^frontend(?:-[a-z0-9-]+)?-mikis-projects-86652663\.vercel\.app$/.test(host);
  } catch {
    return false;
  }
}

/** localhost / *.vercel.app 以外＝成果物がドメイン直下で配信される独自ドメイン。 */
function isPublicCustomDomainHost(hostname: string): boolean {
  if (!hostname) return false;
  if (hostname.startsWith('localhost') || hostname.startsWith('127.0.0.1')) return false;
  if (hostname.endsWith('.vercel.app')) return false;
  return true;
}

/**
 * 専用配信プロジェクトのホスト（`dan-site-<slug>-<id>.vercel.app`）か。
 *
 * 独自ドメインと同じく 1 ホスト = 1 成果物なので、成果物はドメイン直下で
 * 配信される。ここを判定しないと、独自ドメインを繋ぐ前の成果物のリンクだけ
 * `/preview/<slug>/...` のままになり、公開ページの URL に「preview」が
 * 出続ける（動きはするが、法務ページを載せる商用ページとしては見栄えが悪い）。
 */
function isDedicatedDeliveryHost(hostname: string): boolean {
  return /^dan-site-[a-z0-9-]+\.vercel\.app$/.test(hostname);
}

function normalizeRest(rest = ''): string {
  if (!rest || rest === '/') return '';
  return rest.startsWith('/') ? rest : `/${rest}`;
}

function cleanPath(rest = ''): string {
  const normalized = normalizeRest(rest);
  return normalized || '/';
}

export function artifactWorkspacePath(slug: string, rest = ''): string {
  return `/artifacts/${slug}${normalizeRest(rest)}`;
}

export function artifactPreviewPath(slug: string, rest = ''): string {
  return `/preview/${slug}${normalizeRest(rest)}`;
}

export function artifactPublicPath(slug: string, rest = ''): string {
  return artifactPreviewPath(slug, rest);
}

export function artifactDeliveryDomain(slug: string): string {
  return `${slug}${DELIVERY_DOMAIN_SUFFIX}`;
}

export function artifactDeliveryUrl(slug: string, rest = ''): string {
  return `https://${artifactDeliveryDomain(slug)}${cleanPath(rest)}`;
}

export function artifactVisiblePath({
  slug,
  rest = '',
  pathname = '',
  hostname = '',
}: {
  slug: string;
  rest?: string;
  pathname?: string;
  hostname?: string;
}): string {
  const customDomains = KNOWN_CUSTOM_DOMAINS[slug] || [];
  // 独自ドメイン上では常にクリーンURL（/business 等）を出す。静的リスト(KNOWN_CUSTOM_DOMAINS)
  // に無い動的接続ドメインでも、localhost / *.vercel.app 以外＝独自ドメインなら成果物は
  // ドメイン直下で配信されているので、リンクも /preview を付けずクリーンにする。
  if (
    hostname &&
    (customDomains.includes(hostname) ||
      hostname === artifactDeliveryDomain(slug) ||
      isDedicatedDeliveryHost(hostname) ||
      isPublicCustomDomainHost(hostname))
  ) {
    return cleanPath(rest);
  }

  if (pathname === `/preview/${slug}` || pathname.startsWith(`/preview/${slug}/`)) {
    return artifactPreviewPath(slug, rest);
  }

  if (pathname === `/artifacts/${slug}` || pathname.startsWith(`/artifacts/${slug}/`)) {
    return artifactWorkspacePath(slug, rest);
  }

  return artifactPublicPath(slug, rest);
}

export function artifactSharePath(pathOrSlug: string, rest = ''): string {
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(pathOrSlug)) return pathOrSlug;
  if (pathOrSlug.startsWith('/') && !pathOrSlug.startsWith('/artifacts/') && !pathOrSlug.startsWith('/preview/')) {
    return pathOrSlug;
  }
  const parsed = parseArtifactPath(pathOrSlug);
  if (parsed) return artifactPreviewPath(parsed.slug, parsed.rest);
  return artifactPreviewPath(pathOrSlug, rest);
}

export function artifactProductionUrl({
  slug,
  pathOrUrl = '',
  productionUrl,
  customDomain,
}: {
  slug: string;
  pathOrUrl?: string;
  productionUrl?: string | null;
  customDomain?: string | null;
}): string | null {
  // Prefer explicit published URLs, then known route domains. Card slugs can
  // differ from route slugs, so pathOrUrl is the source of truth for routing.
  const parsed = parseArtifactPath(pathOrUrl);
  const routeSlug = parsed?.slug || slug;
  const knownDomain = KNOWN_CUSTOM_DOMAINS[routeSlug]?.[0];
  const domain = customDomain || knownDomain;
  const safeProductionUrl = isInternalVercelUrl(productionUrl) ? null : productionUrl;
  const base = safeProductionUrl || (domain ? `https://${domain}` : `https://${artifactDeliveryDomain(routeSlug)}`);
  if (!base) return null;

  let rest = '';
  if (parsed?.slug === routeSlug) {
    rest = parsed.rest;
  } else if (pathOrUrl.startsWith('/') && !pathOrUrl.startsWith('/artifacts/') && !pathOrUrl.startsWith('/preview/')) {
    rest = pathOrUrl;
  }

  try {
    return new URL(cleanPath(rest), base).toString();
  } catch {
    return null;
  }
}

export function parseArtifactPath(
  href: string,
): { slug: string; rest: string } | null {
  const match = href.match(/^\/(?:artifacts|preview)\/([^/?#]+)([^?#]*)?([?#].*)?$/);
  if (!match) return null;
  return {
    slug: decodeURIComponent(match[1]),
    rest: `${match[2] || ''}${match[3] || ''}`,
  };
}

export function resolveArtifactHref({
  slug,
  rest = '',
  pathname = '',
  hostname = '',
}: {
  slug: string;
  rest?: string;
  pathname?: string;
  hostname?: string;
}): string {
  return artifactVisiblePath({ slug, rest, pathname, hostname });
}
