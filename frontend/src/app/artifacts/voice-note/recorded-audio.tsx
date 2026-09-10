'use client';

import { useEffect, useRef, useState } from 'react';

/** Tie the object URL to its Blob so a new recording never plays an old URL. */
export function RecordedAudio({ blob }: { blob: Blob }) {
  const [source, setSource] = useState<{ blob: Blob; url: string }>();
  const [check, setCheck] = useState<{ blob: Blob; message: string }>();

  useEffect(() => {
    const url = URL.createObjectURL(blob);
    setSource({ blob, url });
    let active = true;
    const context = new AudioContext();
    void blob.arrayBuffer().then(bytes => context.decodeAudioData(bytes)).then(buffer => {
      let peak = 0;
      for (let c = 0; c < buffer.numberOfChannels; c++) {
        for (const sample of buffer.getChannelData(c)) peak = Math.max(peak, Math.abs(sample));
      }
      const message = peak < 0.0001
        ? '録音はほぼ無音です。マイクの接続・ミュート設定を確認してください。'
        : peak < 0.01
          ? '録音の音量が小さいようです。マイクに近づいて話してください。'
          : '音が入っています。再生して声の内容を確認してください。';
      if (active) setCheck({ blob, message });
    }).catch(() => {
      if (active) setCheck({ blob, message: '音量を確認できませんでした。録音を再生して内容を確認してください。' });
    }).finally(() => { void context.close(); });
    return () => { active = false; URL.revokeObjectURL(url); };
  }, [blob]);

  return <div>
    {source?.blob === blob ? <StableAudio src={source.url} /> : <p>再生の準備中です…</p>}
    <p role="status">{check?.blob === blob ? check.message : '録音の音量を確認しています…'}</p>
  </div>;
}


/** A recorder WebM may omit duration. Resolve its end before exposing controls. */
export function StableAudio({ src }: { src: string }) {
  return <PreparedAudio key={src} src={src} />;
}

function PreparedAudio({ src }: { src: string }) {
  const ref = useRef<HTMLAudioElement>(null);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const audio = ref.current;
    if (!audio) return;
    let active = true;
    let phase: 'metadata' | 'end' | 'reset' | 'ready' | 'failed' = 'metadata';
    setReady(false);
    setFailed(false);
    const validDuration = () => Number.isFinite(audio.duration) && audio.duration > 0;
    const finish = () => {
      if (!active || phase === 'failed') return;
      phase = 'ready';
      clearTimeout(timer);
      setReady(true);
    };
    const fail = () => {
      if (!active || phase === 'ready') return;
      phase = 'failed';
      clearTimeout(timer);
      setFailed(true);
    };
    const timer = setTimeout(fail, 60000);
    const metadata = () => {
      if (phase !== 'metadata') return;
      if (validDuration()) { finish(); return; }
      phase = 'end';
      try { audio.currentTime = 1e10; } catch { fail(); }
    };
    const settle = () => {
      if (phase === 'end' && validDuration()) {
        phase = 'reset';
        try { audio.currentTime = 0; } catch { fail(); }
      }
      if (phase === 'reset' && !audio.seeking && audio.currentTime === 0) finish();
    };
    audio.addEventListener('loadedmetadata', metadata);
    audio.addEventListener('timeupdate', settle);
    audio.addEventListener('seeked', settle);
    audio.addEventListener('error', fail);
    audio.src = src;
    audio.load();
    return () => {
      active = false;
      clearTimeout(timer);
      audio.removeEventListener('loadedmetadata', metadata);
      audio.removeEventListener('timeupdate', settle);
      audio.removeEventListener('seeked', settle);
      audio.removeEventListener('error', fail);
      audio.pause();
      audio.removeAttribute('src');
      audio.load();
    };
  }, [src, attempt]);
  return <div>
    <audio ref={ref} controls={ready} hidden={!ready} preload="auto" aria-label="録音の再生" />
    {!ready && <p role="status">{failed ? '音声を読み込めませんでした。' : '録音の長さを確認しています…'}</p>}
    {failed && <button type="button" onClick={() => setAttempt(v => v + 1)}>再生の準備をやり直す</button>}
  </div>;
}
