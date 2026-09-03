'use client';

import { useEffect, useRef, useState } from 'react';
import { ChevronDown, ClipboardList, Copy, Edit3, ExternalLink, Loader2, MessageSquare, RefreshCw, Redo2, Rocket, Sliders, Undo2, X } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { usePreviewStore, flushInspectorEdits, type ArtifactRecord } from '@/stores/preview-store';
import { useEditHistoryStore } from '@/stores/edit-history-store';
import { artifactProductionUrl, artifactSharePath, KNOWN_CUSTOM_DOMAINS } from '@/lib/artifact-paths';
import { attachInspectorBridge, detachInspectorBridge, sendToIframe } from './inspector-bridge';
import type { OverrideRow } from '@/lib/inspector-protocol';
import { CommentPopover } from './comment-popover';
import { InspectorPanel } from './inspector-panel';
import { PublishModal } from './publish-modal';
import { DeliveryModal } from './delivery-modal';

const LEGACY_SHARE_ORIGIN = 'https://frontend-mikis-projects-86652663.vercel.app';

const DOMAIN_PUBLICATION_LABEL: Record<string, string> = {
  domain_pending: '公開を開始中…',
  domain_preparing: 'サイトを準備中…',
  domain_registering: 'ドメインを取得・設定中…',
  domain_failed: '公開を確認中',
};

function isDomainPublicationRunning(status?: string | null) {
  return status === 'domain_pending' || status === 'domain_preparing' || status === 'domain_registering';
}

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
  if (configured && configured.replace(/\/+$/, '') !== LEGACY_SHARE_ORIGIN) {
    return configured.replace(/\/+$/, '');
  }
  if (typeof window === 'undefined') return '';
  // 2サーバー構成: ダッシュボードは本番ビルド(例: 3000)、成果物プレビューは
  // HMR が要るので開発サーバー(例: 3001)。同じホスト名でポートだけ変える
  // （Cookie はホスト単位なので認証は共有される）。ポート無しのホスト
  // （トンネル/Vercel 経由）では同一オリジンのまま。
  const previewPort = process.env.NEXT_PUBLIC_PREVIEW_PORT?.trim();
  const { protocol, hostname, port } = window.location;
  if (previewPort && port && port !== previewPort) {
    return `${protocol}//${hostname}:${previewPort}`;
  }
  return window.location.origin;
}

function absolutePublicUrl(pathOrUrl: string): string {
  const origin = publicShareOrigin();
  if (!origin) return pathOrUrl;
  try {
    return new URL(pathOrUrl, origin).toString();
  } catch {
    return `${origin}/${pathOrUrl.replace(/^\/+/, '')}`;
  }
}

function cleanArtifactUrl(artifact: ArtifactRecord, pathOrUrl: string): string {
  const releaseUrl = absolutePublicUrl(pathOrUrl || artifactSharePath(artifact.slug));

  // A custom domain is the public address once it has been attached.  Until
  // then, use the concrete URL recorded for this artifact's dedicated release.
  const hasCustomDomain =
    !!artifact.production_url ||
    !!artifact.custom_domain ||
    (KNOWN_CUSTOM_DOMAINS[artifact.slug]?.length ?? 0) > 0;
  if (!hasCustomDomain) return releaseUrl;

  return (
    artifactProductionUrl({
      slug: artifact.slug,
      pathOrUrl,
      productionUrl: artifact.production_url,
      customDomain: artifact.custom_domain,
    }) || releaseUrl
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

export function PreviewPane({ onAddComment }: { onAddComment: () => void }) {
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
  const updateArtifact = usePreviewStore((s) => s.updateArtifact);
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
    // The button itself is the status display.  While it is working, refresh
    // this artifact automatically; no separate "check status" action exists.
    refetchInterval: isDomainPublicationRunning(artifact?.publish_status) ? 2_500 : false,
  });

  const saveEditsMutation = useMutation({
    mutationFn: async () => {
      if (!artifact) throw new Error('No artifact selected');
      if (!await flushInspectorEdits()) throw new Error('下書きの保存に失敗しました。公開は行っていません。');
      const res = await fetch(`/api/v1/inspector-overrides/publish?slug=${encodeURIComponent(artifact.slug)}`, {
        method: 'POST', credentials: 'include',
      });
      if (!res.ok) throw new Error(await res.text());
      return res.json() as Promise<{ revision: number }>;
    },
    onSuccess: (release) => {
      toast.success('保存しました', { description: `公開版 ${release.revision} を反映しました` });
    },
    onError: (err) => toast.error('保存できませんでした', { description: String(err).slice(0, 160) }),
  });

  // A paid domain setup updates the artifact from the server in the background.
  // Keep an already-open full-screen preview in sync and reload it at its new
  // production URL as soon as that update arrives.
  useEffect(() => {
    if (!artifact) return;
    const latest = artifacts.find((candidate) => candidate.id === artifact.id);
    if (!latest) return;
    if (
      latest.production_url !== artifact.production_url ||
      latest.custom_domain !== artifact.custom_domain ||
      latest.delivery_url !== artifact.delivery_url ||
      latest.publish_status !== artifact.publish_status ||
      latest.last_publish_error !== artifact.last_publish_error
    ) {
      updateArtifact(latest);
    }
  }, [artifacts, artifact, updateArtifact]);

  const loaded = artifact ? loadedArtifactId === artifact.id : false;

  const publicPreviewUrl = artifact ? artifactSharePath(artifact.preview_url || artifact.slug) : '';
  const draftUrl = artifact ? artifact.draft_url || publicPreviewUrl : '';
  const shareUrl = artifact ? artifact.share_url || draftUrl || publicPreviewUrl : '';
  // delivery_url comes from the release ledger.  It is the same actual Vercel
  // release used by the full-screen view, and takes precedence over retired
  // shared /preview paths left on older artifact cards.
  const releaseUrl = artifact?.delivery_url || draftUrl || shareUrl || publicPreviewUrl;
  const publicShareUrl = artifact && releaseUrl ? cleanArtifactUrl(artifact, releaseUrl) : '';
  // クロスオリジン化: プレビューiframe は成果物配信オリジンを
  // 読む。編集は inspector-bridge(postMessage) 経由なので別オリジンでも動く。
  const baseIframeSrc = absolutePublicUrl(releaseUrl);
  // ライブプレビューでは成果物に「プレビュー中」を伝える dan_preview=1 を必ず付与する。
  // 成果物側 (isDanPreview()) はこれを見てログイン/初期設定ゲートをスキップし、
  // 管理者として全画面を閲覧・編集できる。公開URL/共有URLには付かない（iframe src 限定）。
  // contentVersion は Vercel CDN / ブラウザキャッシュのバイパス用（編集が走ったら ?t=N）。
  const iframeSrc = (() => {
    if (!baseIframeSrc) return baseIframeSrc;
    const params = ['dan_preview=1'];
    if (contentVersion > 0) params.push(`t=${contentVersion}`);
    const sep = baseIframeSrc.includes('?') ? '&' : '?';
    return `${baseIframeSrc}${sep}${params.join('&')}`;
  })();

  useEffect(() => {
    setLoadedArtifactId(null);
    setIframeLoadSeq(0);
  }, [artifact?.id, iframeSrc]);

  // クロスオリジン Inspector: iframe と postMessage で通信するブリッジをアタッチ。
  // iframe 内の agent が選択/編集/適用を行い、ここは選択 snapshot 等を受けて store に反映する。
  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe || !loaded) return;
    const shareOrigin = publicShareOrigin();
    // The inspector message originates from the iframe, not from the
    // dashboard's public-share origin.  Dedicated artifact projects each
    // have their own Vercel origin, so accept the origin of the iframe we
    // actually mounted as well.  `attachInspectorBridge` additionally checks
    // event.source against this exact iframe; this is not a broad allow-list.
    let iframeOrigin = '';
    try {
      iframeOrigin = new URL(iframe.src, window.location.origin).origin;
    } catch {
      // An invalid iframe URL cannot produce a valid inspector message.
    }
    const allowed = [shareOrigin, iframeOrigin].filter(Boolean) as string[];

    const fetchOverrides = async (slug: string): Promise<OverrideRow[]> => {
      try {
        const res = await fetch(`/api/v1/inspector-overrides?slug=${encodeURIComponent(slug)}`, { credentials: 'include' });
        if (!res.ok) return [];
        const rows = (await res.json()) as OverrideRow[];
        return Array.isArray(rows) ? rows : [];
      } catch {
        return [];
      }
    };

    const pushModeAndOverrides = async (reportedSlug?: string) => {
      const st = usePreviewStore.getState();
      // iframe が実際に表示している slug を最優先（chat_artifact のラベルズレ対策）。
      const slug = reportedSlug || st.iframeSlug || st.artifact?.slug;
      if (slug) {
        const rows = await fetchOverrides(slug);
        if (rows.length) {
          st.seedModels(rows);
          sendToIframe({ type: 'inspector:apply-overrides', payload: { overrides: rows } });
        }
      }
      const s2 = usePreviewStore.getState();
      sendToIframe({ type: 'inspector:set-mode', payload: { mode: s2.isEditMode ? s2.inspectorMode : 'off' } });
      // 選択集合が残っていれば（コメント編集中の開き直し/リロード後など）、
      // iframe 側のハイライトを復元する。
      if (s2.isEditMode && s2.selectedElements.length) {
        const elementKeys = s2.selectedElements
          .map((el) => el.elementKey)
          .filter((k): k is string => !!k);
        if (elementKeys.length) {
          sendToIframe({ type: 'inspector:set-selection', payload: { elementKeys } });
        }
      }
    };

    const detach = attachInspectorBridge(
      iframe,
      {
        onReady: (slug) => {
          usePreviewStore.getState().setIframeSlug(slug);
          void pushModeAndOverrides(slug);
        },
        onReloaded: () => { void pushModeAndOverrides(); },
        onSelected: (snap) => usePreviewStore.getState().selectFromSnapshot(snap),
        onMultiSelected: (snaps) => usePreviewStore.getState().selectFromSnapshots(snaps),
        onTextDrafted: (elementKey, text) =>
          usePreviewStore.getState().commitText(elementKey, text, { applyToIframe: false }),
        onTextCommitted: (elementKey, text) =>
          usePreviewStore.getState().commitText(elementKey, text, { applyToIframe: false }),
        onSelectionRange: (payload) =>
          usePreviewStore.getState().setSelectionRange('elementKey' in payload && payload.elementKey ? payload : null),
      },
      allowed,
    );
    return detach;
  }, [loaded, iframeLoadSeq]);

  // 編集モード/inspectorモードが変わったら iframe にモードを通知。
  useEffect(() => {
    sendToIframe({ type: 'inspector:set-mode', payload: { mode: isEditMode ? inspectorMode : 'off' } });
  }, [isEditMode, inspectorMode, loaded, iframeLoadSeq]);

  // Cmd+Z / Ctrl+Z Undo・Cmd+Shift+Z / Ctrl+Y Redo（親ウィンドウのみ。iframe は別オリジンで
  // contentWindow に触れないため、フォーカスが iframe 内のときは効かない＝ step7 で agent 経由に拡張予定）。
  useEffect(() => {
    if (!isEditMode) return;
    const handler = async (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey;
      if (!mod) return;
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
      const key = e.key.toLowerCase();
      if (key === 'z' && !e.shiftKey) {
        e.preventDefault();
        e.stopPropagation();
        const store = useEditHistoryStore.getState();
        if (store.canUndo()) { const ok = await store.undo(); if (ok) bumpContentVersion(); }
        else toast.info('これ以上戻せません');
        return;
      }
      if ((key === 'z' && e.shiftKey) || key === 'y') {
        e.preventDefault();
        e.stopPropagation();
        const store = useEditHistoryStore.getState();
        if (store.canRedo()) { const ok = await store.redo(); if (ok) bumpContentVersion(); }
        else toast.info('これ以上やり直せません');
      }
    };
    const wrap = (e: Event) => void handler(e as KeyboardEvent);
    window.addEventListener('keydown', wrap, { capture: true });
    return () => window.removeEventListener('keydown', wrap, { capture: true });
  }, [isEditMode, bumpContentVersion]);


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
          title="全画面で開く"
        >
          <ExternalLink className="h-3.5 w-3.5" />
        </a>
        {!isWebsite && (
          <button
            onClick={() => setShowDeliveryModal(true)}
            className="shrink-0 rounded bg-primary px-2 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90"
            title="納品設定"
          >
            <ClipboardList className="mr-1 inline h-3 w-3" />
            納品設定
          </button>
        )}
        {isWebsite && (
          <button
            onClick={() => setShowPublishModal(true)}
            className={`shrink-0 rounded px-2 py-1 text-xs font-medium text-primary-foreground ${
              isDomainPublicationRunning(artifact.publish_status)
                ? 'cursor-default bg-amber-600'
                : artifact.publish_status === 'domain_failed'
                  ? 'bg-amber-600 hover:bg-amber-600/90'
                  : 'bg-primary hover:bg-primary/90'
            }`}
            disabled={isDomainPublicationRunning(artifact.publish_status)}
            title={DOMAIN_PUBLICATION_LABEL[artifact.publish_status || ''] || '独自ドメイン公開'}
          >
            {isDomainPublicationRunning(artifact.publish_status) ? (
              <Loader2 className="mr-1 inline h-3 w-3 animate-spin" />
            ) : (
              <Rocket className="mr-1 inline h-3 w-3" />
            )}
            {artifact.custom_domain
              ? `${artifact.custom_domain} を公開中`
              : DOMAIN_PUBLICATION_LABEL[artifact.publish_status || ''] || '独自ドメイン公開'}
          </button>
        )}
        {isEditMode && (
          <button
            onClick={() => saveEditsMutation.mutate()}
            disabled={saveEditsMutation.isPending}
            className="shrink-0 rounded bg-primary px-2 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
          >
            {saveEditsMutation.isPending ? '保存中…' : '保存'}
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
            <CommentPopover iframeRef={iframeRef} onSubmit={onAddComment} />
          )}
          {isEditMode && (
            <div className="pointer-events-none absolute left-0 right-0 top-0 flex justify-center gap-2 p-2">
              <div className="pointer-events-auto rounded-full bg-primary/90 px-3 py-1 text-xs font-medium text-primary-foreground shadow">
                {inspectorMode === 'comment'
                  ? '編集モード — クリックでコメント / Ctrl+クリックで複数選択'
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
