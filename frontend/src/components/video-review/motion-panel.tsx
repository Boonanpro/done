'use client';

// サイズ・左右・上下・不透明度とキーフレームの欄（Premiere の「モーション」と同じ形）。
// 数字は clip_placement / placement.ts の1組だけ。ダンが付けた寄せや動きも、ここに同じ数字で出る。

import type { SequenceClip } from './video-review-editor';
import { EASES, motionAt, setKeyAt, sortedKeys, type Ease, type Motion, type MotionKey } from './placement';

type Props = {
  clip: SequenceClip;
  /** 再生位置（タイムラインの秒） */
  time: number;
  fps: number;
  onChange: (patch: Partial<SequenceClip>) => void;
  onSeek: (t: number) => void;
};

function Num({ value, step, onChange, suffix }: { value: number; step: number; onChange: (v: number) => void; suffix: string }) {
  return (
    <span className="inline-flex items-center gap-0.5">
      <input
        type="number"
        step={step}
        value={Number(value.toFixed(step < 1 ? 1 : 0))}
        onChange={(e) => { const v = Number(e.target.value); if (Number.isFinite(v)) onChange(v); }}
        className="w-14 rounded border border-border bg-background px-1 text-right text-[10px] text-foreground"
      />
      <span>{suffix}</span>
    </span>
  );
}

export function MotionPanel({ clip, time, fps, onChange, onSeek }: Props) {
  const ts = Number(clip.timeline_start || 0);
  const dur = Math.max(0, Number(clip.timeline_end || 0) - ts);
  const rel = Math.max(0, Math.min(dur, time - ts));
  const keys = sortedKeys(clip);
  const m = motionAt(clip, rel);
  const onKey = keys.some((k) => Math.abs(k.t - rel) <= 0.5 / fps);
  const opacity = clip.opacity != null ? Number(clip.opacity) : 1;

  const setMotion = (next: Motion) => {
    if (keys.length) onChange({ motion_keys: setKeyAt(keys, rel, next, fps) });
    else onChange({ transform: { scale: Number(next.scale.toFixed(4)), x: Number(next.x.toFixed(4)), y: Number(next.y.toFixed(4)) } });
  };
  const setKeys = (next: MotionKey[]) => {
    if (next.length) onChange({ motion_keys: next });
    else onChange({ motion_keys: null, transform: { scale: m.scale, x: m.x, y: m.y } });
  };

  const row = (label: string, value: number, min: number, max: number, step: number, apply: (v: number) => void, unit = '%') => (
    <label className="flex flex-col gap-1 text-[10px] text-muted-foreground">
      <span className="flex items-center justify-between">
        <span>{label}</span>
        <Num value={value * 100} step={0.1} suffix={unit} onChange={(v) => apply(v / 100)} />
      </span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => apply(Number(e.target.value))} className="w-full" />
    </label>
  );

  return (
    <div className="space-y-2 rounded-md border border-border p-2" data-motion-panel>
      <div className="flex items-center justify-between">
        <div className="text-xs font-medium text-muted-foreground">サイズ・位置（プレビュー上でドラッグも可）</div>
        <button
          type="button"
          title={keys.length ? (onKey ? 'この時刻のキーを消す' : 'この時刻にキーを打つ') : '動きを付ける（この時刻にキーを打つ）'}
          className={`rounded px-1.5 py-0.5 text-[11px] ${onKey ? 'bg-amber-400 text-black' : keys.length ? 'bg-amber-400/20 text-amber-300' : 'bg-muted text-muted-foreground hover:bg-muted/70'}`}
          onClick={() => {
            if (onKey) setKeys(keys.filter((k) => Math.abs(k.t - rel) > 0.5 / fps));
            else onChange({ motion_keys: setKeyAt(keys, rel, m, fps), transform: null });
          }}
          data-key-toggle
        >
          ◆ {keys.length ? `キー ${keys.length}` : 'キー'}
        </button>
      </div>
      {row('サイズ', m.scale, 0.05, 4, 0.01, (v) => setMotion({ ...m, scale: Math.max(0.01, v) }))}
      <div className="grid grid-cols-2 gap-2">
        {row('左右', m.x, -1, 1, 0.005, (v) => setMotion({ ...m, x: v }))}
        {row('上下', m.y, -1, 1, 0.005, (v) => setMotion({ ...m, y: v }))}
      </div>
      {row('不透明度', opacity, 0, 1, 0.01, (v) => onChange({ opacity: Math.max(0, Math.min(1, Number(v.toFixed(3)))) }))}
      {keys.length ? (
        <div className="space-y-1">
          <div className="text-[10px] text-muted-foreground">キーフレーム（{keys.length}）: 欄を動かすと、再生位置のキーが変わります（無ければ足されます）</div>
          {keys.map((k, i) => (
            <div key={`${k.t}-${i}`} className={`flex items-center gap-1 rounded px-1 py-0.5 text-[10px] ${Math.abs(k.t - rel) <= 0.5 / fps ? 'bg-amber-400/15' : ''}`}>
              <button type="button" className="text-amber-300" title="この時刻へ" onClick={() => onSeek(ts + k.t)}>◆</button>
              <input
                type="number" step={1 / fps} min={0} max={dur}
                value={Number(k.t.toFixed(2))}
                title="クリップの頭からの秒"
                onChange={(e) => {
                  const t = Math.max(0, Math.min(dur, Number(e.target.value)));
                  if (!Number.isFinite(t)) return;
                  setKeys(keys.map((x, j) => (j === i ? { ...x, t: Number(t.toFixed(4)) } : x)).sort((a, b) => a.t - b.t));
                }}
                className="w-12 rounded border border-border bg-background px-1 text-right text-foreground"
              />
              <span className="text-muted-foreground">秒 {Math.round(k.scale * 100)}%</span>
              {i < keys.length - 1 ? (
                <select
                  value={String(k.ease || 'linear')}
                  onChange={(e) => setKeys(keys.map((x, j) => (j === i ? { ...x, ease: e.target.value as Ease } : x)))}
                  className="ml-auto rounded border border-border bg-background text-[10px] text-foreground"
                  title="次のキーまでの動き方"
                >
                  {EASES.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              ) : <span className="ml-auto" />}
              <button type="button" className="px-1 text-muted-foreground hover:text-red-400" title="このキーを消す"
                onClick={() => setKeys(keys.filter((_, j) => j !== i))}>×</button>
            </div>
          ))}
        </div>
      ) : null}
      <div className="space-y-1">
        <div className="text-[10px] text-muted-foreground">くり抜きの形</div>
        <div className="grid grid-cols-3 gap-1">
          {([['rect', '四角'], ['circle', '丸'], ['rounded', '写真風']] as const).map(([val, label]) => {
            const cur = (clip.shape as string) || 'rect';
            return (
              <button key={val} type="button"
                className={`rounded px-1 py-1 text-[10px] ${cur === val ? 'bg-sky-500 text-white' : 'bg-background text-muted-foreground hover:bg-muted'}`}
                onClick={() => onChange({ shape: val })}>
                {label}
              </button>
            );
          })}
        </div>
      </div>
      {(clip.transform || keys.length || (clip.opacity != null && clip.opacity < 1)) ? (
        <button type="button" className="h-6 w-full rounded text-[10px] text-muted-foreground hover:bg-muted"
          onClick={() => onChange({ transform: null, motion_keys: null, opacity: undefined })}>
          サイズ・位置・動きをリセット
        </button>
      ) : null}
    </div>
  );
}
