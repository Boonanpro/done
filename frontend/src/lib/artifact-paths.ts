const DEFAULT_CUSTOM_DOMAINS: Record<string, string[]> = {
  kittoku: ['kittoku.vercel.app', 'yoshikawa-tokuso.vercel.app'],
};

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
  if (hostname && customDomains.includes(hostname)) {
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
  const domain = customDomain || KNOWN_CUSTOM_DOMAINS[slug]?.[0];
  const base = productionUrl || (domain ? `https://${domain}` : null);
  if (!base) return null;

  let rest = '';
  const parsed = parseArtifactPath(pathOrUrl);
  if (parsed?.slug === slug) {
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
