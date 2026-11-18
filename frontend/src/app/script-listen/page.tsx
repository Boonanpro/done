'use client';

// 台本を読み上げで聞いて、その場で直す画面（2026-11-18）。/script-listen?doc=<GoogleドキュメントのID かURL>。
// 中身は components/script-listen/listen-screen.tsx、裏側は app/api/script_listen_screen.py。
import { Suspense, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';

import { ListenScreen } from '@/components/script-listen/listen-screen';

function docIdFrom(value: string) {
  const m = value.match(/\/document\/d\/([A-Za-z0-9_-]+)/);
  return (m ? m[1] : value).trim();
}

function Picker() {
  const router = useRouter();
  const [value, setValue] = useState('');
  return (
    <div className="mx-auto max-w-xl p-6">
      <h1 className="text-lg font-bold">台本を聞く</h1>
      <p className="mt-2 text-[14px] text-stone-600">台本のGoogleドキュメントのURLを入れてください。</p>
      <form
        className="mt-4 flex gap-2"
        onSubmit={e => {
          e.preventDefault();
          const id = docIdFrom(value);
          if (id) router.push(`/script-listen?doc=${encodeURIComponent(id)}`);
        }}
      >
        <input
          value={value}
          onChange={e => setValue(e.target.value)}
          placeholder="https://docs.google.com/document/d/…"
          className="min-w-0 flex-1 rounded-md border border-stone-300 px-3 py-2 text-[16px]"
        />
        <button type="submit" className="rounded-md bg-amber-600 px-4 py-2 font-semibold text-white">開く</button>
      </form>
    </div>
  );
}

function Inner() {
  const params = useSearchParams();
  const doc = docIdFrom(params.get('doc') || '');
  return doc ? <ListenScreen key={doc} docId={doc} /> : <Picker />;
}

export default function ScriptListenPage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-stone-500">読んでいます…</div>}>
      <div className="h-dvh bg-[#faf8f4] text-stone-900"><Inner /></div>
    </Suspense>
  );
}
