'use client';

/** 「画面を見せる」: the owner shows a screen, a window or a tab in the call. The pictures stay in this page (screen-frames.ts);
 * the server asks for them only when Jev says a request needs the screen (app/services/voice_owner_screen.py). Dan's
 * own screens (chat, editor) tell where he is without this. */
import { useCallback, useEffect, useRef, useState } from 'react';
import { Monitor, MonitorOff } from 'lucide-react';
import { type ScreenFrame, difference, during, trim } from './screen-frames';

const EVERY_MS = 1000;        // look at the screen once a second
const CHANGED = 0.012;        // a picture is kept when the small thumbnail changed this much
const STILL_MS = 15_000;      // and at least this often while the screen stays the same
const MAX_SIDE = 1600;

function headers(): Record<string, string> {
  const token = typeof localStorage !== 'undefined' ? localStorage.getItem('done-token') || '' : '';
  return { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) };
}

export function CallOwnerScreen({ room, session }: { room: string; session: string }) {
  const [sharing, setSharing] = useState(false);
  const [error, setError] = useState('');
  const streamRef = useRef<MediaStream | null>(null);
  const framesRef = useRef<ScreenFrame[]>([]);
  const runRef = useRef(0);
  const base = `/api/v1/voicelog/live/backend/screen/${encodeURIComponent(room)}`;

  const post = useCallback((path: string, body: Record<string, unknown>, signal?: AbortSignal) =>
    fetch(base + path, { method: 'POST', headers: headers(), body: JSON.stringify({ session_id: session, ...body }), signal }), [base, session]);

  const stop = useCallback(() => {
    runRef.current += 1;
    streamRef.current?.getTracks().forEach(t => t.stop());
    streamRef.current = null;
    framesRef.current = [];
    setSharing(false);
    void post('/stop', {}).catch(() => {});
  }, [post]);

  const start = useCallback(async () => {
    setError('');
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 2 }, audio: false });
    } catch {
      return;   // he chose not to share
    }
    const run = ++runRef.current;
    const live = () => runRef.current === run;
    streamRef.current = stream;
    const track = stream.getVideoTracks()[0];
    const surface = String((track?.getSettings() as { displaySurface?: string })?.displaySurface || '');
    track?.addEventListener('ended', () => { if (live()) stop(); });
    const started = await post('/start', { surface }).catch(() => null);
    if (!started?.ok) {
      stream.getTracks().forEach(t => t.stop()); streamRef.current = null;
      setError('画面を見せる準備ができませんでした');
      return;
    }
    setSharing(true);

    // keep a picture each time the screen changes (only in this page)
    const video = document.createElement('video');
    video.muted = true; video.playsInline = true; video.srcObject = stream;
    void video.play().catch(() => {});
    const thumb = document.createElement('canvas'); thumb.width = 64; thumb.height = 36;
    const full = document.createElement('canvas');
    let last: Uint8ClampedArray | null = null, lastAt = 0;
    const look = () => {
      if (!live()) return;
      const w = video.videoWidth, h = video.videoHeight;
      if (w && h) {
        const t = thumb.getContext('2d', { willReadFrequently: true })!;
        t.drawImage(video, 0, 0, 64, 36);
        const now = Date.now();
        const small = t.getImageData(0, 0, 64, 36).data;
        if (difference(last, small) >= CHANGED || now - lastAt >= STILL_MS) {
          const scale = Math.min(1, MAX_SIDE / Math.max(w, h));
          full.width = Math.round(w * scale); full.height = Math.round(h * scale);
          full.getContext('2d')!.drawImage(video, 0, 0, full.width, full.height);
          const jpeg = full.toDataURL('image/jpeg', 0.72).split(',')[1] || '';
          if (jpeg) framesRef.current = trim([...framesRef.current, { at: now, jpeg, surface }], now);
          last = small; lastAt = now;
        }
      }
      window.setTimeout(look, EVERY_MS);
    };
    look();

    // answer the server when a request needs the screen
    const wait = async () => {
      while (live()) {
        try {
          const response = await post('/wait', {});
          if (!live()) return;
          if (!response.ok) { await new Promise(r => setTimeout(r, 2000)); continue; }
          const { want } = await response.json();
          if (!want) continue;
          const now = Date.now();
          const chosen = during(framesRef.current, now - Number(want.since_ago_ms || 0), now - Number(want.until_ago_ms || 0));
          void post('', { want_id: want.id, frames: chosen.map(f => ({ ago_ms: Math.max(0, Date.now() - f.at), jpeg: f.jpeg, surface: f.surface })) })
            .catch(() => {});
        } catch {
          await new Promise(r => setTimeout(r, 2000));
        }
      }
    };
    void wait();
  }, [post, stop]);

  useEffect(() => () => {   // the call ended: stop showing the screen
    runRef.current += 1;
    streamRef.current?.getTracks().forEach(t => t.stop());
  }, []);

  if (typeof navigator !== 'undefined' && !navigator.mediaDevices?.getDisplayMedia) return null;   // phones: no screen to show
  return (
    <button type="button" aria-pressed={sharing} title={error || undefined}
      aria-label={sharing ? '画面を見せるのをやめる' : '画面を見せる'}
      className={`inline-flex items-center gap-2 rounded-full border px-3 py-2 text-sm ${sharing
        ? 'border-emerald-500/60 bg-emerald-950 text-emerald-100' : 'border-neutral-700 bg-neutral-950 text-neutral-100'}`}
      onClick={() => (sharing ? stop() : void start())}>
      {sharing ? <MonitorOff size={16} /> : <Monitor size={16} />}
      {sharing ? '見せるのをやめる' : (error ? '画面を見せる（もう一度）' : '画面を見せる')}
    </button>
  );
}
