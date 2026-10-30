/** Build-only registry. Never import this module from a browser component. */
export function artifactRoutingDomains(
  generated: Record<string, string[]>,
  env: Record<string, string | undefined>,
): Record<string, string[]> {
  const domains: Record<string, string[]> = {
    ...generated,
    kittoku: [...new Set([...(generated.kittoku || []), 'kittoku.vercel.app', 'yoshikawa-tokuso.vercel.app'])],
  };
  for (const entry of (env.NEXT_PUBLIC_ARTIFACT_CUSTOM_DOMAINS || '').split(',')) {
    const [rawSlug, rawDomains] = entry.split('=');
    const slug = rawSlug?.trim();
    if (!slug || !rawDomains) continue;
    const hosts = rawDomains.split('|').map((host) => host.trim().toLowerCase()).filter(Boolean);
    if (hosts.length) domains[slug] = hosts;
  }
  for (const entry of (env.NEXT_PUBLIC_ARTIFACT_HOST_MAP || '').split(',')) {
    const [host, slug] = entry.split(':').map((value) => value.trim());
    if (host && slug) domains[slug] = [...new Set([...(domains[slug] || []), host.toLowerCase()])];
  }
  const dedicatedSlug = env.ARTIFACT_ONLY_SLUG?.trim();
  return dedicatedSlug ? (domains[dedicatedSlug] ? { [dedicatedSlug]: domains[dedicatedSlug] } : {}) : domains;
}

/** Shared previews identify themselves by path, never by a customer directory. */
export function publicArtifactRoutingDomains(generated: Record<string, string[]>, env: Record<string, string | undefined>) {
  return env.ARTIFACT_ONLY_SLUG?.trim() ? artifactRoutingDomains(generated, env) : {};
}

/** Resolve legacy root domains on the server; serialize only the selected slug. */
export function artifactSlugFromServerHost(host: string, generated: Record<string, string[]>, env: Record<string, string | undefined>): string | null {
  const dedicated = env.ARTIFACT_ONLY_SLUG?.trim();
  if (dedicated) return dedicated;
  const hostname = host.toLowerCase().split(':')[0];
  const known = Object.entries(artifactRoutingDomains(generated, env)).find(([, hosts]) => hosts.includes(hostname));
  if (known) return known[0];
  const suffix = env.NEXT_PUBLIC_ARTIFACT_DELIVERY_SUFFIX || '-done.vercel.app';
  const slug = hostname.endsWith(suffix) ? hostname.slice(0, -suffix.length) : '';
  return /^[a-z0-9][a-z0-9-]*$/.test(slug) ? slug : null;
}
