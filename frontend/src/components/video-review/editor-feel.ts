/**
 * エディターの体感を、本人の端末で測ってダンに届ける（2026-11-18）。
 *
 * Mac で外の回線・遅いCPUをまねて測ると軽いのに、本人の Windows では「重い・再生されない」が続いた。
 * ダンが見えていたのは 0.25 秒以上の止まり（editor-freeze）の長さだけで、何が止めているのか・
 * 押してから絵が出るまで何秒待ったのかは見えていなかった。本人の画面で次の物を測り、1分ごとにまとめて送る:
 *   - 止まっている時に位置を動かしてから、その位置の絵が出るまで（seek）
 *   - 再生を押して（再生中に飛んで）映像と音がそろって流れ出すまで（start）
 *   - 再生の途中で映像か音が追いつかず止まった回数と長さ（stalls / frozen_ms）
 *   - 押す・キーを打つ等の操作から画面が変わるまで（input。Event Timing）
 *   - 0.2 秒以上かかったコマで、どの処理がどれだけ使ったか（loaf。Long Animation Frames）
 *   - 端末の手がかり（CPU の数・メモリ・GPU・画面の倍率・取り込みの進み）
 * 送り先は perf_events.jsonl の event "editor-feel"。読むのは scripts/editor_feel_report.py。
 */
import { perfLog } from '@/lib/perf-log';

type Loaf = { ms: number; block: number; at: number; style: number; render: number; scripts: Array<{ what: string; ms: number }> };
type Worst = { ms: number; what: string };

const state = {
  seekMs: [] as number[],
  startMs: [] as number[],
  inputMs: [] as number[],
  inputWorst: [] as Worst[],
  stalls: 0,
  frozenMs: 0,
  loaf: [] as Loaf[],
  pendingSeek: null as null | { t: number; at: number },
};

function on(): boolean {
  return typeof window !== 'undefined' && typeof performance !== 'undefined';
}

/** 止まっている時に利用者が位置を動かした（目盛り・矢印キー・クリップの頭へ飛ぶ） */
export function feelSeek(t: number): void {
  if (!on()) return;
  state.pendingSeek = { t, at: performance.now() };
}

/** プレビューがその時刻の絵を描き終えた */
export function feelDrawn(t: number): void {
  const p = state.pendingSeek;
  if (!p || Math.abs(p.t - t) > 0.06) return;
  state.pendingSeek = null;
  const ms = performance.now() - p.at;
  if (ms < 15000) state.seekMs.push(Math.round(ms));
}

/** 再生を押して（再生中に飛んで）から、映像と音がそろって流れ出すまで */
export function feelStart(ms: number): void {
  state.startMs.push(Math.round(ms));
}

/** 再生の途中で映像か音が追いつかず、止めて待った */
export function feelStall(): void {
  state.stalls += 1;
}

export function feelFrozen(ms: number): void {
  state.frozenMs += ms;
}

function pct(a: number[]) {
  if (!a.length) return null;
  const s = [...a].sort((x, y) => x - y);
  const q = (p: number) => s[Math.min(s.length - 1, Math.floor(s.length * p))];
  return { n: s.length, p50: q(0.5), p90: q(0.9), max: s[s.length - 1] };
}

function scriptName(s: Record<string, unknown>): string {
  const fn = String(s.sourceFunctionName || '');
  const url = String(s.sourceURL || '').split('?')[0].split('/').pop() || '';
  const inv = String(s.invoker || '');
  return [inv.slice(0, 60), fn && `${fn}()`, url && `@${url}:${s.sourceCharPosition ?? ''}`].filter(Boolean).join(' ');
}

let gpuName: string | null | undefined;
function gpu(): string | null {
  if (gpuName !== undefined) return gpuName;
  gpuName = null;
  try {
    const c = document.createElement('canvas');
    const gl = (c.getContext('webgl') || c.getContext('experimental-webgl')) as WebGLRenderingContext | null;
    const ext = gl?.getExtension('WEBGL_debug_renderer_info');
    if (gl && ext) gpuName = String(gl.getParameter(ext.UNMASKED_RENDERER_WEBGL)).slice(0, 120);
  } catch { /* none */ }
  return gpuName;
}

/**
 * 計測を始める。ctx() は送る時に呼ばれ、部屋・作品・クリップ数などを返す。戻り値で止める。
 */
export function startEditorFeel(ctx: () => Record<string, unknown> & { room_id?: string | null }): () => void {
  if (!on()) return () => {};
  const observers: PerformanceObserver[] = [];
  try {
    const o = new PerformanceObserver((list) => {
      for (const e of list.getEntries() as unknown as Array<Record<string, unknown> & PerformanceEntry>) {
        if (e.duration < 200) continue;
        const scripts = ((e.scripts as Array<Record<string, unknown>>) || [])
          .map((s) => ({ what: scriptName(s), ms: Math.round(Number(s.duration) || 0) }))
          .sort((a, b) => b.ms - a.ms)
          .slice(0, 4);
        const rs = Number(e.renderStart) || 0;
        const ss = Number(e.styleAndLayoutStart) || 0;
        state.loaf.push({
          ms: Math.round(e.duration),
          block: Math.round(Number(e.blockingDuration) || 0),
          at: Math.round(e.startTime),
          style: ss ? Math.round(e.startTime + e.duration - ss) : 0,
          render: rs && ss ? Math.round(ss - rs) : 0,
          scripts,
        });
        if (state.loaf.length > 40) state.loaf.sort((a, b) => b.ms - a.ms).splice(20);
      }
    });
    o.observe({ type: 'long-animation-frame', buffered: false } as PerformanceObserverInit);
    observers.push(o);
  } catch { /* Long Animation Frames が無いブラウザ */ }
  try {
    const o = new PerformanceObserver((list) => {
      for (const e of list.getEntries() as unknown as Array<PerformanceEntry & { interactionId?: number; target?: Element | null }>) {
        if (!e.interactionId) continue;
        state.inputMs.push(Math.round(e.duration));
        if (e.duration >= 100) {
          const t = e.target as HTMLElement | null;
          const label = t ? `${t.tagName.toLowerCase()}${t.getAttribute?.('aria-label') ? `:${t.getAttribute('aria-label')}` : t.dataset?.clipId ? ':clip' : t.closest?.('[data-timeline-ruler]') ? ':ruler' : ''}` : '';
          state.inputWorst.push({ ms: Math.round(e.duration), what: `${e.name} ${label}`.slice(0, 80) });
          if (state.inputWorst.length > 30) state.inputWorst.sort((a, b) => b.ms - a.ms).splice(10);
        }
      }
    });
    o.observe({ type: 'event', durationThreshold: 16, buffered: false } as PerformanceObserverInit);
    observers.push(o);
  } catch { /* Event Timing が無いブラウザ */ }

  const flush = () => {
    const any = state.seekMs.length || state.startMs.length || state.stalls || state.loaf.length || state.inputWorst.length;
    if (!any) return;
    const c = ctx();
    const nav = navigator as Navigator & { deviceMemory?: number };
    const lm = (window as unknown as { __localMedia?: { status: () => Record<string, unknown> } }).__localMedia;
    const seek = pct(state.seekMs);
    const start = pct(state.startMs);
    const input = pct(state.inputMs);
    const loaf = [...state.loaf].sort((a, b) => b.ms - a.ms).slice(0, 6);
    const worst = Math.max(seek?.max || 0, start?.max || 0, input?.max || 0, loaf[0]?.ms || 0);
    perfLog({
      surface: 'web',
      event: 'editor-feel',
      ms: worst,
      room_id: (c.room_id as string) || null,
      extra: {
        ...c,
        seek,
        start,
        input,
        input_worst: [...state.inputWorst].sort((a, b) => b.ms - a.ms).slice(0, 5),
        stalls: state.stalls,
        frozen_ms: Math.round(state.frozenMs),
        loaf,
        local_media: lm ? lm.status() : null,
        cores: navigator.hardwareConcurrency || null,
        mem_gb: nav.deviceMemory || null,
        gpu: gpu(),
        dpr: window.devicePixelRatio,
        screen: `${window.innerWidth}x${window.innerHeight}`,
        hidden: document.visibilityState === 'hidden',
      },
    });
    state.seekMs = []; state.startMs = []; state.inputMs = []; state.inputWorst = [];
    state.stalls = 0; state.frozenMs = 0; state.loaf = [];
  };
  const timer = window.setInterval(flush, 60000);
  const onHide = () => { if (document.visibilityState === 'hidden') flush(); };
  document.addEventListener('visibilitychange', onHide);
  window.addEventListener('pagehide', flush);
  return () => {
    flush();
    window.clearInterval(timer);
    document.removeEventListener('visibilitychange', onHide);
    window.removeEventListener('pagehide', flush);
    for (const o of observers) o.disconnect();
  };
}
