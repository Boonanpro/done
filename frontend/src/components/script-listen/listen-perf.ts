'use client';

// 台本を聞く画面が開く速さを、本人の端末そのもので測って残す（2026-11-21 本人「台本読み上げページも遅いから直せ」）。
// 開発室で、こちらの試しのブラウザでは出ない遅さが本人の Chrome でだけ出た（端末の控えの溜まり）ので、同じく本人の
// 端末から /chat/perf に event=script-listen-open を送る。t はページを開いた瞬間からのミリ秒:
//   module=この画面のプログラムが読めた / idb0,idb1=前回の控えを読み始め・読み終え / doc0,doc1=台本を問い合わせ・届いた /
//   text=文が見えた（控えか本物）/ editable=打てる文が出た / comments=コメント / room=横の会話の部屋 / chat=会話の欄が使える /
//   imgs=サムネの絵が描けた。
import { perfLog } from '@/lib/perf-log';

const born = typeof performance !== 'undefined' ? performance.now() : 0;
const marks: Record<string, number> = {};
const info: Record<string, unknown> = {};
let sent = false;
let started = false;

export function mark(name: string) {
  if (typeof performance === 'undefined' || name in marks) return;
  marks[name] = Math.round(performance.now());
}

export function note(key: string, value: unknown) { info[key] = value; }

/** Starts the report once per page: when the text can be typed in and the side chat is usable (or 20 s), it is sent. */
export function startReport(docId: string) {
  if (started || typeof window === 'undefined') return;
  started = true;
  marks.module = Math.round(born);
  const seenKey = 'script-listen-opened';
  let first = false;
  try { first = !localStorage.getItem(seenKey); localStorage.setItem(seenKey, '1'); } catch { /* ignore */ }
  const t0 = performance.now();
  const poll = window.setInterval(() => {
    if (!('chat' in marks)) {
      const c = document.querySelector('[data-testid="script-chat"]');
      if (c && c.querySelector('textarea') && !c.textContent?.includes('呼んでいます')) mark('chat');
    }
    const done = 'editable' in marks && 'imgs' in marks && ('chat' in marks || !document.querySelector('[data-testid="script-chat"]'));
    if (done || performance.now() - t0 > 20000) {
      window.clearInterval(poll);
      void send(docId, first);
    }
  }, 100);
}

async function send(docId: string, first: boolean) {
  if (sent) return;
  sent = true;
  const nav = performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming | undefined;
  const res = performance.getEntriesByType('resource') as PerformanceResourceTiming[];
  const js = res.filter(r => r.name.includes('/_next/'));
  const extra: Record<string, unknown> = {
    doc: docId.slice(0, 12),
    t: { ...marks },
    first,
    sw: !!navigator.serviceWorker?.controller,
    nav: nav ? { ttfb: Math.round(nav.responseStart), dcl: Math.round(nav.domContentLoadedEventEnd), type: nav.type } : null,
    js: { n: js.length, kb: Math.round(js.reduce((s, r) => s + (r.transferSize || 0), 0) / 1024), end: Math.round(Math.max(0, ...js.map(r => r.responseEnd))) },
    wide: window.innerWidth,
    ...info,
  };
  try {
    const est = await navigator.storage?.estimate?.() as (StorageEstimate & { usageDetails?: Record<string, number> }) | undefined;
    if (est) extra.store = { mb: Math.round((est.usage || 0) / 1e6), ...Object.fromEntries(Object.entries(est.usageDetails || {}).map(([k, v]) => [k, Math.round(v / 1e6)])) };
  } catch { /* ignore */ }
  perfLog({ surface: 'web', event: 'script-listen-open', ms: marks.editable ?? marks.text ?? -1, extra });
  void probeStore();
}

/** Once a day per device: how heavy the site's IndexedDB is to read (the chat's kept copy lives there). 11/21 the side
 * chat waited 5–8 s for it on the owner's Chrome. */
async function probeStore() {
  try {
    const day = new Date().toISOString().slice(0, 10);
    if (localStorage.getItem('script-listen-idb-probe') === day) return;
    localStorage.setItem('script-listen-idb-probe', day);
    const { get, keys } = await import('idb-keyval');
    const t0 = performance.now();
    const ks = await keys();
    const t1 = performance.now();
    const rq = await get<string>('done-rq-cache');
    const t2 = performance.now();
    const dbs = (await indexedDB.databases?.())?.map(d => d.name) || [];
    perfLog({ surface: 'web', event: 'script-listen-idb', ms: t2 - t0, extra: {
      keys_ms: Math.round(t1 - t0), rq_ms: Math.round(t2 - t1), rq_kb: Math.round((typeof rq === 'string' ? rq.length : 0) / 1024),
      n_keys: ks.length, listen_keys: ks.filter(k => String(k).startsWith('script-listen-doc-')).length, dbs,
    } });
  } catch { /* ignore */ }
}
