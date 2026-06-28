'use client';

// A3 + real-edit (look-first): the desktop shell reads the real room timeline (contents.json),
// hands it to this page on 'ready', and routes edits back to the GES engine (apply_edit).
// The bottom timeline shows the ACTUAL clips; drag to move, drag the right edge to trim, and
// use 分割 / 削除 on the selected clip. Scrub by clicking/dragging empty timeline. Dummy assets.

import { useEffect, useRef, useState } from 'react';

type Clip = { id: string; track: 'video' | 'overlay' | 'audio'; start: number; end: number };

function fmt(s: number) {
  s = Math.max(0, Math.floor(s));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

const LANES: { key: Clip['track']; label: string; cls: string }[] = [
  { key: 'video', label: '映像', cls: 'bg-sky-600/80' },
  { key: 'overlay', label: 'PiP', cls: 'bg-purple-600/80' },
  { key: 'audio', label: '音声', cls: 'bg-emerald-600/80' },
];

export default function DesktopDemo() {
  const [playing, setPlaying] = useState(true);
  const [frac, setFrac] = useState(0);
  const [duration, setDuration] = useState(361);
  const [clips, setClips] = useState<Clip[]>([]);
  const [sel, setSel] = useState<string | null>(null);
  const trackRef = useRef<HTMLDivElement>(null);
  const scrubbing = useRef(false);
  const drag = useRef<null | { id: string; mode: 'move' | 'trim'; x0: number; s0: number; e0: number }>(null);

  const send = (o: Record<string, unknown>) => {
    (window as unknown as { chrome?: { webview?: { postMessage(m: string): void } } })
      .chrome?.webview?.postMessage(JSON.stringify(o));
  };

  // report the #preview rect (device px) + ask the shell for the real timeline
  useEffect(() => {
    const post = () => {
      const el = document.getElementById('preview');
      if (!el) return;
      const r = el.getBoundingClientRect();
      const d = window.devicePixelRatio || 1;
      send({ x: Math.round(r.left * d), y: Math.round(r.top * d), w: Math.round(r.width * d), h: Math.round(r.height * d) });
    };
    post();
    const id = window.setInterval(post, 200);
    window.addEventListener('resize', post);
    const el = document.getElementById('preview');
    const ro = new ResizeObserver(post);
    if (el) ro.observe(el);
    send({ cmd: 'ready' }); // request the real clips
    return () => {
      window.clearInterval(id);
      window.removeEventListener('resize', post);
      ro.disconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // messages from the shell: 'space' (toggle) or the timeline JSON
  useEffect(() => {
    const wv = (window as unknown as { chrome?: { webview?: { addEventListener(t: string, h: (e: { data: unknown }) => void): void; removeEventListener(t: string, h: (e: { data: unknown }) => void): void } } }).chrome?.webview;
    if (!wv) return;
    const onMsg = (e: { data: unknown }) => {
      if (e.data === 'space') {
        setPlaying((p) => {
          const np = !p;
          send({ cmd: np ? 'play' : 'pause' });
          return np;
        });
        return;
      }
      try {
        const d = JSON.parse(String(e.data));
        if (d?.type === 'timeline' && Array.isArray(d.clips)) {
          setClips(d.clips as Clip[]);
          if (typeof d.duration === 'number' && d.duration > 0) setDuration(d.duration);
        }
      } catch {
        /* not JSON */
      }
    };
    wv.addEventListener('message', onMsg);
    return () => wv.removeEventListener('message', onMsg);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // advance the playhead locally while playing (approximate; the real seeks are exact)
  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    let prev = performance.now();
    const loop = (now: number) => {
      const dt = (now - prev) / 1000;
      prev = now;
      setFrac((f) => Math.min(1, f + dt / duration));
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [playing, duration]);

  const fracFromX = (clientX: number) => {
    const el = trackRef.current;
    if (!el) return 0;
    const r = el.getBoundingClientRect();
    return Math.min(1, Math.max(0, (clientX - r.left) / r.width));
  };

  // scrub on empty timeline
  const onTrackDown = (e: React.PointerEvent) => {
    scrubbing.current = true;
    (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
    const f = fracFromX(e.clientX);
    setFrac(f);
    send({ cmd: 'seek', pos: f * duration });
  };
  const onTrackMove = (e: React.PointerEvent) => {
    if (!scrubbing.current) return;
    const f = fracFromX(e.clientX);
    setFrac(f);
    send({ cmd: 'seek', pos: f * duration });
  };
  const onTrackUp = () => {
    scrubbing.current = false;
  };

  // clip drag (move / trim)
  const onClipDown = (e: React.PointerEvent, c: Clip, mode: 'move' | 'trim') => {
    e.stopPropagation();
    setSel(c.id);
    drag.current = { id: c.id, mode, x0: e.clientX, s0: c.start, e0: c.end };
    (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
  };
  const onClipMove = (e: React.PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    const el = trackRef.current;
    if (!el) return;
    const dsec = ((e.clientX - d.x0) / el.getBoundingClientRect().width) * duration;
    setClips((cs) =>
      cs.map((c) => {
        if (c.id !== d.id) return c;
        if (d.mode === 'move') {
          const len = d.e0 - d.s0;
          const ns = Math.max(0, d.s0 + dsec);
          return { ...c, start: ns, end: ns + len };
        }
        const ne = Math.max(d.s0 + 0.4, Math.min(duration, d.e0 + dsec));
        return { ...c, end: ne };
      }),
    );
  };
  const onClipUp = () => {
    const d = drag.current;
    drag.current = null;
    if (!d) return;
    const c = clips.find((x) => x.id === d.id);
    if (!c) return;
    if (d.mode === 'move') send({ cmd: 'move', id: c.id, v: c.start });
    else send({ cmd: 'trim', id: c.id, v: c.end - c.start });
  };

  const toggle = () =>
    setPlaying((p) => {
      const np = !p;
      send({ cmd: np ? 'play' : 'pause' });
      return np;
    });

  const splitSel = () => {
    if (!sel) return;
    const at = frac * duration;
    const c = clips.find((x) => x.id === sel);
    if (!c || at <= c.start + 0.2 || at >= c.end - 0.2) return;
    send({ cmd: 'split', id: sel, v: at });
    setClips((cs) => cs.flatMap((x) => (x.id === sel ? [{ ...x, end: at }, { ...x, id: `${x.id}__b`, start: at }] : [x])));
  };
  const deleteSel = () => {
    if (!sel) return;
    send({ cmd: 'delete', id: sel });
    setClips((cs) => cs.filter((x) => x.id !== sel));
    setSel(null);
  };

  // keyboard shortcuts: Space = play/pause, S = split, Delete/Backspace = delete
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA')) return;
      if (e.code === 'Space') {
        e.preventDefault();
        toggle();
      } else if (e.key === 's' || e.key === 'S') {
        e.preventDefault();
        splitSel();
      } else if (e.key === 'Delete' || e.key === 'Backspace') {
        e.preventDefault();
        deleteSel();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sel, frac, clips, duration, playing]);

  return (
    <div className="fixed inset-0 flex flex-col overflow-hidden bg-[#15151a] text-zinc-200 select-none">
      <header className="flex h-12 shrink-0 items-center gap-3 border-b border-black/60 bg-[#26262e] px-4">
        <span className="h-2.5 w-2.5 rounded-full bg-red-500" />
        <span className="font-semibold">制作タブ — Desktop</span>
        <span className="text-xs text-zinc-400">StyleUp UGC 01</span>
        <div className="ml-auto flex items-center gap-2">
          <button onClick={toggle} className="w-9 rounded bg-zinc-700 px-2 py-1 text-sm hover:bg-zinc-600" title={playing ? '一時停止' : '再生'}>
            {playing ? '⏸' : '▶'}
          </button>
          <span className="tabular-nums text-xs text-zinc-400">{fmt(frac * duration)} / {fmt(duration)}</span>
          <button className="rounded bg-blue-600 px-3 py-1 text-sm hover:bg-blue-500">書き出し</button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <aside className="w-56 shrink-0 overflow-y-auto border-r border-black/60 bg-[#22222a] p-3">
          <div className="mb-2 text-xs font-semibold text-zinc-400">素材</div>
          <div className="grid grid-cols-2 gap-2">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="flex aspect-video items-center justify-center rounded border border-black/40 bg-zinc-700/70 text-[10px] text-zinc-400">
                clip {i + 1}
              </div>
            ))}
          </div>
        </aside>

        <main className="flex min-w-0 flex-1 items-center justify-center bg-[#15151a] p-5">
          <div id="preview" className="relative flex aspect-[9/16] h-full max-h-full max-w-full items-center justify-center rounded-lg border-2 border-blue-500/70 bg-black/40 shadow-[0_0_0_4px_rgba(59,130,246,0.15)]">
            <span className="text-xs text-zinc-500">プレビュー（ネイティブ映像）</span>
          </div>
        </main>
      </div>

      <footer className="h-36 shrink-0 overflow-hidden border-t border-black/60 bg-[#1d1d24] p-2">
        <div className="mb-1 flex items-center justify-between px-1">
          <span className="text-[10px] text-zinc-500">
            タイムライン（{clips.length}クリップ・クリップ=ドラッグ移動/右端=トリム・空白=シーク）
          </span>
          <div className="flex items-center gap-2">
            <button onClick={splitSel} disabled={!sel} className="rounded bg-zinc-700 px-2 py-0.5 text-[11px] hover:bg-zinc-600 disabled:opacity-40" title="再生ヘッド位置で分割">
              分割
            </button>
            <button onClick={deleteSel} disabled={!sel} className="rounded bg-red-700/80 px-2 py-0.5 text-[11px] hover:bg-red-600 disabled:opacity-40" title="選択クリップを削除">
              削除
            </button>
            <span className="tabular-nums text-[10px] text-zinc-400">{fmt(frac * duration)}</span>
          </div>
        </div>

        <div className="flex gap-1">
          <div className="flex w-10 shrink-0 flex-col gap-1">
            {LANES.map((l) => (
              <div key={l.key} className="flex h-6 items-center text-[10px] text-zinc-500">{l.label}</div>
            ))}
          </div>
          <div ref={trackRef} onPointerDown={onTrackDown} onPointerMove={onTrackMove} onPointerUp={onTrackUp} className="relative flex-1 cursor-pointer">
            <div className="flex flex-col gap-1">
              {LANES.map((l) => (
                <div key={l.key} className="relative h-6 overflow-hidden rounded bg-black/20">
                  {clips
                    .filter((c) => c.track === l.key)
                    .map((c) => (
                      <div
                        key={c.id}
                        onPointerDown={(e) => onClipDown(e, c, 'move')}
                        onPointerMove={onClipMove}
                        onPointerUp={onClipUp}
                        className={`absolute top-0 h-6 cursor-grab rounded-sm border ${l.cls} ${
                          sel === c.id ? 'z-10 border-white' : 'border-black/30'
                        }`}
                        style={{ left: `${(c.start / duration) * 100}%`, width: `${Math.max(0.25, ((c.end - c.start) / duration) * 100)}%` }}
                      >
                        <div
                          onPointerDown={(e) => onClipDown(e, c, 'trim')}
                          onPointerMove={onClipMove}
                          onPointerUp={onClipUp}
                          className="absolute right-0 top-0 h-full w-1 cursor-ew-resize bg-white/40"
                        />
                      </div>
                    ))}
                </div>
              ))}
            </div>
            {/* playhead — same coordinate space as the clip lanes */}
            <div className="pointer-events-none absolute inset-y-0 w-0.5 bg-red-500" style={{ left: `${frac * 100}%` }}>
              <div className="absolute -left-1 -top-1 h-2 w-2 rounded-full bg-red-500" />
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}
