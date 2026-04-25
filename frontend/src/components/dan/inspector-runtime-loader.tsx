'use client';

import { usePathname } from 'next/navigation';
import { InspectorRuntime } from './inspector-runtime';

/** 現在のパスから artifact slug を抽出して InspectorRuntime を起動 */
export function InspectorRuntimeLoader() {
  const pathname = usePathname();
  if (!pathname) return null;
  // /artifacts/{slug} (通常) または /demo/{slug} (提案動画用プロトタイプ)
  const m = pathname.match(/^\/(?:artifacts|demo)\/([^/]+)/);
  if (!m) return null;
  return <InspectorRuntime slug={m[1]} />;
}
