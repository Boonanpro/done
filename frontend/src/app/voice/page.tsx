'use client';

/**
 * 音声会話の単体ページ（チャット外から直接アクセスする場合用）。
 *
 * 通常はチャット内ヘッダーの「音声」ボタンからフローティングパネルとして開かれる
 * （UI 切替なしで会話できる）。このページは
 *   - モバイルブラウザから本番URLで直接開く
 *   - `/voice?room=xxx` でディープリンクする
 * といったケース向けに残してある。
 */
import { useEffect, useState } from 'react';
import Link from 'next/link';

import { VoiceConsole } from '@/components/voice/voice-console';

export default function VoicePage() {
  const [roomId, setRoomId] = useState<string | undefined>(undefined);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const r = new URLSearchParams(window.location.search).get('room');
    if (r) setRoomId(r);
  }, []);

  return (
    <main className="flex min-h-screen flex-col items-center bg-neutral-950 px-4 py-6 text-neutral-100">
      <div className="w-full max-w-md">
        <Link
          href="/chat"
          className="mb-3 inline-flex items-center gap-1 text-xs text-neutral-400 transition hover:text-neutral-100"
        >
          <span aria-hidden>←</span> ダンに戻る
        </Link>
        <div className="rounded-2xl border border-neutral-800 bg-neutral-950 shadow-2xl">
          <VoiceConsole roomId={roomId} />
        </div>
      </div>
    </main>
  );
}
