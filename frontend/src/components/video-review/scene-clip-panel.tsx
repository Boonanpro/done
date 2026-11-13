'use client';

/**
 * Side panel for a selected editable scene: every text the scene marks with data-edit, with its
 * words, font, colour, size, position and timing. Edits are stored in scene.params.edits[key]
 * and applied inside the scene before its own animation code runs, so the animation, the preview
 * and the export all use the edited text. Nothing is baked: "元に戻す" restores the original.
 */
import { useEffect, useState } from 'react';

import type { SequenceClip } from './video-review-editor';
import { useSceneInfoFor, type SceneItem } from './scene-store';
import { isSceneClip } from './scene-layer';

type Edit = { text?: string; font?: string; color?: string; scale?: number; dx?: number; dy?: number; shift?: number };
type Scene = Record<string, unknown> & { params?: { edits?: Record<string, Edit> } & Record<string, unknown> };

declare global { interface Window { DAN_SCENE_FONTS?: { family: string; label?: string }[] } }

function toHex(rgb: string): string {
  const m = rgb.match(/\d+/g);
  if (!m || m.length < 3) return '#ffffff';
  return '#' + m.slice(0, 3).map((v) => Number(v).toString(16).padStart(2, '0')).join('');
}

function ItemEditor({ item, edit, fonts, open, onOpen, onEdit }: {
  item: SceneItem; edit: Edit; fonts: { family: string; label?: string }[]; open: boolean;
  onOpen: () => void; onEdit: (e: Edit | null) => void;
}) {
  const [text, setText] = useState(edit.text ?? item.text);
  useEffect(() => { setText(edit.text ?? item.text); }, [edit.text, item.text]);
  // the scene reloads on every committed edit: commit typing after a short pause
  useEffect(() => {
    if (text === (edit.text ?? item.text)) return;
    const t = window.setTimeout(() => onEdit({ ...edit, text }), 350);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text]);
  const changed = Object.keys(edit).length > 0;
  return (
    <div data-scene-item-editor={item.key} className={`rounded border ${open ? 'border-violet-400/70 bg-violet-500/10' : 'border-white/10'} p-2`}>
      <button type="button" className="flex w-full items-center justify-between text-left text-[11px]" onClick={onOpen}>
        <span className="truncate"><span className="text-violet-300">{item.label || item.key}</span>　{item.text}</span>
        <span className="shrink-0 text-[10px] text-neutral-400">{item.start.toFixed(1)}〜{item.end.toFixed(1)}秒</span>
      </button>
      {open ? (
        <div className="mt-2 space-y-2 text-[11px]">
          <textarea
            className="w-full rounded border border-white/15 bg-black/40 p-1 text-sm"
            rows={Math.min(3, Math.max(1, text.split('\n').length))}
            value={text}
            onChange={(e) => setText(e.target.value)}
            aria-label="文字"
          />
          <div className="grid grid-cols-[auto_1fr] items-center gap-x-2 gap-y-1">
            <span>書体</span>
            <select
              className="rounded border border-white/15 bg-black/40 p-1"
              value={edit.font || item.font}
              onChange={(e) => onEdit({ ...edit, font: e.target.value })}
            >
              {[...(fonts.some((f) => f.family === item.font) ? [] : [{ family: item.font, label: item.font }]), ...fonts].map((f) => (
                <option key={f.family} value={f.family}>{f.label || f.family}</option>
              ))}
            </select>
            <span>色</span>
            <input type="color" value={edit.color || toHex(item.color)} onChange={(e) => onEdit({ ...edit, color: e.target.value })} />
            <span>大きさ</span>
            <input type="range" min={0.4} max={2} step={0.05} value={edit.scale ?? 1} onChange={(e) => onEdit({ ...edit, scale: Number(e.target.value) })} />
            <span>横・縦</span>
            <div className="flex gap-1">
              <input type="number" step={0.01} className="w-16 rounded border border-white/15 bg-black/40 p-1" value={edit.dx ?? 0} onChange={(e) => onEdit({ ...edit, dx: Number(e.target.value) })} title="横のずらし（画面の幅に対する割合）" />
              <input type="number" step={0.01} className="w-16 rounded border border-white/15 bg-black/40 p-1" value={edit.dy ?? 0} onChange={(e) => onEdit({ ...edit, dy: Number(e.target.value) })} title="縦のずらし（画面の高さに対する割合）" />
            </div>
            <span>出る時刻</span>
            <div className="flex items-center gap-1">
              <input type="number" step={0.05} className="w-16 rounded border border-white/15 bg-black/40 p-1" value={edit.shift ?? 0} onChange={(e) => onEdit({ ...edit, shift: Number(e.target.value) })} />
              <span className="text-neutral-400">秒ずらす（動きごと）</span>
            </div>
          </div>
          {changed ? (
            <button type="button" className="text-[11px] text-neutral-300 underline" onClick={() => onEdit(null)}>元に戻す</button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export function SceneClipPanel({ clip, onChange }: { clip: SequenceClip; onChange: (scene: Scene) => void }) {
  const id = String(clip.id);
  const info = useSceneInfoFor(id);
  const [openKey, setOpenKey] = useState<string | null>(() => {
    const d = typeof window !== 'undefined' ? (window as unknown as { __danSceneItem?: { clipId: string; key: string } }).__danSceneItem : undefined;
    return d && d.clipId === id ? d.key : null;
  });
  const fonts = (typeof window !== 'undefined' && window.DAN_SCENE_FONTS) || [];
  useEffect(() => {
    const on = (e: Event) => { const d = (e as CustomEvent).detail; if (d?.clipId === id) setOpenKey(d.key); };
    window.addEventListener('dan-scene-item', on);
    return () => window.removeEventListener('dan-scene-item', on);
  }, [id]);
  if (!isSceneClip(clip)) return null;
  const scene = clip.scene as Scene;
  const edits = (scene.params?.edits || {}) as Record<string, Edit>;
  const setEdit = (key: string, e: Edit | null) => {
    const next = { ...edits };
    if (e && Object.values(e).some((v) => v !== undefined && v !== '')) next[key] = e; else delete next[key];
    onChange({ ...scene, params: { ...(scene.params || {}), edits: next } });
  };
  return (
    <div data-scene-panel className="space-y-1.5">
      <div className="text-[11px] text-neutral-400">場面の中の文字（押すと直せます。動きはそのまま付いてきます）</div>
      {!info ? <div className="text-[11px] text-neutral-500">場面を読み込み中…</div> : null}
      {info?.items.map((it) => (
        <ItemEditor
          key={it.key}
          item={it}
          edit={edits[it.key] || {}}
          fonts={fonts}
          open={openKey === it.key}
          onOpen={() => setOpenKey(openKey === it.key ? null : it.key)}
          onEdit={(e) => setEdit(it.key, e)}
        />
      ))}
    </div>
  );
}

const BLENDS: [string, string][] = [
  ['', '普通'], ['screen', 'スクリーン（黒が消えて光だけ乗る）'], ['add', '加算（もっと明るく）'], ['lighten', '比較（明）'],
  ['multiply', '乗算（白が消える）'], ['overlay', 'オーバーレイ'], ['softlight', 'ソフトライト'],
];

/** How an overlay video/picture mixes with what is under it (light leaks, film burns and
 *  particles shot on black use スクリーン). The export mixes the same way. */
export function BlendSelect({ clip, onChange }: { clip: SequenceClip; onChange: (blend: string | undefined) => void }) {
  if (!clip.asset_id || isSceneClip(clip)) return null;
  const cur = String((clip as { blend?: string }).blend || '');
  return (
    <label className="flex items-center gap-2 text-[11px]">
      <span className="shrink-0">重ね方</span>
      <select
        data-blend-select
        className="min-w-0 flex-1 rounded border border-white/15 bg-black/40 p-1"
        value={cur}
        onChange={(e) => onChange(e.target.value || undefined)}
      >
        {BLENDS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </label>
  );
}
