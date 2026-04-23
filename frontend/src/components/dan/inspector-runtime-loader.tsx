'use client';

import { usePathname } from 'next/navigation';
import { InspectorRuntime } from './inspector-runtime';

/** 現在のパスから artifact slug を抽出して InspectorRuntime を起動 */
export function InspectorRuntimeLoader() {
  const pathname = usePathname();
  if (!pathname) return null;
  // /demo/{slug} のみ（dashboard/ は廃止）
  const m = pathname.match(/^\/demo\/([^/]+)/);
  if (!m) return null;
  return <InspectorRuntime slug={m[1]} />;
}
