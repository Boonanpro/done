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
