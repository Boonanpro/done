'use client';
import { useEffect, useState } from 'react';

export function InputLevel({ stream }: { stream: MediaStream | null }) {
  const [level, setLevel] = useState(0);
  const [unavailable, setUnavailable] = useState(false);
  useEffect(() => {
    setLevel(0);setUnavailable(false);
    if (!stream) return;
    let context: AudioContext | undefined;
    let frame = 0;
    let active = true;
    try {
      context = new AudioContext();
      const source = context.createMediaStreamSource(stream);
      const analyser = context.createAnalyser();
      analyser.fftSize = 1024;
      source.connect(analyser);
      const samples = new Float32Array(analyser.fftSize);
      const tick = () => {
        if (!active) return;
        analyser.getFloatTimeDomainData(samples);
        const rms = Math.sqrt(samples.reduce((sum, v) => sum + v * v, 0) / samples.length);
        setLevel(Math.max(0, Math.min(100, (20 * Math.log10(Math.max(rms, 0.000001)) + 60) / 60 * 100)));
        frame = requestAnimationFrame(tick);
      };
      void context.resume().then(tick).catch(() => { if(active)setUnavailable(true); });
      return () => { active=false;cancelAnimationFrame(frame);source.disconnect();analyser.disconnect();void context?.close(); };
    } catch { setUnavailable(true);void context?.close(); }
  }, [stream]);
  return <div style={{margin:'12px 0'}}>
    <label style={{display:'block',fontSize:13,marginBottom:6}}>入力レベル</label>
    <div role="meter" aria-label="入力レベル" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(level)} style={{height:10,borderRadius:5,background:'#dce6e1',overflow:'hidden'}}>
      <div style={{height:'100%',width:`${level}%`,background:level>95?'#b91c1c':level>85?'#c58110':'#07856d',transition:'width 80ms linear'}} />
    </div>
    <small>{unavailable?'入力レベルを表示できません。':stream?'録音中':'録音を始めると、音の大きさを表示します。'}</small>
  </div>;
}
