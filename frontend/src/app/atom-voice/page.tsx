'use client';

import { useEffect, useState } from 'react';
import { VoiceSession } from '@/components/voice/voice-session';

export default function AtomVoicePage() {
  const [destination, setDestination] = useState<{ roomId: string; title: string } | null>(null);
  const [worker, setWorker] = useState(false);
  const [message, setMessage] = useState('接続すると、この画面を閉じても音声デバイスからダンを使えます。');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (new URLSearchParams(location.search).get('worker') !== '1') return;
    try {
      const config = JSON.parse(localStorage.getItem('dan-atom-wifi') || '{}');
      if (localStorage.getItem('done-token') && config.enabled && config.roomId && config.key) {
        setDestination({ roomId: config.roomId, title: config.title || 'ダンの司令塔' });
        setWorker(true);
      }
      else setMessage('音声用のログイン接続が必要です。');
    } catch { setMessage('音声デバイスの接続設定を確認してください。'); }
  }, []);
  async function stop() {
    setBusy(true);
    try {
      const response = await fetch('/api/v1/chat/refresh/atom-pair?action=stop', { method: 'POST', credentials: 'include' });
      if (!response.ok) throw new Error('停止できませんでした。接続状態を確認してください。');
      setMessage('バックグラウンドの音声を停止しました。');
    } catch (error) { setMessage(error instanceof Error ? error.message : '停止に失敗しました。'); }
    finally { setBusy(false); }
  }
  async function pair() {
    setBusy(true);
    try {
      const response = await fetch('/api/v1/chat/refresh/atom-pair', { method: 'POST', credentials: 'include' });
      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.error || '音声を接続できませんでした。');
      }
      setMessage('ログインを接続しました。専用ブラウザがバックグラウンドで音声を起動します。この画面は閉じて大丈夫です。');
    } catch (error) { setMessage(error instanceof Error ? error.message : '接続に失敗しました。'); }
    finally { setBusy(false); }
  }
  return <main className="mx-auto flex min-h-screen max-w-lg flex-col justify-center gap-6 p-8">
    <h1 className="text-2xl font-semibold">ダンの音声デバイス</h1>
    <p className="text-sm text-muted-foreground">接続先：{destination?.title || 'ダンの司令塔'}</p>
    {worker && destination ? <VoiceSession roomId={destination.roomId} chatTitle={destination.title} onClose={() => setWorker(false)} /> : <>
      <p aria-live="polite">{message}</p>
      <a href="http://localhost:3000/login" className="underline">ダンのログイン画面</a>
      <button disabled={busy} onClick={() => void pair()} className="rounded-lg bg-primary px-5 py-3 text-primary-foreground disabled:opacity-50">
        {busy ? '接続中…' : 'バックグラウンドで接続'}
      </button>
      <button disabled={busy} onClick={() => void stop()} className="rounded-lg border border-border px-5 py-3 disabled:opacity-50">音声を停止</button>
      <p className="text-sm text-muted-foreground">同じ PC 内の専用ブラウザに、ダンのログインを接続します。PC は起動したままお使いください。</p>
    </>}
  </main>;
}
