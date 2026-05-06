'use client';

import { usePathname } from 'next/navigation';
import { InspectorRuntime } from './inspector-runtime';

const PUBLIC_ARTIFACT_HOSTS: Record<string, string> = {
  'kittoku.vercel.app': 'kittoku',
  'kittoku-tokuso.vercel.app': 'kittoku',
  'yoshikawa-tokuso.vercel.app': 'kittoku',
};

function slugFromHost(): string | null {
  if (typeof window === 'undefined') return null;
  const envMap = process.env.NEXT_PUBLIC_ARTIFACT_HOST_MAP;
  if (envMap) {
    for (const pair of envMap.split(',')) {
      const [host, slug] = pair.split(':').map((s) => s?.trim());
      if (host && slug && window.location.host === host) return slug;
    }
  }
  return PUBLIC_ARTIFACT_HOSTS[window.location.host] || null;
}

/** 現在のパスから artifact slug を抽出して InspectorRuntime を起動 */
export function InspectorRuntimeLoader() {
  const pathname = usePathname();
  if (!pathname) return null;
  // /artifacts/{slug} (通常) または /demo/{slug} (提案動画用プロトタイプ)
  const m = pathname.match(/^\/(?:artifacts|demo|preview)\/([^/]+)/);
  const slug = m?.[1] || slugFromHost();
  if (!slug) return null;
  return <InspectorRuntime slug={slug} />;
}
