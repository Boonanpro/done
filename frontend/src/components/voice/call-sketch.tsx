'use client';

import { useState } from 'react';
import { Pencil } from 'lucide-react';
import { SketchBoard } from '@/components/chat/sketch-board';

export function CallSketch({ room, session, onToggle }: {
  room: string;
  session: string;
  onToggle?: (open: boolean) => void;
}) {
  const [view, setView] = useState<'unused' | 'open' | 'hidden'>('unused');
  const toggle = (open: boolean) => {
    setView(open ? 'open' : 'hidden');
    onToggle?.(open);
  };
  return <>
    <button type="button" aria-label="手描きボードを開く" aria-expanded={view === 'open'}
      className="inline-flex items-center gap-2 rounded-full border border-neutral-700 bg-neutral-950 px-3 py-2 text-sm text-neutral-100"
      onClick={() => toggle(true)}><Pencil size={16} />手描きボード</button>
    {view !== 'unused' && <SketchBoard room={room} session={session} open={view === 'open'} onClose={() => toggle(false)} />}
  </>;
}
