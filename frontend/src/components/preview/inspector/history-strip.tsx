'use client';

import Image from 'next/image';
import { SectionHeader } from './controls';

export interface HistoryItem {
  id: string;
  url: string;
  prompt?: string;
  created_at?: string;
  kind?: string;
}

/** 過去に生成した画像/動画のサムネイル一覧。クリックで現 src 差し替え */
export function HistoryStrip({
  items,
  currentUrl,
  onSelect,
  isVideo = false,
}: {
  items: HistoryItem[];
  currentUrl?: string;
  onSelect: (item: HistoryItem) => void;
  isVideo?: boolean;
}) {
  if (!items.length) {
    return (
      <div className="rounded border border-dashed border-border p-2 text-center text-xs text-muted-foreground">
        このプロジェクトの履歴はまだない
      </div>
    );
  }

  return (
    <section className="flex flex-col gap-1.5">
      <SectionHeader title={`履歴 (${items.length})`} />
      <div className="flex gap-1.5 overflow-x-auto pb-1">
        {items.map((it) => {
          const isActive = it.url === currentUrl;
          return (
            <button
              key={it.id}
              onClick={() => onSelect(it)}
              className={`relative h-14 w-20 shrink-0 overflow-hidden rounded border transition-all ${
                isActive ? 'border-primary ring-1 ring-primary' : 'border-border hover:border-primary/50'
              }`}
              title={it.prompt || it.url}
            >
              {isVideo ? (
                <video src={it.url} className="h-full w-full object-cover" muted />
              ) : (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={it.url} alt="" className="h-full w-full object-cover" />
              )}
              {isActive && (
                <div className="pointer-events-none absolute inset-0 bg-primary/10" />
              )}
            </button>
          );
        })}
      </div>
    </section>
  );
}
