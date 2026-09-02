'use client';

/**
 * コラボチャットのリアクション（既存チップの表示＋人間が押せる絵文字ピッカー）。
 * - チップをタップ: その絵文字を自分が付け外し（トグル）
 * - 「+」: 絵文字ピッカー（🙏 👍 ❤️ 😂 🎉）
 * リアクションはメッセージではないので通知・未読は発生しない。
 */
import { useEffect, useRef, useState } from 'react';
import { SmilePlus } from 'lucide-react';

export const REACTION_CHOICES = ['🙏', '👍', '❤️', '😂', '🎉'];

export function ReactionBar({ reactions, myName, onToggle, align = 'left', compact = false }: {
  reactions?: Record<string, string[]> | null;
  myName?: string;
  onToggle: (emoji: string) => void;
  align?: 'left' | 'right';
  /** true: 常時「+」を薄く表示（スマホ向け）。false: ホバー時のみ */
  compact?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const entries = Object.entries(reactions || {}).filter(([, names]) => (names || []).length > 0);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);

  return (
    <div ref={ref} className={`relative mt-1 flex items-center gap-1 ${align === 'right' ? 'justify-end' : ''}`}>
      {entries.map(([emoji, names]) => {
        const mine = !!myName && (names || []).includes(myName);
        return (
          <button
            key={emoji}
            type="button"
            title={(names || []).join('、')}
            onClick={() => onToggle(emoji)}
            className={`animate-in zoom-in duration-200 motion-reduce:animate-none rounded-full border px-1.5 py-0.5 text-sm leading-none transition-colors ${
              mine ? 'border-primary/60 bg-primary/15' : 'border-border bg-background/80 hover:bg-muted'
            }`}
          >
            {emoji}{(names || []).length > 1 ? ` ${names.length}` : ''}
          </button>
        );
      })}
      <button
        type="button"
        aria-label="リアクションを追加"
        onClick={() => setOpen((v) => !v)}
        className={`rounded-full p-1 text-muted-foreground transition-opacity hover:text-foreground ${
          compact ? 'opacity-50' : 'opacity-0 group-hover:opacity-70 focus:opacity-100'
        }`}
      >
        <SmilePlus className="h-3.5 w-3.5" />
      </button>
      {open && (
        <div className={`absolute top-full z-20 mt-1 flex gap-1 rounded-full border border-border bg-card px-2 py-1 shadow-lg animate-in fade-in zoom-in-95 duration-200 motion-reduce:animate-none ${
          align === 'right' ? 'right-0' : 'left-0'
        }`}>
          {REACTION_CHOICES.map((e) => (
            <button
              key={e}
              type="button"
              onClick={() => { onToggle(e); setOpen(false); }}
              className="rounded-full px-1.5 py-0.5 text-lg leading-none transition-transform hover:scale-125 active:scale-95"
            >
              {e}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
