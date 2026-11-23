'use client';

import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { PointerEvent } from 'react';
import { Circle, Eraser, ImagePlus, Mic, Pencil, Square, Undo2, X } from 'lucide-react';
import type { ThumbMark } from '@/components/thumbnail/thumb-doc';
import { QUIET_SPEECH_MIC } from '@/components/voice/quiet-speech';

const WIDTH = 1280, HEIGHT = 800;
const colors = [['墨', '#292c36'], ['赤', '#c83d46'], ['青', '#315dc5'], ['緑', '#258366']];
type Mark = ThumbMark & { erase?: boolean };
type Props = {
  room: string;
  session: string | null;
  voiceOpen: boolean;
  onVoice: (open: boolean) => void;
  onAttach: (file: File) => Promise<void>;
  onClose: () => void;
};

function paint(ctx: CanvasRenderingContext2D, mark: Mark) {
  ctx.strokeStyle = mark.color;
  ctx.lineWidth = mark.width;
  ctx.lineJoin = ctx.lineCap = 'round';
  ctx.beginPath();
  const [x, y] = mark.points[0];
  ctx.moveTo(x - .01, y);
  for (const point of mark.points) ctx.lineTo(...point);
  ctx.stroke();
}

export function SketchBoard({ room, session, voiceOpen, onVoice, onAttach, onClose }: Props) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const ink = useRef<HTMLCanvasElement | null>(null);
  const image = useRef<HTMLImageElement | null>(null);
  const marks = useRef<Mark[]>([]);
  const active = useRef<number | null>(null);
  const version = useRef(0);
  const input = useRef<HTMLInputElement>(null);
  const alive = useRef(true);
  const media = useRef<MediaStream | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const [color, setColor] = useState(colors[0][1]);
  const [erase, setErase] = useState(false);
  const [hasBackground, setHasBackground] = useState(false);
  const [count, setCount] = useState(0);
  const [recordState, setRecordState] = useState<'idle' | 'starting' | 'recording' | 'stopping'>('idle');
  const [clip, setClip] = useState<File | null>(null);
  const [seconds, setSeconds] = useState(0);
  const [busy, setBusy] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [error, setError] = useState('');
  const [discard, setDiscard] = useState(false);

  function draw() {
    const ctx = canvas.current?.getContext('2d');
    if (!ctx) return;
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, WIDTH, HEIGHT);
    if (image.current) {
      const img = image.current;
      const scale = Math.min(WIDTH / img.naturalWidth, HEIGHT / img.naturalHeight);
      const w = img.naturalWidth * scale, h = img.naturalHeight * scale;
      ctx.drawImage(img, (WIDTH - w) / 2, (HEIGHT - h) / 2, w, h);
    }
    if (ink.current) ctx.drawImage(ink.current, 0, 0);
    version.current++;
  }

  function stroke(mark: Mark) {
    const ctx = ink.current?.getContext('2d');
    if (!ctx) return;
    ctx.globalCompositeOperation = mark.erase ? 'destination-out' : 'source-over';
    paint(ctx, mark);
    draw();
  }

  function undo() {
    marks.current.pop();
    const ctx = ink.current?.getContext('2d');
    ctx?.clearRect(0, 0, WIDTH, HEIGHT);
    for (const mark of marks.current) {
      if (!ctx) break;
      ctx.globalCompositeOperation = mark.erase ? 'destination-out' : 'source-over';
      paint(ctx, mark);
    }
    setCount(marks.current.length);
    draw();
  }

  function point(e: PointerEvent<HTMLCanvasElement>): [number, number] {
    const box = e.currentTarget.getBoundingClientRect();
    return [(e.clientX - box.left) * WIDTH / box.width, (e.clientY - box.top) * HEIGHT / box.height];
  }

  async function loadImage(file?: File) {
    if (!file) return;
    const url = URL.createObjectURL(file);
    try {
      const img = new Image();
      img.src = url;
      await img.decode();
      if (alive.current) { image.current = img; setHasBackground(true); draw(); }
    } catch { if (alive.current) setError('下絵を開けませんでした。'); }
    finally { URL.revokeObjectURL(url); }
  }

  useLayoutEffect(() => {
    alive.current = true;
    ink.current = document.createElement('canvas');
    ink.current.width = WIDTH; ink.current.height = HEIGHT;
    draw();
    return () => {
      alive.current = false;
      if (recorder.current?.state === 'recording') recorder.current.stop();
      media.current?.getTracks().forEach(t => t.stop());
    };
  }, []);
  useEffect(() => {
    if (clip) return;
    const paste = (e: ClipboardEvent) => {
      const file = Array.from(e.clipboardData?.files || []).find(f => f.type.startsWith('image/'));
      if (file) { e.preventDefault(); void loadImage(file); }
    };
    document.addEventListener('paste', paste);
    return () => document.removeEventListener('paste', paste);
  }, [clip]);

  useEffect(() => {
    if (!session) { setSharing(false); return; }
    let done = false, sent = -1, pending = false, preparing = 0;
    const controller = new AbortController();
    const publish = async () => {
      if (!canvas.current || pending || sent === version.current || done) return;
      const current = version.current;
      pending = true;
      try {
        const jpeg = canvas.current.toDataURL('image/jpeg', .68).split(',')[1];
        const token = localStorage.getItem('done-token');
        const response = await fetch('/api/v1/voicelog/live/backend/sketch/' + encodeURIComponent(room), {
          method: 'POST', headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: 'Bearer ' + token } : {}) },
          signal: controller.signal, body: JSON.stringify({ session_id: session, number: current, jpeg }),
        });
        if (response.status === 409 && preparing++ < 6) return;
        if (!response.ok || !(await response.json()).accepted) throw new Error('共有できませんでした');
        if (!done) { sent = current; setSharing(true); setError(''); }
      } catch {
        if (!done) { setSharing(false); setError('絵を共有できませんでした。音声を終了して、もう一度接続してください。'); }
        done = true;
      } finally { pending = false; }
    };
    void publish();
    const timer = window.setInterval(() => void publish(), 650);
    return () => { done = true; controller.abort(); clearInterval(timer); };
  }, [room, session]);

  useEffect(() => {
    if (recordState !== 'recording') return;
    const start = Date.now();
    const timer = setInterval(() => setSeconds(Math.floor((Date.now() - start) / 1000)), 250);
    return () => clearInterval(timer);
  }, [recordState]);

  async function record() {
    if (!canvas.current || recorder.current || recordState !== 'idle') return;
    setError(''); setSeconds(0); setRecordState('starting');
    let mic: MediaStream | undefined;
    let combined: MediaStream | undefined;
    try {
      if (!canvas.current.captureStream || typeof MediaRecorder === 'undefined') throw new Error('このブラウザは録画に対応していません。');
      mic = await navigator.mediaDevices.getUserMedia({ audio: QUIET_SPEECH_MIC });
      if (!alive.current) { mic.getTracks().forEach(t => t.stop()); return; }
      combined = canvas.current.captureStream(20);
      const track = mic.getAudioTracks()[0];
      if (!track) throw new Error('マイクを選び直してください。');
      combined.addTrack(track);
      const mimeType = ['video/webm;codecs=vp9,opus', 'video/webm;codecs=vp8,opus', 'video/mp4'].find(m => MediaRecorder.isTypeSupported(m));
      const rec = new MediaRecorder(combined, { ...(mimeType ? { mimeType } : {}), videoBitsPerSecond: 900000 });
      const chunks: Blob[] = [];
      let size = 0;
      rec.ondataavailable = e => {
        if (e.data.size) { chunks.push(e.data); size += e.data.size; }
        if (size > 80 * 1024 * 1024 && rec.state === 'recording') rec.stop();
      };
      rec.onstop = () => {
        combined?.getTracks().forEach(t => t.stop());
        media.current = null; recorder.current = null;
        if (!alive.current) return;
        setRecordState('idle');
        const type = chunks[0]?.type || rec.mimeType;
        if (chunks.length) setClip(new File(chunks, '手描きの説明.' + (type.includes('mp4') ? 'mp4' : 'webm'), { type }));
        else setError('録画を保存できませんでした。');
      };
      track.onended = () => { if (rec.state === 'recording') rec.stop(); };
      rec.onerror = () => { if (alive.current) setError('録画が中断されました。'); };
      rec.start(1000); media.current = combined; recorder.current = rec;
      draw();
      setRecordState('recording');
    } catch (e) {
      mic?.getTracks().forEach(t => t.stop());
      combined?.getTracks().forEach(t => t.stop());
      if (alive.current) {
        setError(e instanceof Error && e.name === 'NotAllowedError' ? '録画にはブラウザのマイク許可が必要です。' : '録画を始められませんでした。マイクとブラウザを確認してください。');
        setRecordState('idle');
      }
    }
  }

  async function attach() {
    setBusy(true); setError('');
    try {
      let file = clip;
      if (!file && canvas.current) {
        const blob = await new Promise<Blob | null>(resolve => canvas.current!.toBlob(resolve));
        if (blob) file = new File([blob], '手描きの説明.png', { type: blob.type });
      }
      if (!file) throw new Error();
      await onAttach(file);
      if (alive.current) onClose();
    } catch { if (alive.current) { setError('添付できませんでした。もう一度「会話に添付」を押してください。'); setBusy(false); } }
  }

  const button = 'inline-flex min-h-9 items-center justify-center gap-1.5 rounded-lg border border-stone-300 bg-white px-3 text-sm text-stone-800 hover:bg-stone-100 disabled:opacity-40';
  const recording = recordState !== 'idle';
  return createPortal(<div role="dialog" aria-modal="true" aria-label="描いて話す" className="fixed inset-0 z-[49] flex items-center justify-center bg-black/60 p-2 sm:p-5">
    <section className="flex max-h-full w-full max-w-5xl flex-col overflow-y-auto rounded-2xl bg-stone-100 p-3 text-stone-900 shadow-2xl sm:p-5">
      <header className="mb-3 flex items-center justify-between"><h2 className="flex items-center gap-2 font-semibold"><Pencil size={19}/>描いて話す</h2>
        <button aria-label="閉じる" disabled={recording || busy} className={button} onClick={() => { if (clip || count || hasBackground) setDiscard(true); else onClose(); }}><X size={16}/></button></header>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        {colors.map(([name, value]) => <button key={name} aria-label={name + 'のペン'} aria-pressed={!erase && value === color} onClick={() => { setErase(false); setColor(value); }}
          className="grid h-9 w-9 place-items-center rounded-full border border-stone-300 bg-white aria-pressed:ring-2 aria-pressed:ring-stone-700"><span className="h-4 w-4 rounded-full" style={{ background: value }}/></button>)}
        <button className={button + ' aria-pressed:ring-2 aria-pressed:ring-stone-700'} aria-pressed={erase} onClick={() => setErase(e => !e)}><Eraser size={15}/>消しゴム</button>
        <button className={button} disabled={!count || !!clip} onClick={undo}><Undo2 size={15}/>戻す</button>
        <input ref={input} type="file" accept="image/*" hidden onChange={e => { void loadImage(e.target.files?.[0]); e.target.value = ''; }}/>
        <button className={button} disabled={!!clip} onClick={() => input.current?.click()} title="スクリーンショットや写真に描く"><ImagePlus size={15}/>下絵を選ぶ</button>
      </div>
      <div className="flex justify-center rounded-xl border border-stone-300 bg-stone-200 p-1">
        <canvas ref={canvas} width={WIDTH} height={HEIGHT} aria-label="手描きボード" style={{ pointerEvents: clip ? 'none' : 'auto', width: 'min(100%, 91dvh)', height: 'auto', touchAction: 'none' }} className="block aspect-[8/5] cursor-crosshair bg-white"
          onPointerDown={e => {
            if (active.current !== null || e.button !== 0) return;
            active.current = e.pointerId; e.currentTarget.setPointerCapture(e.pointerId);
            const mark = { color, width: erase ? 32 : 5, erase, points: [point(e)] };
            marks.current.push(mark); stroke(mark); setCount(marks.current.length);
          }}
          onPointerMove={e => {
            if (active.current !== e.pointerId) return;
            const mark = marks.current[marks.current.length - 1];
            const last = mark.points[mark.points.length - 1], next = point(e);
            mark.points.push(next); stroke({ ...mark, points: [last, next] });
          }}
          onLostPointerCapture={() => { active.current = null; }}/>
      </div>
      <footer className="mt-3 flex flex-wrap items-center gap-2">
        {recordState === 'recording' ? <button className={button} onClick={() => { setRecordState('stopping'); recorder.current?.stop(); }}><Square size={14} fill="currentColor"/>録画を止める</button> :
          !clip && <button className={button} disabled={recording || voiceOpen || busy} onClick={() => void record()}><Circle size={14} fill="#bd3847" color="#bd3847"/>声つきで録画</button>}
        <button className={button} disabled={recording || busy || !!clip} onClick={() => { setError(''); onVoice(!voiceOpen); }}><Mic size={15}/>{voiceOpen ? '音声を終了' : '音声モードで話す'}</button>
        <span role="status" className="text-sm text-stone-600">{recordState === 'starting' ? 'マイクを準備中' : recording ? '録画中 ' + Math.floor(seconds/60) + '分' + seconds%60 + '秒' : clip ? '録画を添付できます' : sharing && session ? '絵を共有中' : voiceOpen ? '接続中' : ''}</span>
        <button disabled={recording || busy || voiceOpen || !(clip || count || hasBackground)} className="ml-auto min-h-9 rounded-lg bg-stone-900 px-4 text-sm font-semibold text-white disabled:opacity-40" onClick={() => void attach()}>{busy ? '添付中' : '会話に添付'}</button>
      </footer>
      {error && <p role="alert" className="mt-2 text-sm text-red-700">{error}</p>}
      {discard && <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">描いた内容を閉じますか？
        <button className={button} onClick={() => setDiscard(false)}>続ける</button><button className={button} onClick={onClose}>閉じる</button></div>}
    </section>
  </div>, document.body);
}
