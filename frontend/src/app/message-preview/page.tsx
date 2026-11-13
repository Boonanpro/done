'use client';

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import { StageMessageCard } from '@/components/voice/voice-stage';

function Preview() {
  const id = useSearchParams().get('proposal') || '';
  if (!id) return <p>確認する下書きが指定されていません。</p>;
  return <StageMessageCard key={id} card={{ proposal_id: id, status: 'pending', channel: '', to: '', body: '' }} />;
}

export default function MessagePreviewPage() {
  return <main className="dark min-h-[100dvh] bg-neutral-950 px-3 py-4 text-foreground">
    <div className="mx-auto w-full max-w-2xl">
      <h1 className="mb-1 text-lg font-semibold">投稿・送信内容の確認</h1>
      <p className="mb-4 text-sm text-neutral-400">本文をタップして編集し、保存できます。</p>
      <Suspense fallback={<p>読み込み中…</p>}><Preview /></Suspense>
    </div>
  </main>;
}
