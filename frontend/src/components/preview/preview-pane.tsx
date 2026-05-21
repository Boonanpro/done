'use client';

import { useEffect, useRef, useState } from 'react';
import { ChevronDown, ClipboardList, Copy, Edit3, ExternalLink, MessageSquare, RefreshCw, Redo2, Rocket, Sliders, Undo2, X } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { usePreviewStore, flushInspectorEdits, type ArtifactRecord } from '@/stores/preview-store';
import { useEditHistoryStore } from '@/stores/edit-history-store';
import { artifactProductionUrl, artifactSharePath } from '@/lib/artifact-paths';
import { attachInspector, detachInspector } from './iframe-inspector';
import { CommentPopover } from './comment-popover';
import { InspectorPanel } from './inspector-panel';
import { PublishModal } from './publish-modal';
import { DeliveryModal } from './delivery-modal';

const FALLBACK_SHARE_ORIGIN = 'https://frontend-mikis-projects-86652663.vercel.app';

/** Undo / Redo ボタン。編集中のみ表示。 */
function UndoRedoButtons() {
  const undoStack = useEditHistoryStore((s) => s.undoStack);
  const redoStack = useEditHistoryStore((s) => s.redoStack);
  const undo = useEditHistoryStore((s) => s.undo);
  const redo = useEditHistoryStore((s) => s.redo);
  const bumpContentVersion = usePreviewStore((s) => s.bumpContentVersion);
  const canUndo = undoStack.length > 0;
  const canRedo = redoStack.length > 0;
  return (
    <>
      <button
        type="button"
        onClick={async () => {
          const ok = await undo();
          if (ok) bumpContentVersion();
        }}
        disabled={!canUndo}
        title={canUndo ? `Undo: ${undoStack[undoStack.length - 1]?.summary}` : '巻き戻すものがありません'}
        className="shrink-0 rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-30"
      >
        <Undo2 className="h-3.5 w-3.5" />
      </button>
      <button
        type="button"
        onClick={async () => {
          const ok = await redo();
          if (ok) bumpContentVersion();
        }}
        disabled={!canRedo}
        title={canRedo ? `Redo: ${redoStack[redoStack.length - 1]?.summary}` : 'やり直すものがありません'}
        className="shrink-0 rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-30"
      >
        <Redo2 className="h-3.5 w-3.5" />
      </button>
    </>
  );
}

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

function cleanArtifactUrl(artifact: ArtifactRecord, pathOrUrl: string): string {
  return (
    artifactProductionUrl({
      slug: artifact.slug,
      pathOrUrl,
      productionUrl: artifact.production_url,
      customDomain: artifact.custom_domain,
    }) || absolutePublicUrl(artifactSharePath(pathOrUrl || artifact.slug))
  );
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
  const artifactRoomId = artifact?.room_id || null;
  const isEditMode = usePreviewStore((s) => s.isEditMode);
  const inspectorMode = usePreviewStore((s) => s.inspectorMode);
  const setInspectorMode = usePreviewStore((s) => s.setInspectorMode);
  const closePreview = usePreviewStore((s) => s.closePreview);
  const toggleEditMode = usePreviewStore((s) => s.toggleEditMode);
  const openArtifact = usePreviewStore((s) => s.openArtifact);
  const contentVersion = usePreviewStore((s) => s.contentVersion);
  const bumpContentVersion = usePreviewStore((s) => s.bumpContentVersion);

  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [loadedArtifactId, setLoadedArtifactId] = useState<string | null>(null);
  const [showSwitcher, setShowSwitcher] = useState(false);
  const [showPublishModal, setShowPublishModal] = useState(false);
  const [showDeliveryModal, setShowDeliveryModal] = useState(false);
  const [refreshSpinning, setRefreshSpinning] = useState(false);
  // iframe が load するたびに increment する。attachInspector 再実行の deps に入れ、
  // リフレッシュや内部ナビゲーション後も新 contentDocument に再アタッチする
  const [iframeLoadSeq, setIframeLoadSeq] = useState(0);

  const refreshArtifacts = () => {
    queryClient.invalidateQueries({ queryKey: ['chat-artifacts'] });
  };

  const publishPreviewMutation = useMutation({
    mutationFn: async () => {
      if (!artifact) throw new Error('No artifact selected');
      await flushInspectorEdits();
      const share_url = artifactSharePath(artifact.share_url || artifact.preview_url || artifact.slug);
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
      const url = cleanArtifactUrl(updated, updated.share_url || updated.preview_url || updated.slug);
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


  const handleRefresh = async () => {
    if (!iframeRef.current) return;
    setRefreshSpinning(true);
    // 未送信のインスペクタ編集をまず flush（リロードで消さないため）。
    // flush 成功時は内部で contentVersion が bump され iframe が新URLで再ロードされる。
    await flushInspectorEdits();
    // flush で bump されなかった場合（未送信編集ゼロ）でも、Refresh ボタンは
    // 「明示的に最新を取りに行く」操作なので必ず bump して CDN をバイパスする。
    bumpContentVersion();
    setTimeout(() => setRefreshSpinning(false), 600);
  };

  const { data: artifacts = [] } = useQuery<ArtifactRecord[]>({
    queryKey: ['chat-artifacts', artifactRoomId || projectId],
    queryFn: async () => {
      const query = artifactRoomId
        ? `?room_id=${artifactRoomId}`
        : projectId
          ? `?project_id=${projectId}`
          : '';
      const res = await fetch(
        `/api/v1/chat-artifact${query}`,
        { credentials: 'include' }
      );
      if (!res.ok) return [];
      return res.json();
    },
    enabled: !!artifactRoomId || !!projectId,
    staleTime: 10_000,
  });

  const loaded = artifact ? loadedArtifactId === artifact.id : false;

  const publicPreviewUrl = artifact ? artifactSharePath(artifact.preview_url || artifact.slug) : '';
  const draftUrl = artifact ? artifact.draft_url || publicPreviewUrl : '';
  const shareUrl = artifact ? artifact.share_url || draftUrl || publicPreviewUrl : '';
  const publicShareUrl = artifact && shareUrl ? cleanArtifactUrl(artifact, shareUrl) : '';
  const baseIframeSrc = draftUrl || publicPreviewUrl || shareUrl;
  // contentVersion を URL に乗せて Vercel CDN / ブラウザキャッシュをバイパスする。
  // 初回は素のURLでCDNキャッシュを活かし、編集が走ったら ?t=N で新キャッシュキーへ。
  const iframeSrc = baseIframeSrc && contentVersion > 0
    ? `${baseIframeSrc}${baseIframeSrc.includes('?') ? '&' : '?'}t=${contentVersion}`
    : baseIframeSrc;

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

  // Cmd+Z / Ctrl+Z で Undo、Cmd+Shift+Z / Ctrl+Y で Redo。
  //
  // iframe 内にフォーカスがある時、parent window の keydown は発火しない。
  // そこで iframe.contentWindow / iframe.contentDocument にも capture: true で
  // 同じハンドラを bind する。capture phase なので、iframe 内の任意要素より先に走る。
  // editMode が ON の間は常時バインドし、選択中/非選択中によらず効くようにする。
  useEffect(() => {
    if (!isEditMode) return;
    const reloadIframe = () => {
      // contentVersion を bump → iframeSrc が ?t=N で変わり、iframe が完全再ロード（CDNキャッシュもバイパス）。
      bumpContentVersion();
    };
    const handler = async (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey;
      if (!mod) return;
      // input/textarea/contentEditable 上では OS の undo に任せる
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) {
        return;
      }
      const key = e.key.toLowerCase();
      if (key === 'z' && !e.shiftKey) {
        e.preventDefault();
        e.stopPropagation();
        const store = useEditHistoryStore.getState();
        if (store.canUndo()) {
          const ok = await store.undo();
          if (ok) reloadIframe();
        } else {
          toast.info('これ以上戻せません');
        }
        return;
      }
      if ((key === 'z' && e.shiftKey) || key === 'y') {
        e.preventDefault();
        e.stopPropagation();
        const store = useEditHistoryStore.getState();
        if (store.canRedo()) {
          const ok = await store.redo();
          if (ok) reloadIframe();
        } else {
          toast.info('これ以上やり直せません');
        }
      }
    };
    const wrap = (e: Event) => void handler(e as KeyboardEvent);
    // parent window（Inspector パネル側、編集モードトグル後など）
    window.addEventListener('keydown', wrap, { capture: true });
    // iframe 内のあらゆる場所からも拾う
    const iframe = iframeRef.current;
    const innerWin = iframe?.contentWindow as Window | null;
    const innerDoc = iframe?.contentDocument;
    innerWin?.addEventListener('keydown', wrap, { capture: true });
    innerDoc?.addEventListener('keydown', wrap, { capture: true });
    return () => {
      window.removeEventListener('keydown', wrap, { capture: true });
      innerWin?.removeEventListener('keydown', wrap, { capture: true });
      innerDoc?.removeEventListener('keydown', wrap, { capture: true });
    };
  }, [isEditMode, loaded, iframeLoadSeq, bumpContentVersion]);


  if (!artifact) return null;

  const isWebsite = artifact.artifact_type === 'website';

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
        {isEditMode && <UndoRedoButtons />}
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
        {!isWebsite && (
          <button
            onClick={() => setShowDeliveryModal(true)}
            className="shrink-0 rounded bg-primary px-2 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90"
            title="納品準備"
          >
            <ClipboardList className="mr-1 inline h-3 w-3" />
            納品準備
          </button>
        )}
        {isWebsite && (
          <button
            onClick={() => setShowPublishModal(true)}
            className="shrink-0 rounded bg-primary px-2 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90"
            title="カスタムドメインを購入して公開"
          >
            <Rocket className="mr-1 inline h-3 w-3" />
            公開
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
      {artifact && (
        <PublishModal
          open={showPublishModal}
          onOpenChange={setShowPublishModal}
          artifact={artifact}
          onPublished={() => refreshArtifacts()}
        />
      )}
      {artifact && (
        <DeliveryModal
          open={showDeliveryModal}
          onOpenChange={setShowDeliveryModal}
          artifact={artifact}
          publicUrl={publicShareUrl}
          onRequestDomain={() => setShowPublishModal(true)}
          onUpdated={(updated) => {
            if (projectId) openArtifact(projectId, updated);
            refreshArtifacts();
          }}
        />
      )}
    </div>
  );
}
