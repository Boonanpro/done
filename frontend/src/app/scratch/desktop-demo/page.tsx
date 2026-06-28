'use client';

// A3 (look-first): a production-tab-style editor UI served by Next.js, loaded by the desktop
// shell's composition WebView2. The shell composites the native GES video on top of the
// #preview box, positioned from the rect this page posts (device px). Dummy data only — the
// real production-workspace component + live backend is the deferred "本接続" step.

import { useEffect } from 'react';

export default function DesktopDemo() {
  useEffect(() => {
    const post = () => {
      const el = document.getElementById('preview');
      if (!el) return;
      const r = el.getBoundingClientRect();
      const d = window.devicePixelRatio || 1;
      const msg = JSON.stringify({
        x: Math.round(r.left * d),
        y: Math.round(r.top * d),
        w: Math.round(r.width * d),
        h: Math.round(r.height * d),
      });
      // present only inside the desktop shell; harmless no-op in a browser
      (window as unknown as { chrome?: { webview?: { postMessage(m: string): void } } })
        .chrome?.webview?.postMessage(msg);
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
  }, []);

  return (
    <div className="fixed inset-0 flex flex-col overflow-hidden bg-[#15151a] text-zinc-200 select-none">
      <header className="flex h-12 shrink-0 items-center gap-3 border-b border-black/60 bg-[#26262e] px-4">
        <span className="h-2.5 w-2.5 rounded-full bg-red-500" />
        <span className="font-semibold">制作タブ — Desktop</span>
        <span className="text-xs text-zinc-400">StyleUp UGC 01</span>
        <div className="ml-auto flex gap-2">
          <button className="rounded bg-zinc-700 px-3 py-1 text-sm hover:bg-zinc-600">プレビュー</button>
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
        <div className="mb-1 px-1 text-[10px] text-zinc-500">タイムライン</div>
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
      </footer>
    </div>
  );
}
