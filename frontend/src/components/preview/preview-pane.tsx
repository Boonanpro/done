'use client';

import { useEffect, useRef, useState } from 'react';
import { ChevronDown, Copy, Edit3, ExternalLink, Globe2, MessageSquare, RefreshCw, Sliders, X } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { usePreviewStore, flushInspectorEdits, type ArtifactRecord } from '@/stores/preview-store';
import { attachInspector, detachInspector } from './iframe-inspector';
import { CommentPopover } from './comment-popover';
import { InspectorPanel } from './inspector-panel';

const FALLBACK_SHARE_ORIGIN = 'https://kittoku.vercel.app';

function publicShareOrigin(): string {
  const configured = process.env.NEXT_PUBLIC_SHARE_ORIGIN?.trim();
  if (configured) return configured.replace(/\/+$/, '');
  if (typeof window === 'undefined') return FALLBACK_SHARE_ORIGIN;

  const { origin, hostname } = window.location;
  const isLocalPreview =
    hostname === 'localhost' ||
    hostname === '127.0.0.1' ||
    hostname.startsWith('100.') ||
    hostname.startsWith('192.168.') ||
    hostname.startsWith('10.');

  return isLocalPreview ? FALLBACK_SHARE_ORIGIN : origin;
}

function absolutePublicUrl(pathOrUrl: string): string {
  try {
    return new URL(pathOrUrl, publicShareOrigin()).toString();
  } catch {
    return `${publicShareOrigin()}/${pathOrUrl.replace(/^\/+/, '')}`;
  }
}

async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // Fall through to the textarea fallback.
  }

  try {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.setAttribute('readonly', '');
    textarea.style.position = 'fixed';
    textarea.style.left = '-9999px';
    textarea.style.top = '0';
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    const copied = document.execCommand('copy');
    document.body.removeChild(textarea);
    return copied;
  } catch {
    return false;
  }
}

export function PreviewPane({ onSubmitComment }: { onSubmitComment: () => void }) {
  const queryClient = useQueryClient();
  const artifact = usePreviewStore((s) => s.artifact);
  const projectId = usePreviewStore((s) => s.projectId);
  const isEditMode = usePreviewStore((s) => s.isEditMode);
  const inspectorMode = usePreviewStore((s) => s.inspectorMode);
  const setInspectorMode = usePreviewStore((s) => s.setInspectorMode);
  const closePreview = usePreviewStore((s) => s.closePreview);
  const toggleEditMode = usePreviewStore((s) => s.toggleEditMode);
  const openArtifact = usePreviewStore((s) => s.openArtifact);

  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [loadedArtifactId, setLoadedArtifactId] = useState<string | null>(null);
  const [showSwitcher, setShowSwitcher] = useState(false);
  const [refreshSpinning, setRefreshSpinning] = useState(false);
  // iframe が load するたびに increment する。attachInspector 再実行の deps に入れ、
  // リフレッシュや内部ナビゲーション後も新 contentDocument に再アタッチする
  const [iframeLoadSeq, setIframeLoadSeq] = useState(0);

  const refreshArtifacts = () => {
    queryClient.invalidateQueries({ queryKey: ['chat-artifacts', projectId] });
  };

  const publishPreviewMutation = useMutation({
    mutationFn: async () => {
      if (!artifact) throw new Error('No artifact selected');
      await flushInspectorEdits();
      const share_url = artifact.share_url || `/preview/${artifact.slug}`;
      return {
        ...artifact,
        share_url,
        draft_url: artifact.draft_url || share_url,
        publish_status: artifact.publish_status || 'preview_live',
      } satisfies ArtifactRecord;
    },
    onSuccess: async (updated) => {
      refreshArtifacts();
      if (projectId) openArtifact(projectId, updated);
      const url = absolutePublicUrl(updated.share_url || `/preview/${updated.slug}`);
      const copied = await copyText(url);
      if (copied) {
        toast.success('共有URLをコピーしました');
      } else {
        toast.error('クリップボードにコピーできませんでした', { description: url });
      }
    },
    onError: (err) => {
      toast.error('共有URLの準備に失敗しました', { description: String(err).slice(0, 160) });
    },
  });

  const connectDomainMutation = useMutation({
    mutationFn: async (domain: string) => {
      if (!artifact) throw new Error('No artifact selected');
      await flushInspectorEdits();
      const res = await fetch(`/api/v1/chat-artifact/${artifact.id}/connect-domain`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ domain }),
      });
      if (!res.ok) throw new Error(await res.text());
      return res.json() as Promise<ArtifactRecord>;
    },
    onSuccess: (updated) => {
      refreshArtifacts();
      if (projectId) openArtifact(projectId, updated);
      toast.success('本公開URLを設定しました');
    },
    onError: (err) => {
      toast.error('本公開の設定に失敗しました', { description: String(err).slice(0, 160) });
    },
  });

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

  const loaded = artifact ? loadedArtifactId === artifact.id : false;

  const publicPreviewUrl = artifact?.preview_url.startsWith('/artifacts/')
    ? artifact.preview_url.replace(/^\/artifacts\//, '/preview/')
    : artifact?.preview_url || '';
  const draftUrl = artifact ? artifact.draft_url || publicPreviewUrl : '';
  const shareUrl = artifact ? artifact.share_url || draftUrl || publicPreviewUrl : '';
  const publicShareUrl = shareUrl ? absolutePublicUrl(shareUrl) : '';
  const iframeSrc = draftUrl || publicPreviewUrl || shareUrl;

  useEffect(() => {
    setLoadedArtifactId(null);
    setIframeLoadSeq(0);
  }, [artifact?.id, iframeSrc]);

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

  const isWebsite = artifact.artifact_type === 'website';
  const handleConnectDomain = () => {
    const domain = window.prompt('本公開するドメインを入力してください（例: example.com）', artifact.custom_domain || '');
    if (!domain?.trim()) return;
    connectDomainMutation.mutate(domain.trim());
  };

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
        <button
          onClick={() => publishPreviewMutation.mutate()}
          disabled={publishPreviewMutation.isPending}
          className="shrink-0 rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50"
          title="共有URLをコピー"
        >
          <Copy className="h-3.5 w-3.5" />
        </button>
        <a
          href={publicShareUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="shrink-0 rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
          title="仮公開URLを開く"
        >
          <ExternalLink className="h-3.5 w-3.5" />
        </a>
        {isWebsite && (
          <button
            onClick={handleConnectDomain}
            disabled={connectDomainMutation.isPending}
            className="shrink-0 rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50"
            title="ドメインを設定"
          >
            <Globe2 className="h-3.5 w-3.5" />
          </button>
        )}
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
            key={`${artifact.id}:${iframeSrc}`}
            ref={iframeRef}
            src={iframeSrc}
            onLoad={() => {
              setLoadedArtifactId(artifact.id);
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
