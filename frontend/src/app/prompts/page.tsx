'use client';

// ダンを動かしている指示文の画面（2026-11-17）。中身は components/prompts/prompts-screen.tsx（開発室のボードの「指示文」と同じ物）。
// URL の ?place=<図の箱>&id=<文> で、その箱・その文を開いたまま共有できる。
// ダンの画面は html と body のスクロールを止めているので、この画面は自分の枠でスクロールする（11/17 まではスクロールできず、
// 全文の欄まで行けなかった＝本人「見るだけで編集できない」）。
import { Suspense } from 'react';
import { usePathname, useSearchParams } from 'next/navigation';

import { PromptsScreen } from '@/components/prompts/prompts-screen';

function PromptsInner() {
  const params = useSearchParams();
  const path = usePathname();
  const go = (next: { place: string; id?: string }) => {
    const q = new URLSearchParams(window.location.search);
    q.delete('id');
    q.set('place', next.place);
    if (next.id) q.set('id', next.id);
    window.history.replaceState(null, '', window.location.pathname + '?' + q.toString());
  };
  return (
    <div className="h-dvh overflow-y-auto overscroll-contain bg-[#faf8f4] text-stone-900 lg:overflow-hidden">
      <PromptsScreen initialCircuit={path === '/prompts/circuit' || params.get('circuit') === '1'} place={params.get('place') || ''} id={params.get('id') || ''} onGo={go} />
    </div>
  );
}

export default function PromptsPage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-stone-500">読んでいます…</div>}>
      <PromptsInner />
    </Suspense>
  );
}
