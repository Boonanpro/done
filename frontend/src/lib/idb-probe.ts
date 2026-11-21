'use client';

// Once a day per device: how slow this site's IndexedDB is to read (the chat's kept copy, the board and the script screen
// live there). 11/21 the owner's Chrome took 12 s to list 3 keys and 31 s to read the chat's 6.8 MB copy, because the
// service worker's expiration records (~2 million) were walked on every cached request. event=site-idb.
import { perfLog } from '@/lib/perf-log';

const DAY_KEY = 'site-idb-probe';

export function probeSiteIdbOncePerDay(delayMs = 8000) {
  if (typeof window === 'undefined' || !('indexedDB' in window)) return;
  try {
    const day = new Date().toISOString().slice(0, 10);
    if (localStorage.getItem(DAY_KEY) === day) return;
    localStorage.setItem(DAY_KEY, day);
  } catch { return; }
  window.setTimeout(() => { void run(); }, delayMs);
}

async function run() {
  try {
    const { get, keys } = await import('idb-keyval');
    const t0 = performance.now();
    const ks = await keys();
    const t1 = performance.now();
    const rq = await get<string>('done-rq-cache');
    const t2 = performance.now();
    const dbs = (await indexedDB.databases?.())?.map((d) => `${d.name}@${d.version}`) || [];
    let store: Record<string, number> | undefined;
    try {
      const est = await navigator.storage?.estimate?.() as (StorageEstimate & { usageDetails?: Record<string, number> }) | undefined;
      if (est) store = { mb: Math.round((est.usage || 0) / 1e6), ...Object.fromEntries(Object.entries(est.usageDetails || {}).map(([k, v]) => [k, Math.round(v / 1e6)])) };
    } catch { /* ignore */ }
    perfLog({ surface: 'web', event: 'site-idb', ms: t2 - t0, extra: {
      keys_ms: Math.round(t1 - t0), rq_ms: Math.round(t2 - t1), rq_kb: Math.round((typeof rq === 'string' ? rq.length : 0) / 1024),
      n_keys: ks.length, dbs, store, path: location.pathname.split('/')[1] || '',
    } });
  } catch { /* ignore */ }
}
