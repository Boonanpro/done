'use client';

import { useState, type ReactNode } from 'react';
import { Play, X } from 'lucide-react';

/**
 * 複数の画像・動画を LINE 式にまとめて表示する共通部品。
 * 1枚: そのまま（縦横比維持） / 2枚: 横2列 / 3枚: 左1大＋右2小 / 4枚以上: 正方形タイル
 * （4=2列、5枚以上=3列、7枚以上は「+N」で畳む）。
 * プロジェクトルームの吹き出し・コラボ窓口（オーナー/ゲスト）で同じものを使う。
 */
export interface MediaItem {
  url: string;
  kind: 'image' | 'video';
  name?: string;
}

const MAX_TILES = 6;

export function MediaGrid({
  items,
  onImageClick,
  className = '',
}: {
  items: MediaItem[];
  /** 画像タップ時（ライトボックス等）。未指定なら新しいタブで開く */
  onImageClick?: (url: string) => void;
  className?: string;
}) {
  const [playing, setPlaying] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  if (items.length === 0) return null;

  const openImage = (url: string) => {
    if (onImageClick) onImageClick(url);
    else window.open(url, '_blank', 'noopener,noreferrer');
  };

  // 1枚: 自然なサイズ（動画はインライン再生）
  if (items.length === 1) {
    const it = items[0];
    return (
      <div className={`my-1 ${className}`}>
        {it.kind === 'video' ? (
          <video src={it.url} controls playsInline preload="metadata"
            className="rounded-xl max-w-full border border-border/50" style={{ maxHeight: 300 }} />
        ) : (
          <img src={it.url} alt={it.name || '添付画像'}
            className="rounded-xl max-w-full max-h-64 object-contain border border-border/50 cursor-zoom-in"
            onClick={() => openImage(it.url)} />
        )}
      </div>
    );
  }

  const visible = expanded ? items : items.slice(0, MAX_TILES);
  const hidden = items.length - visible.length;

  const tile = (it: MediaItem, i: number, extraClass = '') => {
    const isLast = i === visible.length - 1 && hidden > 0;
    return (
      <button
        key={`${it.url}-${i}`}
        type="button"
        onClick={() => (isLast ? setExpanded(true) : it.kind === 'video' ? setPlaying(it.url) : openImage(it.url))}
        className={`relative overflow-hidden bg-muted rounded-lg ${extraClass}`}
        aria-label={it.kind === 'video' ? '動画を再生' : '画像を開く'}
      >
        {it.kind === 'video' ? (
          <video src={it.url} muted playsInline preload="metadata" className="h-full w-full object-cover" />
        ) : (
          <img src={it.url} alt={it.name || ''} className="h-full w-full object-cover" loading="lazy" />
        )}
        {it.kind === 'video' && !isLast && (
          <span className="absolute inset-0 flex items-center justify-center">
            <span className="rounded-full bg-black/55 p-2"><Play className="h-5 w-5 text-white fill-white" /></span>
          </span>
        )}
        {isLast && (
          <span className="absolute inset-0 flex items-center justify-center bg-black/55 text-white text-lg font-semibold">
            +{hidden}
          </span>
        )}
      </button>
    );
  };

  let grid: ReactNode;
  if (items.length === 2) {
    grid = <div className="grid grid-cols-2 gap-0.5">{visible.map((it, i) => tile(it, i, 'aspect-square'))}</div>;
  } else if (items.length === 3) {
    grid = (
      <div className="grid grid-cols-2 grid-rows-2 gap-0.5" style={{ height: 220 }}>
        {tile(visible[0], 0, 'row-span-2 h-full')}
        {tile(visible[1], 1, 'h-full')}
        {tile(visible[2], 2, 'h-full')}
      </div>
    );
  } else {
    const cols = items.length === 4 ? 'grid-cols-2' : 'grid-cols-3';
    grid = <div className={`grid ${cols} gap-0.5`}>{visible.map((it, i) => tile(it, i, 'aspect-square'))}</div>;
  }

  return (
    <div className={`my-1 w-full max-w-[320px] overflow-hidden rounded-xl border border-border/50 ${className}`}>
      {grid}
      {playing && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/85 p-4" onClick={() => setPlaying(null)}>
          <video src={playing} controls autoPlay playsInline className="max-h-full max-w-full rounded-lg" onClick={(e) => e.stopPropagation()} />
          <button type="button" className="absolute right-4 top-4 rounded-full bg-black/60 p-2 text-white" onClick={() => setPlaying(null)} aria-label="閉じる">
            <X className="h-5 w-5" />
          </button>
        </div>
      )}
    </div>
  );
}

/** コラボメッセージの metadata（files[] / 互換の file）→ 表示用リスト。画像・動画以外は含めない */
export function collabMediaItems(metadata: Record<string, unknown> | null | undefined): { media: MediaItem[]; others: { name: string; url: string; size?: number }[] } {
  const md = (metadata || {}) as { files?: unknown; file?: unknown };
  const raw = (Array.isArray(md.files) ? md.files : md.file ? [md.file] : []) as { name?: string; url?: string; type?: string; size?: number }[];
  const media: MediaItem[] = [];
  const others: { name: string; url: string; size?: number }[] = [];
  for (const f of raw) {
    if (!f?.url) continue;
    const t = f.type || '';
    if (t.startsWith('image/')) media.push({ url: f.url, kind: 'image', name: f.name });
    else if (t.startsWith('video/')) media.push({ url: f.url, kind: 'video', name: f.name });
    else others.push({ name: f.name || 'ファイル', url: f.url, size: f.size });
  }
  return { media, others };
}
