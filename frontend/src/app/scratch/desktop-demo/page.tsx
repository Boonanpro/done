'use client';

// A3 (look-first): a production-tab-style editor UI served by Next.js, loaded by the desktop
// shell's composition WebView2. The shell composites the native GES video on top of the
// #preview box (rect posted below in device px) and routes transport commands to the engine.
// Scrubbing is timeline-direct: click/drag the bottom timeline to seek. Dummy data only.

import { useEffect, useRef, useState } from 'react';

const DURATION = 361; // timeline length (s) — matches the room content (~360.9s)

function fmt(s: number) {
  s = Math.max(0, Math.floor(s));
  const m = Math.floor(s / 60);
  const ss = s % 60;
  return `${m}:${String(ss).padStart(2, '0')}`;
}

export default function DesktopDemo() {
  const [playing, setPlaying] = useState(true);
  const [frac, setFrac] = useState(0);
  const trackRef = useRef<HTMLDivElement>(null);
  const scrubbing = useRef(false);

  const send = (o: Record<string, unknown>) => {
    (window as unknown as { chrome?: { webview?: { postMessage(m: string): void } } })
      .chrome?.webview?.postMessage(JSON.stringify(o));
  };

  // report the #preview rect (device px) so the shell can place the native video on it
  useEffect(() => {
    const post = () => {
      const el = document.getElementById('preview');
      if (!el) return;
      const r = el.getBoundingClientRect();
      const d = window.devicePixelRatio || 1;
      send({
        x: Math.round(r.left * d),
        y: Math.round(r.top * d),
        w: Math.round(r.width * d),
        h: Math.round(r.height * d),
      });
    };
    post();
    const id = window.setInterval(post, 200);
    window.addEventListener('resize', post);
    const el = document.getElementById('preview');
    const ro = new ResizeObserver(post);
    if (el) ro.observe(el);
    return () => {
      window.clearInterval(id);
      window.removeEventListener('resize', post);
      ro.disconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // advance the playhead locally while playing (approximate; the actual seeks are exact)
  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      setFrac((f) => Math.min(1, f + dt / DURATION));
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing]);

  // spacebar relayed from the desktop shell → toggle play/pause
  useEffect(() => {
    const wv = (
      window as unknown as {
        chrome?: {
          webview?: {
            addEventListener(t: string, h: (e: { data: unknown }) => void): void;
            removeEventListener(t: string, h: (e: { data: unknown }) => void): void;
          };
        };
      }
    ).chrome?.webview;
    if (!wv) return;
    const onMsg = (e: { data: unknown }) => {
      if (e.data === 'space')
        setPlaying((p) => {
          const np = !p;
          send({ cmd: np ? 'play' : 'pause' });
          return np;
        });
    };
    wv.addEventListener('message', onMsg);
    return () => wv.removeEventListener('message', onMsg);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const seekToClientX = (clientX: number) => {
    const el = trackRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const f = Math.min(1, Math.max(0, (clientX - r.left) / r.width));
    setFrac(f);
    send({ cmd: 'seek', pos: f * DURATION });
  };
  const onDown = (e: React.PointerEvent) => {
    scrubbing.current = true;
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
    seekToClientX(e.clientX);
  };
  const onMove = (e: React.PointerEvent) => {
    if (scrubbing.current) seekToClientX(e.clientX);
  };
  const onUp = () => {
    scrubbing.current = false;
  };

  const toggle = (p: boolean) => {
    setPlaying(p);
    send({ cmd: p ? 'play' : 'pause' });
  };

  return (
    <div className="fixed inset-0 flex flex-col overflow-hidden bg-[#15151a] text-zinc-200 select-none">
      <header className="flex h-12 shrink-0 items-center gap-3 border-b border-black/60 bg-[#26262e] px-4">
        <span className="h-2.5 w-2.5 rounded-full bg-red-500" />
        <span className="font-semibold">制作タブ — Desktop</span>
        <span className="text-xs text-zinc-400">StyleUp UGC 01</span>
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={() => toggle(!playing)}
            className="w-9 rounded bg-zinc-700 px-2 py-1 text-sm hover:bg-zinc-600"
            title={playing ? '一時停止' : '再生'}
          >
            {playing ? '⏸' : '▶'}
          </button>
          <span className="tabular-nums text-xs text-zinc-400">
            {fmt(frac * DURATION)} / {fmt(DURATION)}
          </span>
          <button className="rounded bg-blue-600 px-3 py-1 text-sm hover:bg-blue-500">書き出し</button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <aside className="w-56 shrink-0 overflow-y-auto border-r border-black/60 bg-[#22222a] p-3">
          <div className="mb-2 text-xs font-semibold text-zinc-400">素材</div>
          <div className="grid grid-cols-2 gap-2">
            {Array.from({ length: 6 }).map((_, i) => (
              <div
                key={i}
                className="flex aspect-video items-center justify-center rounded border border-black/40 bg-zinc-700/70 text-[10px] text-zinc-400"
              >
                clip {i + 1}
              </div>
            ))}
          </div>
        </aside>

        <main className="flex min-w-0 flex-1 items-center justify-center bg-[#15151a] p-5">
          <div
            id="preview"
            className="relative flex aspect-[9/16] h-full max-h-full max-w-full items-center justify-center rounded-lg border-2 border-blue-500/70 bg-black/40 shadow-[0_0_0_4px_rgba(59,130,246,0.15)]"
          >
            <span className="text-xs text-zinc-500">プレビュー（ネイティブ映像）</span>
          </div>
        </main>
      </div>

      <footer className="h-32 shrink-0 overflow-hidden border-t border-black/60 bg-[#1d1d24] p-2">
        <div className="mb-1 flex items-center justify-between px-1">
          <span className="text-[10px] text-zinc-500">タイムライン（クリック / ドラッグでシーク）</span>
          <span className="tabular-nums text-[10px] text-zinc-400">{fmt(frac * DURATION)}</span>
        </div>
        <div
          ref={trackRef}
          onPointerDown={onDown}
          onPointerMove={onMove}
          onPointerUp={onUp}
          className="relative cursor-pointer select-none"
        >
          <div className="space-y-1">
            {['映像', 'PiP', '音声'].map((lane, li) => (
              <div key={li} className="flex h-7 items-center gap-1">
                <div className="w-10 shrink-0 text-[10px] text-zinc-500">{lane}</div>
                <div className="flex flex-1 gap-0.5 overflow-hidden">
                  {Array.from({ length: 18 - li * 2 }).map((_, i) => (
                    <div
                      key={i}
                      className={`h-6 rounded-sm ${
                        li === 0 ? 'bg-sky-700/70' : li === 1 ? 'bg-purple-700/70' : 'bg-emerald-700/70'
                      }`}
                      style={{ width: `${30 + ((i * 7) % 40)}px` }}
                    />
                  ))}
                </div>
              </div>
            ))}
          </div>
          {/* playhead — same full-track coordinate space as the seek calc, so it sits exactly
              under the cursor */}
          <div
            className="pointer-events-none absolute bottom-0 top-0 w-0.5 bg-red-500"
            style={{ left: `${frac * 100}%` }}
          >
            <div className="absolute -left-1 -top-1 h-2 w-2 rounded-full bg-red-500" />
          </div>
        </div>
      </footer>
    </div>
  );
}
