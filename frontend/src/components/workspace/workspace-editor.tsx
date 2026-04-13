'use client';

import { useEffect, useMemo, useRef } from 'react';
import { useCreateBlockNote } from '@blocknote/react';
import { BlockNoteView } from '@blocknote/shadcn';
import '@blocknote/core/fonts/inter.css';
import '@blocknote/shadcn/style.css';

import type { BlockResponse } from '@/lib/api-client';

type Props = {
  block: BlockResponse;
  onChange: (content: unknown[]) => void;
};

export function WorkspaceEditor({ block, onChange }: Props) {
  const initialContent = useMemo(() => {
    const c = Array.isArray(block.content) ? block.content : [];
    return c.length > 0 ? (c as any[]) : undefined;
  }, [block.id]);

  const editor = useCreateBlockNote({
    initialContent: initialContent as any,
  });

  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const handler = () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
      saveTimer.current = setTimeout(() => {
        onChange(editor.document as unknown as unknown[]);
      }, 600);
    };
    const unsubscribe = editor.onChange(handler);
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
      unsubscribe?.();
    };
  }, [editor, onChange]);

  return (
    <div className="prose max-w-none">
      <BlockNoteView editor={editor} theme="light" />
    </div>
  );
}
