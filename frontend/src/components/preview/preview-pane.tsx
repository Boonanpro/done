'use client';

import { useEffect, useRef, useState } from 'react';
import { ChevronDown, Edit3, ExternalLink, MessageSquare, RefreshCw, Sliders, X } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';

import { Button } from '@/components/ui/button';
import { usePreviewStore, flushInspectorEdits, type ArtifactRecord } from '@/stores/preview-store';
import { attachInspector, detachInspector } from './iframe-inspector';
import { CommentPopover } from './comment-popover';
import { InspectorPanel } from './inspector-panel';

export function PreviewPane({ onSubmitComment }: { onSubmitComment: () => void }) {
  const artifact = usePreviewStore((s) => s.artifact);
  const projectId = usePreviewStore((s) => s.projectId);
  const isEditMode = usePreviewStore((s) => s.isEditMode);
  const inspectorMode = usePreviewStore((s) => s.inspectorMode);
  const setInspectorMode = usePreviewStore((s) => s.setInspectorMode);
  const closePreview = usePreviewStore((s) => s.closePreview);
  const toggleEditMode = usePreviewStore((s) => s.toggleEditMode);
  const openArtifact = usePreviewStore((s) => s.openArtifact);

  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [loaded, setLoaded] = useState(false);
  const [showSwitcher, setShowSwitcher] = useState(false);
  const [refreshSpinning, setRefreshSpinning] = useState(false);
  // iframe が load するたびに increment する。attachInspector 再実行の deps に入れ、
  // リフレッシュや内部ナビゲーション後も新 contentDocument に再アタッチする
  const [iframeLoadSeq, setIframeLoadSeq] = useState(0);

  const handleRefresh = async () => {
    const iframe = iframeRef.current;
    if (!iframe) return;
    setRefreshSpinning(true);
    // 未送信のインスペクタ編集をまず flush（リロードで消さないため）
    await flushInspectorEdits();
    const prevScrollX = iframe.contentWindow?.scrollX ?? 0;
    const prevScrollY = iframe.contentWindow?.scrollY ?? 0;
    const restoreScroll = () => {
      try {
        iframe.contentWindow?.scrollTo(prevScrollX, prevScrollY);
      } catch {
        /* ignore */
      }
      iframe.removeEventListener('load', restoreScroll);
    };
    iframe.addEventListener('load', restoreScroll, { once: true });
    try {
      iframe.contentWindow?.location.reload();
    } catch {
      const current = iframe.src;
      iframe.src = '';
      setTimeout(() => {
        iframe.src = current;
      }, 30);
    }
    setTimeout(() => setRefreshSpinning(false), 600);
  };

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
    // 古い contentDocument から念のためデタッチしてから再アタッチ
    detachInspector(iframe);
    if (isEditMode) {
      attachInspector(iframe);
    }
    return () => detachInspector(iframe);
  }, [isEditMode, loaded, iframeLoadSeq]);


  if (!artifact) return null;

  const publicPreviewUrl = artifact.preview_url.startsWith('/artifacts/')
    ? artifact.preview_url.replace(/^\/artifacts\//, '/preview/')
    : artifact.preview_url;

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
        <button
          onClick={handleRefresh}
          className="shrink-0 rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
          title="プレビューを再読み込み"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${refreshSpinning ? 'animate-spin' : ''}`} />
        </button>
        <a
          href={publicPreviewUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="shrink-0 rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
          title="仮公開URLを開く"
        >
          <ExternalLink className="h-3.5 w-3.5" />
        </a>
        {isEditMode && (
          <div className="flex overflow-hidden rounded-md border border-border">
            <button
              onClick={() => setInspectorMode('comment')}
              className={`flex items-center gap-1 px-2 py-1 text-xs transition-colors ${
                inspectorMode === 'comment'
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-background text-muted-foreground hover:bg-muted'
              }`}
              title="コメントモード"
            >
              <MessageSquare className="h-3 w-3" />
              コメント
            </button>
            <button
              onClick={() => setInspectorMode('edit')}
              className={`flex items-center gap-1 px-2 py-1 text-xs transition-colors ${
                inspectorMode === 'edit'
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-background text-muted-foreground hover:bg-muted'
              }`}
              title="手動編集モード"
            >
              <Sliders className="h-3 w-3" />
              編集
            </button>
          </div>
        )}
        <Button
          variant={isEditMode ? 'default' : 'ghost'}
          size="sm"
          className="h-7 px-2"
          onClick={toggleEditMode}
        >
          <Edit3 className="mr-1 h-3.5 w-3.5" />
          {isEditMode ? '終了' : '編集ON'}
        </Button>
        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={closePreview}>
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>
      <div className="flex flex-1 overflow-hidden bg-background">
        <div className="relative flex-1 overflow-hidden">
          <iframe
            ref={iframeRef}
            src={artifact.preview_url}
            onLoad={() => {
              setLoaded(true);
              setIframeLoadSeq((s) => s + 1);
            }}
            className="h-full w-full border-0"
            title={artifact.label || artifact.slug}
          />
          {isEditMode && inspectorMode === 'comment' && (
            <CommentPopover iframeRef={iframeRef} onSubmit={onSubmitComment} />
          )}
          {isEditMode && (
            <div className="pointer-events-none absolute left-0 right-0 top-0 flex justify-center gap-2 p-2">
              <div className="pointer-events-auto rounded-full bg-primary/90 px-3 py-1 text-xs font-medium text-primary-foreground shadow">
                {inspectorMode === 'comment'
                  ? '編集モード — 要素をクリックしてコメント'
                  : '編集モード — 要素をクリックして手動編集'}
              </div>
            </div>
          )}
        </div>
        {isEditMode && inspectorMode === 'edit' && <InspectorPanel />}
      </div>
    </div>
  );
}
