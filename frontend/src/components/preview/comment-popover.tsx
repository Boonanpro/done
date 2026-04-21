'use client';

import { RefObject, useEffect, useRef } from 'react';
import { Send, X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { usePreviewStore } from '@/stores/preview-store';

export function CommentPopover({
  iframeRef,
  onSubmit,
}: {
  iframeRef: RefObject<HTMLIFrameElement | null>;
  onSubmit: () => void;
}) {
  const selectedElement = usePreviewStore((s) => s.selectedElement);
  const popoverDraft = usePreviewStore((s) => s.popoverDraft);
  const setPopoverDraft = usePreviewStore((s) => s.setPopoverDraft);
  const clearSelection = usePreviewStore((s) => s.clearSelection);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (selectedElement) {
      textareaRef.current?.focus();
    }
  }, [selectedElement?.refId]);

  if (!selectedElement) return null;

  const POPOVER_WIDTH = 300;
  const POPOVER_HEIGHT = 160;
  const iframe = iframeRef.current;
  const containerRect = iframe?.parentElement?.getBoundingClientRect();
  const maxX = (containerRect?.width ?? 800) - POPOVER_WIDTH - 12;
  const maxY = (containerRect?.height ?? 600) - POPOVER_HEIGHT - 12;

  const preferredY = selectedElement.rect.y + selectedElement.rect.height + 8;
  const x = Math.max(12, Math.min(selectedElement.rect.x, maxX));
  const y = Math.max(12, Math.min(preferredY, maxY));

  return (
    <div
      className="absolute z-30 flex w-[300px] flex-col gap-2 rounded-lg border border-border bg-popover p-2.5 shadow-xl"
      style={{ left: x, top: y }}
    >
      <div className="flex items-center gap-1.5 text-xs">
        <span className="rounded bg-primary/15 px-1.5 py-0.5 font-mono font-medium text-primary">
          @{selectedElement.refId}
        </span>
        <span className="truncate text-muted-foreground">
          &lt;{selectedElement.tagName}&gt;
          {selectedElement.text ? ` "${selectedElement.text}"` : ''}
        </span>
        <button
          onClick={clearSelection}
          className="ml-auto shrink-0 text-muted-foreground hover:text-foreground"
          title="閉じる (Esc)"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      <textarea
        ref={textareaRef}
        value={popoverDraft}
        onChange={(e) => setPopoverDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            if (popoverDraft.trim()) onSubmit();
          } else if (e.key === 'Escape') {
            e.preventDefault();
            clearSelection();
          }
        }}
        placeholder="この要素へのコメント..."
        rows={3}
        className="min-h-[72px] resize-none rounded-md border border-border bg-input/40 p-2 text-sm focus:border-primary/50 focus:outline-none"
      />
      <Button
        size="sm"
        className="h-7 w-full"
        onClick={onSubmit}
        disabled={!popoverDraft.trim()}
      >
        <Send className="mr-1 h-3 w-3" />
        送信
      </Button>
    </div>
  );
}
