'use client';

import { RefObject, useEffect, useRef } from 'react';
import { Plus, X } from 'lucide-react';

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
  const selectedElements = usePreviewStore((s) => s.selectedElements);
  const popoverDraft = usePreviewStore((s) => s.popoverDraft);
  const setPopoverDraft = usePreviewStore((s) => s.setPopoverDraft);
  const clearSelection = usePreviewStore((s) => s.clearSelection);
  const removeSelectedElement = usePreviewStore((s) => s.removeSelectedElement);
  const pendingCount = usePreviewStore((s) => s.pendingComments.length);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (selectedElement) {
      textareaRef.current?.focus();
    }
  }, [selectedElement?.refId]);

  if (!selectedElement) return null;

  const elements = selectedElements.length ? selectedElements : [selectedElement];
  const isMulti = elements.length > 1;

  const POPOVER_WIDTH = 300;
  const POPOVER_HEIGHT = 200;
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
      <div className="flex items-start gap-1.5 text-xs">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1">
          {isMulti && (
            <span className="w-full text-[11px] font-medium text-foreground">
              {elements.length}個の要素を選択中
            </span>
          )}
          {elements.map((el) => (
            <span
              key={el.refId}
              className="inline-flex max-w-full items-center gap-1 rounded bg-primary/15 px-1.5 py-0.5 font-mono text-primary"
            >
              @{el.refId}
              <span className="truncate font-sans text-muted-foreground">
                &lt;{el.tagName}&gt;
                {el.text ? ` "${el.text.slice(0, isMulti ? 12 : 40)}"` : ''}
              </span>
              {isMulti && (
                <button
                  onClick={() => removeSelectedElement(el.refId)}
                  className="shrink-0 text-muted-foreground hover:text-foreground"
                  title="この要素を選択から外す"
                >
                  <X className="h-3 w-3" />
                </button>
              )}
            </span>
          ))}
        </div>
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
        placeholder={isMulti ? `選択中の${elements.length}要素へのコメント...` : 'この要素へのコメント...'}
        rows={3}
        className="min-h-[72px] resize-none rounded-md border border-border bg-input/40 p-2 text-sm focus:border-primary/50 focus:outline-none"
      />
      <Button
        size="sm"
        className="h-7 w-full"
        onClick={onSubmit}
        disabled={!popoverDraft.trim()}
      >
        <Plus className="mr-1 h-3 w-3" />
        {isMulti ? `${elements.length}要素まとめて追加` : '追加'}
      </Button>
      <p className="text-[11px] leading-snug text-muted-foreground">
        {pendingCount > 0
          ? `${pendingCount}件たまっています。続けて他の要素も選べます。送信はチャットの送信ボタンで。`
          : 'Ctrl+クリックで要素を追加選択できます。追加してもまだ送信されません。まとめてチャットの送信ボタンで送ります。'}
      </p>
    </div>
  );
}
