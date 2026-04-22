'use client';

import { usePathname } from 'next/navigation';
import { InspectorRuntime } from './inspector-runtime';

/** 現在のパスから artifact slug を抽出して InspectorRuntime を起動 */
export function InspectorRuntimeLoader() {
  const pathname = usePathname();
  if (!pathname) return null;
  // /demo/{slug} または /dashboard/{slug}
  const m = pathname.match(/^\/(?:demo|dashboard)\/([^/]+)/);
  if (!m) return null;
  return <InspectorRuntime slug={m[1]} />;
}
