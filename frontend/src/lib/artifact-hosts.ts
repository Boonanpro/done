/** Next config supplies only the current site's domains in dedicated builds. */
export const KNOWN_CUSTOM_DOMAINS: Record<string, string[]> = JSON.parse(
  process.env.NEXT_PUBLIC_ARTIFACT_ROUTING_DOMAINS || '{}',
);

export function artifactSlugFromHost(host: string): string | null {
  return Object.entries(KNOWN_CUSTOM_DOMAINS).find(([, hosts]) => hosts.includes(host.toLowerCase()))?.[0] || null;
}
