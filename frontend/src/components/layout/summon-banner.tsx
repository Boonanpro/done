'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';

/**
 * ダンが本人を今すぐ呼んでいる間（app/services/owner_summon.py）、PC の画面の上に帯を出して音を鳴らす。
 * 振込の承認や認証コードのように、本人が応じないと作業が止まる時だけ出る。押すとその部屋を開き、呼び出しが止まる。
 * 本人がその部屋に書く・スマホの通知を押す・通話で受けても止まる（帯は次の読み直しで消える）。
 */
type Summon = { id: string; project_id?: string; reason: string; state: string };

function tone(ctx: AudioContext) {
  [880, 1175].forEach((hz, i) => {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.frequency.value = hz;
    gain.gain.setValueAtTime(0.0001, ctx.currentTime + i * 0.25);
    gain.gain.exponentialRampToValueAtTime(0.3, ctx.currentTime + i * 0.25 + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + i * 0.25 + 0.24);
    osc.connect(gain).connect(ctx.destination);
    osc.start(ctx.currentTime + i * 0.25);
    osc.stop(ctx.currentTime + i * 0.25 + 0.25);
  });
}

export function SummonBanner() {
  const router = useRouter();
  const [open, setOpen] = useState<Summon | null>(null);
  const audio = useRef<AudioContext | null>(null);
  const notified = useRef<Set<string>>(new Set());

  useEffect(() => {
    let alive = true;
    const read = async () => {
      const token = localStorage.getItem('done-token');
      if (!token) return;
      try {
        const res = await fetch('/api/v1/summon/active', { headers: { Authorization: `Bearer ${token}` } });
        if (!res.ok) return;
        const rows: Summon[] = (await res.json()).summons || [];
        const ringing = rows.find((s) => s.state === 'open') || null;
        if (!alive) return;
        setOpen(ringing);
        if (ringing && !notified.current.has(ringing.id) && 'Notification' in window && Notification.permission === 'granted') {
          notified.current.add(ringing.id);
          new Notification('ダンが呼んでいます', { body: ringing.reason, tag: ringing.id, requireInteraction: true });
        }
      } catch {
        // 読めない時は前の状態のまま（次の読み直しで戻る）
      }
    };
    void read();
    const timer = window.setInterval(read, 4000);
    return () => { alive = false; window.clearInterval(timer); };
  }, []);

  useEffect(() => {
    if (!open) return;
    const ring = () => {
      try {
        audio.current = audio.current || new AudioContext();
        if (audio.current.state === 'suspended') void audio.current.resume();
        tone(audio.current);
      } catch {}
    };
    ring();
    const timer = window.setInterval(ring, 3000);
    const title = document.title;
    document.title = 'ダンが呼んでいます';
    return () => { window.clearInterval(timer); document.title = title; };
  }, [open]);

  if (!open) return null;
  const answer = () => {
    const token = localStorage.getItem('done-token');
    void fetch(`/api/v1/summon/${open.id}/answer`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }).catch(() => {});
    if ('Notification' in window && Notification.permission === 'default') void Notification.requestPermission().catch(() => {});
    setOpen(null);
    if (open.project_id) router.push(`/chat/${open.project_id}`);
  };
  return (
    <button
      type="button"
      onClick={answer}
      aria-label="ダンからの呼び出し"
      className="fixed left-1/2 top-3 z-[1000] flex max-w-[min(640px,92vw)] -translate-x-1/2 items-center gap-3 rounded-2xl bg-amber-400 px-5 py-3 text-left text-[15px] font-semibold text-neutral-950 shadow-2xl ring-4 ring-amber-300/60"
    >
      <span className="h-2.5 w-2.5 shrink-0 animate-pulse rounded-full bg-red-600" />
      <span className="min-w-0">{open.reason}</span>
    </button>
  );
}
