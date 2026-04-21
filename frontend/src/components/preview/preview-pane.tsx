'use client';

import { useEffect, useRef, useState } from 'react';
import { ChevronDown, Edit3, ExternalLink, X } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';

import { Button } from '@/components/ui/button';
import { usePreviewStore, type ArtifactRecord } from '@/stores/preview-store';
import { attachInspector, detachInspector } from './iframe-inspector';
import { CommentPopover } from './comment-popover';

export function PreviewPane({ onSubmitComment }: { onSubmitComment: () => void }) {
  const artifact = usePreviewStore((s) => s.artifact);
  const projectId = usePreviewStore((s) => s.projectId);
  const isEditMode = usePreviewStore((s) => s.isEditMode);
  const closePreview = usePreviewStore((s) => s.closePreview);
  const toggleEditMode = usePreviewStore((s) => s.toggleEditMode);
  const openArtifact = usePreviewStore((s) => s.openArtifact);

  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [loaded, setLoaded] = useState(false);
  const [showSwitcher, setShowSwitcher] = useState(false);

  const { data: artifacts = [] } = useQuery<ArtifactRecord[]>({
    queryKey: ['chat-artifacts', projectId],
    queryFn: async () => {
      const res = await fetch(
        `/api/v1/chat-artifact${projectId ? `?project_id=${projectId}` : ''}`,
        { credentials: 'include' }
      );
      if (!res.ok) return [];
      return res.json();
    },
    enabled: !!projectId,
    staleTime: 10_000,
  });

  useEffect(() => {
    setLoaded(false);
  }, [artifact?.id]);

  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe || !loaded) return;
    if (isEditMode) {
      attachInspector(iframe);
    } else {
      detachInspector(iframe);
    }
    return () => detachInspector(iframe);
  }, [isEditMode, loaded]);

  if (!artifact) return null;

  return (
    <div className="flex h-full flex-col border-l border-border bg-muted/20">
      <div className="flex shrink-0 items-center gap-2 border-b border-border bg-background px-3 py-2">
        <div className="relative min-w-0 flex-1">
          <button
            onClick={() => setShowSwitcher((v) => !v)}
            className="flex w-full items-center gap-1.5 rounded-md px-2 py-1 text-left hover:bg-muted"
          >
            <span className="truncate text-sm font-medium">
              {artifact.label || artifact.slug}
            </span>
            <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" />
          </button>
          {showSwitcher && artifacts.length > 0 && (
            <div className="absolute left-0 top-full z-20 mt-1 w-[320px] max-w-[90vw] rounded-md border border-border bg-popover p-1 shadow-lg">
              {artifacts.map((a) => (
                <button
                  key={a.id}
                  onClick={() => {
                    if (projectId) openArtifact(projectId, a);
                    setShowSwitcher(false);
                  }}
                  className={`block w-full truncate rounded px-2 py-1.5 text-left text-sm hover:bg-muted ${
                    a.id === artifact.id ? 'bg-muted' : ''
                  }`}
                >
                  <div className="truncate">{a.label || a.slug}</div>
                  <div className="truncate text-xs text-muted-foreground">{a.preview_url}</div>
                </button>
              ))}
            </div>
          )}
        </div>
        <a
          href={artifact.preview_url}
          target="_blank"
          rel="noopener noreferrer"
          className="shrink-0 rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
          title="新しいタブで開く"
        >
          <ExternalLink className="h-3.5 w-3.5" />
        </a>
        <Button
          variant={isEditMode ? 'default' : 'ghost'}
          size="sm"
          className="h-7 px-2"
          onClick={toggleEditMode}
        >
          <Edit3 className="mr-1 h-3.5 w-3.5" />
          {isEditMode ? '編集中' : '編集'}
        </Button>
        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={closePreview}>
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>
      <div className="relative flex-1 overflow-hidden bg-background">
        <iframe
          ref={iframeRef}
          src={artifact.preview_url}
          onLoad={() => setLoaded(true)}
          className="h-full w-full border-0"
          title={artifact.label || artifact.slug}
        />
        {isEditMode && <CommentPopover iframeRef={iframeRef} onSubmit={onSubmitComment} />}
        {isEditMode && (
          <div className="pointer-events-none absolute left-0 right-0 top-0 flex justify-center p-2">
            <div className="pointer-events-auto rounded-full bg-primary/90 px-3 py-1 text-xs font-medium text-primary-foreground shadow">
              編集モード — 要素をクリックしてコメント
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
