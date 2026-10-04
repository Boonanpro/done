'use client';

import { useState, useRef, type ReactNode } from 'react';
import { Play } from 'lucide-react';
import {MediaViewer, collectChatMedia, mediaKind, type GalleryItem} from './media-viewer';

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
  className = '',
}: {
  items: MediaItem[];
  /** Legacy prop; media now always opens in the shared in-page viewer. */
  onImageClick?: (url: string) => void;
  className?: string;
}) {
  const root=useRef<HTMLDivElement>(null);
  const trigger=useRef<HTMLElement|null>(null);
  const [viewing,setViewing]=useState<{items:GalleryItem[];url:string}|null>(null);
  const [expanded, setExpanded] = useState(false);
  if (items.length === 0) return null;

  const open=(item:MediaItem)=>{trigger.current=document.activeElement as HTMLElement;setViewing({items:collectChatMedia(root.current,items),url:item.url})};
  const viewer=viewing?<MediaViewer items={viewing.items} initialUrl={viewing.url} onClose={()=>setViewing(null)} returnFocus={trigger.current}/>:null;
  if(items.length===1){const it=items[0];return <div ref={root} data-media-items={JSON.stringify(items)} className={`my-1 ${className}`}><button type="button" aria-label={it.name||(it.kind==='video'?'動画を再生':'画像を開く')} className="relative block max-w-full overflow-hidden rounded-xl border border-border/50" onClick={()=>open(it)}>{it.kind==='video'?<><video src={it.url} muted playsInline preload="metadata" className="max-h-[300px] max-w-full"/><span className="absolute inset-0 flex items-center justify-center"><span className="rounded-full bg-black/55 p-3"><Play className="h-6 w-6 fill-white text-white"/></span></span></>:<img src={it.url} alt={it.name||'添付画像'} className="max-h-64 max-w-full object-contain"/>}</button>{viewer}</div>}

  const visible = expanded ? items : items.slice(0, MAX_TILES);
  const hidden = items.length - visible.length;

  const tile = (it: MediaItem, i: number, extraClass = '') => {
    const isLast = i === visible.length - 1 && hidden > 0;
    return (
      <button
        key={`${it.url}-${i}`}
        type="button"
        onClick={() => (isLast ? setExpanded(true) : open(it))}
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
    <div ref={root} data-media-items={JSON.stringify(items)} className={`my-1 w-full max-w-[320px] overflow-hidden rounded-xl border border-border/50 ${className}`}>
      {grid}
      {viewer}
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
    const kind=t.startsWith('image/')?'image':t.startsWith('video/')?'video':mediaKind(f.url)||mediaKind(f.name||'');
    if (kind) media.push({ url: f.url, kind, name: f.name });
    else others.push({ name: f.name || 'ファイル', url: f.url, size: f.size });
  }
  return { media, others };
}
