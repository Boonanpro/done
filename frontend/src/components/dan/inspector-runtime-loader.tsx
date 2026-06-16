'use client';

import { useEffect } from 'react';
import { usePathname } from 'next/navigation';
import { InspectorRuntime } from './inspector-runtime';
import { initInspectorIframeAgent } from '@/lib/inspector-iframe-agent';

const PUBLIC_ARTIFACT_HOSTS: Record<string, string> = {
  'kittoku.vercel.app': 'kittoku',
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
  // /artifacts/{slug} (通常) または /preview/{slug}
  const m = pathname?.match(/^\/(?:artifacts|preview)\/([^/]+)/);
  const slug = m?.[1] || slugFromHost();

  // クロスオリジン Inspector: iframe 内に居る場合のみ、親ダッシュボードと
  // postMessage で通信する agent を起動する（公開閲覧では何もしない）。
  useEffect(() => {
    if (!slug) return;
    const allowed = (process.env.NEXT_PUBLIC_DASHBOARD_ORIGINS || '')
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);
    initInspectorIframeAgent({ slug, allowedOrigins: allowed });
  }, [slug]);

  if (!slug) return null;
  return <InspectorRuntime slug={slug} />;
}
