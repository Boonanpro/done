'use client';

import { useEffect, useState } from 'react';

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
    {source?.blob === blob ? <audio controls src={source.url} /> : <p>再生の準備中です…</p>}
    <p role="status">{check?.blob === blob ? check.message : '録音の音量を確認しています…'}</p>
  </div>;
}
