'use client';

import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { ChevronDown, Edit3, ExternalLink, MessageSquare, Monitor, RefreshCw, Sliders, Smartphone, Tablet, X } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';

import { Button } from '@/components/ui/button';
import { usePreviewStore, type ArtifactRecord } from '@/stores/preview-store';
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
  const scaleContainerRef = useRef<HTMLDivElement>(null);
  const [loaded, setLoaded] = useState(false);
  const [showSwitcher, setShowSwitcher] = useState(false);
  const [refreshSpinning, setRefreshSpinning] = useState(false);
  const [deviceWidth, setDeviceWidth] = useState<number>(1440);
  const [containerSize, setContainerSize] = useState({ w: 0, h: 0 });

  useLayoutEffect(() => {
    const el = scaleContainerRef.current;
    if (!el) return;
    const update = () => {
      setContainerSize({ w: el.clientWidth, h: el.clientHeight });
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const scale = containerSize.w > 0 ? Math.min(1, containerSize.w / deviceWidth) : 1;
  const scaledHeight = scale > 0 ? containerSize.h / scale : containerSize.h;

  const handleRefresh = () => {
    const iframe = iframeRef.current;
    if (!iframe) return;
    setRefreshSpinning(true);
    // リロード前のスクロール位置を保持 → ロード後に復元
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
        <div className="flex overflow-hidden rounded-md border border-border">
          {[
            { w: 1440, icon: Monitor, title: 'デスクトップ (1440px)' },
            { w: 768, icon: Tablet, title: 'タブレット (768px)' },
            { w: 375, icon: Smartphone, title: 'モバイル (375px)' },
          ].map(({ w, icon: Icon, title }) => (
            <button
              key={w}
              onClick={() => setDeviceWidth(w)}
              className={`px-1.5 py-1 transition-colors ${
                deviceWidth === w
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-background text-muted-foreground hover:bg-muted'
              }`}
              title={title}
            >
              <Icon className="h-3.5 w-3.5" />
            </button>
          ))}
        </div>
        <button
          onClick={handleRefresh}
          className="shrink-0 rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
          title="プレビューを再読み込み"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${refreshSpinning ? 'animate-spin' : ''}`} />
        </button>
        <a
          href={artifact.preview_url}
          target="_blank"
          rel="noopener noreferrer"
          className="shrink-0 rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
          title="新しいタブで開く"
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
        <div
          ref={scaleContainerRef}
          className="relative flex-1 overflow-hidden bg-muted/30"
        >
          {containerSize.w > 0 && (
            <iframe
              ref={iframeRef}
              src={artifact.preview_url}
              onLoad={() => setLoaded(true)}
              className="absolute left-0 top-0 border-0 bg-background shadow-xl"
              style={{
                width: deviceWidth,
                height: scaledHeight,
                transform: `scale(${scale})`,
                transformOrigin: 'top left',
              }}
              title={artifact.label || artifact.slug}
            />
          )}
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
          <div className="pointer-events-none absolute bottom-2 right-2 rounded-md bg-background/80 px-2 py-0.5 text-[10px] text-muted-foreground backdrop-blur">
            {deviceWidth}px × {Math.round(scale * 100)}%
          </div>
        </div>
        {isEditMode && inspectorMode === 'edit' && <InspectorPanel />}
      </div>
    </div>
  );
}
