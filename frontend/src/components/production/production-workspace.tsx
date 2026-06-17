'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowLeft, Check, Clapperboard, Film, Loader2, Plus, RefreshCw, Trash2, Upload } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { type EditSequence, type ReviewAnnotation, type SessionPayload, VideoReviewEditor } from '@/components/video-review/video-review-editor';

type AssetStatus = 'registered' | 'processing' | 'proxy_ready' | 'failed' | 'missing';

type ProductionAsset = {
  id: string;
  room_id: string;
  kind: 'video' | 'image' | 'audio' | 'file';
  source_type: 'local_path' | 'nas_path' | 'cloud_url' | 'upload' | 'generated';
  original_uri: string;
  local_path?: string | null;
  proxy_path?: string | null;
  proxy_url?: string | null;
  thumbnail_url?: string | null;
  filename?: string | null;
  status: AssetStatus;
  metadata?: Record<string, unknown>;
  error?: string | null;
  created_at: string;
  updated_at: string;
};

type ProductionContent = {
  id: string;
  room_id: string;
  title: string;
  format: string;
  status: 'draft' | 'running' | 'ready' | 'failed';
  asset_ids: string[];
  timeline: Record<string, unknown>;
  outputs: Array<Record<string, unknown>>;
  created_at: string;
  updated_at: string;
};

type ProductionJob = {
  id: string;
  room_id: string;
  content_id: string;
  kind: string;
  status: 'queued' | 'running' | 'done' | 'failed';
  instruction: Record<string, unknown>;
  result: Record<string, unknown>;
  error?: string | null;
  created_at: string;
  updated_at: string;
};

type ProductionJobEvent = {
  created_at?: string;
  type?: string;
  text?: string;
  name?: string;
};

function formatDuration(value: unknown): string {
  const seconds = Number(value || 0);
  if (!Number.isFinite(seconds) || seconds <= 0) return '-';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}

function assetMediaPath(asset: ProductionAsset): string {
  return asset.proxy_path || asset.local_path || asset.original_uri;
}

function assetMediaUrl(asset: ProductionAsset): string | undefined {
  return asset.proxy_url || undefined;
}

function sequenceAssetForEditor(asset: ProductionAsset) {
  return {
    id: asset.id,
    url: asset.proxy_url || undefined,
    path: asset.proxy_url ? undefined : assetMediaPath(asset),
    thumbnail_url: asset.thumbnail_url || undefined,
    label: asset.filename || asset.original_uri,
    fps: asset.metadata?.fps as string | number | undefined,
  };
}

function makeUniqueTitle(baseTitle: string, existingTitles: string[]): string {
  const base = baseTitle.trim() || 'Content';
  const used = new Set(existingTitles.map((title) => title.trim()).filter(Boolean));
  if (!used.has(base)) return base;

  const match = base.match(/^(.*?)(?:\s+(\d+))?$/);
  const prefix = (match?.[1] || base).trim() || base;
  const start = Number(match?.[2] || 1);
  for (let index = Math.max(2, start + 1); index < 10000; index += 1) {
    const candidate = `${prefix} ${String(index).padStart(2, '0')}`;
    if (!used.has(candidate)) return candidate;
  }
  return `${prefix} ${Date.now()}`;
}

const WORKFLOW_PRESETS = [
  { id: 'video_ugc', label: '映像 -> UGC', format: '9:16', prompt: '自然なスマホ撮影風のUGC。冒頭に強い悩み訴求、途中で素材の良い部分と操作デモ、最後にCTA。' },
  { id: 'video_story', label: '映像 -> ストーリー', format: '9:16', prompt: 'SNSストーリー向け。短いカット、読みやすいテロップ、テンポ良いBGMで要点を伝える。' },
  { id: 'video_cinematic', label: '映像 -> 映画風', format: '16:9', prompt: '映画的な構図、落ち着いたカラーグレーディング、余白のある編集で印象重視に仕上げる。' },
  { id: 'image_ad', label: '画像 -> 広告画像', format: '4:5', prompt: '広告画像向け。商品やサービスが一目で分かり、訴求とCTAが明確な構成にする。' },
  { id: 'freeform', label: '自由制作', format: '9:16', prompt: '' },
] as const;

export function ProductionWorkspace({
  roomId,
}: {
  roomId: string;
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [assets, setAssets] = useState<ProductionAsset[]>([]);
  const [contents, setContents] = useState<ProductionContent[]>([]);
  const [selectedContent, setSelectedContent] = useState<ProductionContent | null>(null);
  const [uri, setUri] = useState('');
  const [sourceType, setSourceType] = useState<ProductionAsset['source_type']>('local_path');
  const [newContentTitle, setNewContentTitle] = useState('StyleUp UGC 01');
  const [contentFormat, setContentFormat] = useState('9:16');
  const [productionBrief, setProductionBrief] = useState('');
  const [workflowPreset, setWorkflowPreset] = useState<(typeof WORKFLOW_PRESETS)[number]['id']>('video_ugc');
  const [draftAssetIds, setDraftAssetIds] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isRegistering, setIsRegistering] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [jobs, setJobs] = useState<ProductionJob[]>([]);
  const [jobEvents, setJobEvents] = useState<ProductionJobEvent[]>([]);
  const [activeVideoAssetId, setActiveVideoAssetId] = useState<string | null>(null);

  const hasProcessing = useMemo(() => assets.some((a) => a.status === 'processing'), [assets]);
  const selectedContentAssets = useMemo(
    () => (selectedContent ? assets.filter((asset) => selectedContent.asset_ids.includes(asset.id)) : []),
    [assets, selectedContent]
  );
  const selectedSourceAssets = useMemo(
    () => selectedContentAssets.filter((asset) => asset.source_type !== 'generated'),
    [selectedContentAssets]
  );
  const sourceAssets = useMemo(() => assets.filter((asset) => asset.source_type !== 'generated'), [assets]);
  const draftAssets = useMemo(() => assets.filter((asset) => draftAssetIds.includes(asset.id)), [assets, draftAssetIds]);
  const videoAssets = useMemo(() => selectedSourceAssets.filter((asset) => asset.kind === 'video'), [selectedSourceAssets]);
  const primaryVideo = videoAssets.find((asset) => asset.id === activeVideoAssetId) || videoAssets[0] || null;

  useEffect(() => {
    if (!primaryVideo) {
      setActiveVideoAssetId(null);
      return;
    }
    if (!activeVideoAssetId || !videoAssets.some((asset) => asset.id === activeVideoAssetId)) {
      setActiveVideoAssetId(primaryVideo.id);
    }
  }, [activeVideoAssetId, primaryVideo, videoAssets]);

  const setUrlContentId = useCallback((contentId: string | null) => {
    const url = new URL(window.location.href);
    url.searchParams.set('production', '1');
    if (contentId) url.searchParams.set('content_id', contentId);
    else url.searchParams.delete('content_id');
    window.history.replaceState(null, '', url.toString());
  }, []);

  const loadAll = useCallback(async () => {
    if (!roomId) return;
    setIsLoading(true);
    try {
      const [assetRes, contentRes] = await Promise.all([
        fetch(`/api/v1/production-assets?room_id=${encodeURIComponent(roomId)}`, { credentials: 'include' }),
        fetch(`/api/v1/production-assets/contents?room_id=${encodeURIComponent(roomId)}`, { credentials: 'include' }),
      ]);
      if (!assetRes.ok) throw new Error(await assetRes.text());
      if (!contentRes.ok) throw new Error(await contentRes.text());
      setAssets(await assetRes.json());
      const nextContents = await contentRes.json();
      setContents(nextContents);
      const urlContentId = new URLSearchParams(window.location.search).get('content_id');
      setSelectedContent((current) =>
        current
          ? nextContents.find((content: ProductionContent) => content.id === current.id) || null
          : urlContentId
            ? nextContents.find((content: ProductionContent) => content.id === urlContentId) || null
            : null
      );
    } catch (error) {
      toast.error('Failed to load production workspace', { description: String(error).slice(0, 160) });
    } finally {
      setIsLoading(false);
    }
  }, [roomId]);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  useEffect(() => {
    if (!hasProcessing) return;
    const timer = window.setInterval(() => void loadAll(), 4000);
    return () => window.clearInterval(timer);
  }, [hasProcessing, loadAll]);

  const loadJobs = useCallback(async () => {
    if (!roomId || !selectedContent) {
      setJobs([]);
      return;
    }
    try {
      const res = await fetch(
        `/api/v1/production-assets/jobs?room_id=${encodeURIComponent(roomId)}&content_id=${encodeURIComponent(selectedContent.id)}`,
        { credentials: 'include' }
      );
      if (!res.ok) throw new Error(await res.text());
      const nextJobs = (await res.json()) as ProductionJob[];
      setJobs(nextJobs.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()));
      if (nextJobs.some((job) => job.status === 'done' || job.status === 'failed')) {
        void loadAll();
      }
    } catch (error) {
      toast.error('Failed to load production jobs', { description: String(error).slice(0, 160) });
    }
  }, [loadAll, roomId, selectedContent]);

  useEffect(() => {
    void loadJobs();
  }, [loadJobs]);

  useEffect(() => {
    if (!jobs.some((job) => job.status === 'queued' || job.status === 'running')) return;
    const timer = window.setInterval(() => void loadJobs(), 2000);
    return () => window.clearInterval(timer);
  }, [jobs, loadJobs]);

  const latestJob = jobs[0] || null;

  const loadJobEvents = useCallback(async () => {
    if (!roomId || !latestJob) {
      setJobEvents([]);
      return;
    }
    try {
      const res = await fetch(
        `/api/v1/production-assets/jobs/${encodeURIComponent(latestJob.id)}/events?room_id=${encodeURIComponent(roomId)}`,
        { credentials: 'include' }
      );
      if (!res.ok) throw new Error(await res.text());
      setJobEvents(await res.json());
    } catch {
      setJobEvents([]);
    }
  }, [latestJob, roomId]);

  useEffect(() => {
    void loadJobEvents();
  }, [loadJobEvents]);

  useEffect(() => {
    if (!latestJob || latestJob.status !== 'running') return;
    const timer = window.setInterval(() => void loadJobEvents(), 2000);
    return () => window.clearInterval(timer);
  }, [latestJob, loadJobEvents]);

  const registerAsset = async () => {
    if (!uri.trim()) {
      toast.error('Enter a path or URL');
      return;
    }
    setIsRegistering(true);
    try {
      const res = await fetch('/api/v1/production-assets/register', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          room_id: roomId,
          uri: uri.trim(),
          source_type: sourceType,
          make_proxy: true,
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      setUri('');
      toast.success('Asset registered');
      await loadAll();
    } catch (error) {
      toast.error('Failed to register asset', { description: String(error).slice(0, 180) });
    } finally {
      setIsRegistering(false);
    }
  };

  const uploadFiles = async (files: File[]) => {
    if (files.length === 0) return;
    const tooLarge = files.filter((file) => file.size > 500 * 1024 * 1024);
    if (tooLarge.length > 0) {
      toast.info('大容量素材はパス登録で追加してください', {
        description: `${tooLarge.map((file) => file.name).join(', ')} は500MBを超えています。PC/NAS上に置いたまま、下のパス登録を使います。`,
      });
      return;
    }
    setIsUploading(true);
    try {
      for (const file of files) {
        const form = new FormData();
        form.append('file', file);
        const res = await fetch(`/api/v1/production-assets/upload?room_id=${encodeURIComponent(roomId)}`, {
          method: 'POST',
          credentials: 'include',
          body: form,
        });
        if (!res.ok) throw new Error(await res.text());
      }
      toast.success('Upload complete');
      await loadAll();
    } catch (error) {
      toast.error('Upload failed', { description: String(error).slice(0, 180) });
    } finally {
      setIsUploading(false);
    }
  };

  const createProxy = async (asset: ProductionAsset) => {
    try {
      const res = await fetch(`/api/v1/production-assets/${asset.id}/proxy?room_id=${encodeURIComponent(roomId)}`, {
        method: 'POST',
        credentials: 'include',
      });
      if (!res.ok) throw new Error(await res.text());
      toast.success('Proxy job started');
      await loadAll();
    } catch (error) {
      toast.error('Proxy job failed', { description: String(error).slice(0, 180) });
    }
  };

  const createContent = async () => {
    const title = makeUniqueTitle(newContentTitle.trim() || `Content ${contents.length + 1}`, contents.map((content) => content.title));
    const selectedAssetIds = [...draftAssetIds];
    const selectedAssets = assets.filter((asset) => selectedAssetIds.includes(asset.id));
    if (selectedAssetIds.length === 0) {
      toast.error('素材を選択してください');
      return;
    }
    try {
      const res = await fetch('/api/v1/production-assets/contents', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          room_id: roomId,
          title,
          format: contentFormat,
          asset_ids: selectedAssetIds,
          timeline: {
            brief: productionBrief.trim(),
            workflow_preset: workflowPreset,
            format: contentFormat,
            source_asset_ids: selectedAssetIds,
            annotations: [],
          },
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      const content = await res.json();
      const instruction = {
        mode: 'dan_edit',
        content_id: content.id,
        content_title: content.title,
        asset_ids: selectedAssetIds,
        source_assets: selectedAssets.map((asset) => ({
          id: asset.id,
          kind: asset.kind,
          filename: asset.filename,
          local_path: asset.local_path,
          proxy_path: asset.proxy_path,
          source_type: asset.source_type,
          metadata: asset.metadata,
        })),
        brief: productionBrief.trim(),
        workflow_preset: workflowPreset,
        timeline: {
          brief: productionBrief.trim(),
          workflow_preset: workflowPreset,
          format: contentFormat,
          source_asset_ids: selectedAssetIds,
          annotations: [],
        },
      };
      const jobRes = await fetch('/api/v1/production-assets/jobs', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ room_id: roomId, content_id: content.id, instruction }),
      });
      if (!jobRes.ok) throw new Error(await jobRes.text());
      setContents((prev) => [...prev, content]);
      setSelectedContent(content);
      setUrlContentId(content.id);
      setDraftAssetIds([]);
      setProductionBrief('');
      setWorkflowPreset('video_ugc');
      setContentFormat('9:16');
      setNewContentTitle(makeUniqueTitle(newContentTitle.trim() || 'StyleUp UGC 01', [...contents.map((item) => item.title), title]));
      toast.success('制作を開始しました');
      window.setTimeout(() => {
        void loadAll();
      }, 1200);
    } catch (error) {
      toast.error('制作開始に失敗しました', { description: String(error).slice(0, 180) });
    }
  };

  const toggleAssetOnContent = async (asset: ProductionAsset) => {
    if (!selectedContent) {
      setDraftAssetIds((current) =>
        current.includes(asset.id) ? current.filter((id) => id !== asset.id) : [...current, asset.id]
      );
      return;
    }
    const nextAssetIds = selectedContent.asset_ids.includes(asset.id)
      ? selectedContent.asset_ids.filter((id) => id !== asset.id)
      : [...selectedContent.asset_ids, asset.id];
    const res = await fetch(
      `/api/v1/production-assets/contents/${selectedContent.id}?room_id=${encodeURIComponent(roomId)}`,
      {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ asset_ids: nextAssetIds }),
      }
    );
    if (!res.ok) {
      toast.error('Failed to update content assets');
      return;
    }
    const updated = await res.json();
    setSelectedContent(updated);
    setUrlContentId(updated.id);
    setContents((prev) => prev.map((content) => (content.id === updated.id ? updated : content)));
  };

  const createProductionJob = async (timeline: SessionPayload) => {
    if (!selectedContent) return;
    const instruction = {
      timeline,
      content_id: selectedContent.id,
      content_title: selectedContent.title,
      asset_ids: selectedSourceAssets.map((asset) => asset.id),
      source_assets: selectedSourceAssets.map((asset) => ({
        id: asset.id,
        kind: asset.kind,
        filename: asset.filename,
        local_path: asset.local_path,
        proxy_path: asset.proxy_path,
        source_type: asset.source_type,
        metadata: asset.metadata,
      })),
      mode: 'render_timeline',
    };
    try {
      const res = await fetch('/api/v1/production-assets/jobs', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ room_id: roomId, content_id: selectedContent.id, instruction }),
      });
      if (!res.ok) throw new Error(await res.text());
      toast.success('書き出しを開始しました');
      await loadJobs();
      window.setTimeout(() => {
        void loadJobs();
        void loadAll();
      }, 1200);
    } catch (error) {
      toast.error('Failed to queue production job', { description: String(error).slice(0, 180) });
    }
  };

  const requestDanEdit = async () => {
    if (!selectedContent) return;
    const selectedAssets = selectedSourceAssets;
    if (selectedAssets.length === 0) {
      toast.error('素材がありません');
      return;
    }
    const timeline = selectedContent.timeline || {};
    const instruction = {
      mode: 'dan_edit',
      content_id: selectedContent.id,
      content_title: selectedContent.title,
      asset_ids: selectedAssets.map((asset) => asset.id),
      source_assets: selectedAssets.map((asset) => ({
        id: asset.id,
        kind: asset.kind,
        filename: asset.filename,
        local_path: asset.local_path,
        proxy_path: asset.proxy_path,
        source_type: asset.source_type,
        metadata: asset.metadata,
      })),
      brief: typeof timeline.brief === 'string' ? timeline.brief : '',
      workflow_preset: typeof timeline.workflow_preset === 'string' ? timeline.workflow_preset : 'video_ugc',
      timeline: {
        ...timeline,
        format: selectedContent.format,
        source_asset_ids: selectedAssets.map((asset) => asset.id),
        annotations: [],
        sequence: undefined,
      },
    };
    try {
      const res = await fetch('/api/v1/production-assets/jobs', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ room_id: roomId, content_id: selectedContent.id, instruction }),
      });
      if (!res.ok) throw new Error(await res.text());
      toast.success('Danに制作を依頼しました');
      await loadJobs();
      window.setTimeout(() => {
        void loadJobs();
        void loadAll();
      }, 1200);
    } catch (error) {
      toast.error('Danへの制作依頼に失敗しました', { description: String(error).slice(0, 180) });
    }
  };

  const saveContentTimeline = async (timeline: SessionPayload) => {
    if (!selectedContent) return;
    const res = await fetch(
      `/api/v1/production-assets/contents/${selectedContent.id}?room_id=${encodeURIComponent(roomId)}`,
      {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ timeline }),
      }
    );
    if (!res.ok) throw new Error(await res.text());
    const updated = await res.json();
    setSelectedContent(updated);
    setContents((prev) => prev.map((content) => (content.id === updated.id ? updated : content)));
  };

  const deleteContent = async (content: ProductionContent) => {
    const res = await fetch(
      `/api/v1/production-assets/contents/${content.id}?room_id=${encodeURIComponent(roomId)}`,
      {
        method: 'DELETE',
        credentials: 'include',
      }
    );
    if (!res.ok) {
      toast.error('制作物を削除できませんでした');
      return;
    }
    if (selectedContent?.id === content.id) {
      setSelectedContent(null);
      setUrlContentId(null);
    }
    setContents((prev) => prev.filter((item) => item.id !== content.id));
    toast.success('制作物を削除しました');
  };

  if (selectedContent && primaryVideo && primaryVideo.status === 'processing') {
    return (
      <div className="flex h-full min-h-0 flex-col bg-background">
        <header className="flex shrink-0 items-center gap-3 border-b border-border px-5 py-3">
          <Button variant="ghost" size="sm" onClick={() => {
            setSelectedContent(null);
            setUrlContentId(null);
          }}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div className="min-w-0 flex-1">
            <h1 className="text-base font-semibold">{selectedContent.title}</h1>
            <p className="truncate text-xs text-muted-foreground">プロキシ動画を作成中です</p>
          </div>
          <Button variant="outline" size="sm" onClick={() => void loadAll()} disabled={isLoading}>
            <RefreshCw className={`mr-1 h-4 w-4 ${isLoading ? 'animate-spin' : ''}`} />
            更新
          </Button>
        </header>
        <div className="flex flex-1 items-center justify-center p-6">
          <div className="max-w-md rounded-md border border-border p-6 text-center">
            <Loader2 className="mx-auto h-6 w-6 animate-spin text-primary" />
            <div className="mt-3 text-sm font-medium">再生用の軽い動画を準備しています</div>
            <p className="mt-2 text-sm text-muted-foreground">
              大きい元動画を直接開くと重くなるため、プロキシ完成後にタイムラインを開きます。
            </p>
          </div>
        </div>
      </div>
    );
  }

  if (selectedContent && primaryVideo) {
    const mediaUrl = assetMediaUrl(primaryVideo);
    return (
      <VideoReviewEditor
        key={primaryVideo.id}
        embedded
        initialPath={mediaUrl ? undefined : assetMediaPath(primaryVideo)}
        initialUrl={mediaUrl}
        initialThumbnailUrl={primaryVideo.thumbnail_url || undefined}
        initialFps={primaryVideo.metadata?.fps as string | number | undefined}
        initialAnnotations={(selectedContent.timeline?.annotations as ReviewAnnotation[] | undefined) || undefined}
        initialSequence={(selectedContent.timeline?.sequence as EditSequence | undefined) || undefined}
        sequenceAssets={selectedSourceAssets.filter((asset) => asset.kind === 'video').map(sequenceAssetForEditor)}
        sidePanelTop={
          <div className="mb-3 space-y-3">
            <div className="rounded-md border border-border p-3">
              <div className="mb-2 flex items-center justify-between gap-2">
                <div className="text-sm font-medium">使用素材</div>
                <span className="text-xs text-muted-foreground">{selectedSourceAssets.length}個</span>
              </div>
              <div className="grid grid-cols-2 gap-2">
                {selectedSourceAssets.map((asset) => (
                  <div key={asset.id} className="overflow-hidden rounded border border-border bg-muted/30">
                    <div className="flex aspect-video items-center justify-center bg-muted">
                      {asset.thumbnail_url ? (
                        <img src={asset.thumbnail_url} alt="" className="h-full w-full object-cover" />
                      ) : (
                        <Film className="h-5 w-5 text-muted-foreground" />
                      )}
                    </div>
                    <div className="p-1.5">
                      <div className="truncate text-[11px] font-medium">{asset.filename || asset.original_uri}</div>
                      <div className="mt-0.5 text-[10px] text-muted-foreground">{asset.kind} / {formatDuration(asset.metadata?.duration)}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
            <div className="rounded-md border border-border p-3">
              <div className="mb-1 text-sm font-medium">制作ブリーフ</div>
              <div className="line-clamp-6 whitespace-pre-wrap text-xs text-muted-foreground">
                {typeof selectedContent.timeline?.brief === 'string' && selectedContent.timeline.brief.trim()
                  ? selectedContent.timeline.brief
                  : 'ブリーフ未設定'}
              </div>
              <Button className="mt-3 w-full" size="sm" onClick={() => void requestDanEdit()}>
                Danに制作を依頼
              </Button>
            </div>
            {selectedContent.outputs.length > 0 ? (
              <div className="rounded-md border border-border p-3">
                <div className="mb-2 text-sm font-medium">最新出力</div>
                <div className="space-y-2">
                  {selectedContent.outputs.slice(0, 3).map((output, index) => (
                    <div key={`${String(output.asset_id || output.path || index)}`} className="rounded border border-border bg-muted/30 p-2 text-xs">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-medium">{String(output.kind || 'video')}</span>
                        {typeof output.created_at === 'string' ? (
                          <span className="text-muted-foreground">{new Date(output.created_at).toLocaleTimeString()}</span>
                        ) : null}
                      </div>
                      {typeof output.url === 'string' ? (
                        <a
                          href={output.url}
                          target="_blank"
                          rel="noreferrer"
                          className="mt-1 block truncate text-primary underline-offset-2 hover:underline"
                        >
                          出力動画を開く
                        </a>
                      ) : null}
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
            <div className="rounded-md border border-border p-3">
              <div className="mb-2 flex items-center justify-between">
                <div className="text-sm font-medium">処理状況</div>
                <Button variant="ghost" size="sm" onClick={() => void loadJobs()}>
                  <RefreshCw className="h-4 w-4" />
                </Button>
              </div>
              {jobs.length === 0 ? (
                <p className="text-xs text-muted-foreground">まだ処理はありません。</p>
              ) : (
                <div className="space-y-2">
                  {jobEvents.length > 0 ? (
                    <div className="rounded border border-border bg-muted/30 p-2 text-xs">
                      <div className="mb-1 font-medium">Dan作業ログ</div>
                      <div className="max-h-40 space-y-1 overflow-y-auto">
                        {jobEvents.slice(-8).map((event, index) => (
                          <div key={`${event.created_at || index}-${index}`} className="text-muted-foreground">
                            <span className="mr-1 text-[10px] uppercase">{event.type || 'event'}</span>
                            <span>{event.name ? `${event.name}: ` : ''}{event.text || ''}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : null}
                  {jobs.slice(0, 4).map((job) => (
                    <div key={job.id} className="rounded border border-border bg-muted/30 p-2 text-xs">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-medium">{job.status}</span>
                        <span className="text-muted-foreground">{new Date(job.created_at).toLocaleTimeString()}</span>
                      </div>
                      {typeof job.result?.task_path === 'string' ? (
                        <div className="mt-1 truncate text-muted-foreground" title={job.result.task_path}>
                          {job.result.task_path}
                        </div>
                      ) : null}
                      {typeof job.result?.output_url === 'string' ? (
                        <a
                          href={job.result.output_url}
                          target="_blank"
                          rel="noreferrer"
                          className="mt-1 block truncate text-primary underline-offset-2 hover:underline"
                        >
                          出力動画を開く
                        </a>
                      ) : null}
                      {job.error ? <div className="mt-1 text-destructive">{job.error}</div> : null}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        }
        onBack={() => {
          setSelectedContent(null);
          setUrlContentId(null);
        }}
        onSaveTimeline={saveContentTimeline}
        onExecute={createProductionJob}
      />
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <header className="flex shrink-0 items-center gap-3 border-b border-border px-5 py-3">
        <Clapperboard className="h-5 w-5 text-primary" />
        <div className="min-w-0 flex-1">
          <h1 className="text-base font-semibold">制作</h1>
          <p className="truncate text-xs text-muted-foreground">素材を選び、作りたい内容を決めてからタイムラインで仕上げます。</p>
        </div>
        {selectedContent ? (
          <Button variant="outline" size="sm" onClick={() => setSelectedContent(null)}>
            <ArrowLeft className="mr-1 h-4 w-4" />
            Contents
          </Button>
        ) : null}
        <Button variant="outline" size="sm" onClick={() => void loadAll()} disabled={isLoading}>
          <RefreshCw className={`mr-1 h-4 w-4 ${isLoading ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </header>

      <main className="grid min-h-0 flex-1 grid-cols-[360px_1fr] overflow-hidden">
        <aside className="flex min-h-0 flex-col border-r border-border">
          <section
            className={`m-3 rounded-md border border-dashed p-4 ${isDragging ? 'border-primary bg-primary/5' : 'border-border'}`}
            onDragOver={(e) => {
              e.preventDefault();
              setIsDragging(true);
            }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setIsDragging(false);
              void uploadFiles(Array.from(e.dataTransfer.files || []));
            }}
          >
            <div className="flex items-center gap-2 text-sm font-medium">
              <Upload className="h-4 w-4" />
              素材を追加
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              500MB未満はここにドロップできます。大きい素材はPC/NASに置いてパスを登録します。
            </p>
            <input
              ref={inputRef}
              type="file"
              multiple
              className="hidden"
              onChange={(e) => void uploadFiles(Array.from(e.currentTarget.files || []))}
            />
            <Button variant="outline" size="sm" className="mt-3" onClick={() => inputRef.current?.click()} disabled={isUploading}>
              {isUploading ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : null}
              ファイルを選択
            </Button>
          </section>

          <section className="border-t border-border p-3">
            <div className="grid gap-2">
              <Label className="text-xs">PC/NAS/URLから登録</Label>
              <select
                value={sourceType}
                onChange={(e) => setSourceType(e.target.value as ProductionAsset['source_type'])}
                className="h-9 rounded-md border border-input bg-background px-2 text-sm"
              >
                <option value="local_path">ローカルパス</option>
                <option value="nas_path">NASパス</option>
                <option value="cloud_url">クラウドURL</option>
                <option value="upload">アップロード</option>
                <option value="generated">生成物</option>
              </select>
              <Input value={uri} onChange={(e) => setUri(e.target.value)} placeholder="D:\dan-workspace\media\clip.mp4" />
              <Button onClick={() => void registerAsset()} disabled={isRegistering}>
                {isRegistering ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Plus className="mr-1 h-4 w-4" />}
                登録
              </Button>
            </div>
          </section>

          <section className="min-h-0 flex-1 overflow-y-auto border-t border-border p-3">
            <div className="mb-2 text-sm font-medium">素材 ({sourceAssets.length})</div>
            <div className="space-y-2">
              {sourceAssets.map((asset) => {
                const linked = selectedContent
                  ? selectedContent.asset_ids.includes(asset.id)
                  : draftAssetIds.includes(asset.id);
                return (
                  <div
                    key={asset.id}
                    role="button"
                    tabIndex={0}
                    onClick={() => void toggleAssetOnContent(asset)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        void toggleAssetOnContent(asset);
                      }
                    }}
                    className={`w-full rounded-md border p-2 text-left transition-colors ${
                      linked ? 'border-primary bg-primary/5' : 'border-border hover:bg-muted'
                    }`}
                  >
                    <div className="flex gap-2">
                      <div className="relative flex h-16 w-24 shrink-0 items-center justify-center overflow-hidden rounded bg-muted">
                        {asset.thumbnail_url ? (
                          <img src={asset.thumbnail_url} alt="" className="h-full w-full object-cover" />
                        ) : asset.status === 'processing' ? (
                          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                        ) : (
                          <Film className="h-6 w-6 text-muted-foreground" />
                        )}
                        {asset.status === 'processing' ? (
                          <div className="absolute bottom-0 left-0 right-0 bg-black/60 px-1 py-0.5 text-[10px] text-white">生成中</div>
                        ) : null}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex min-w-0 items-start gap-2">
                          <span
                            className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border ${
                              linked ? 'border-primary bg-primary text-primary-foreground' : 'border-muted-foreground/50'
                            }`}
                          >
                            {linked ? <Check className="h-3 w-3" /> : null}
                          </span>
                          <div className="truncate text-xs font-medium">{asset.filename || asset.original_uri}</div>
                        </div>
                        <div className="mt-1 flex flex-wrap gap-1 text-[11px] text-muted-foreground">
                          <span>{asset.status}</span>
                          <span>{formatDuration(asset.metadata?.duration)}</span>
                          {asset.metadata?.width && asset.metadata?.height ? (
                            <span>{String(asset.metadata.width)}x{String(asset.metadata.height)}</span>
                          ) : null}
                        </div>
                        {asset.error ? <div className="mt-1 line-clamp-2 text-[11px] text-destructive">{asset.error}</div> : null}
                      </div>
                    </div>
                    {asset.status !== 'proxy_ready' && asset.kind === 'video' ? (
                      <div className="mt-2 flex justify-end">
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-7"
                          onClick={(event) => {
                            event.stopPropagation();
                            void createProxy(asset);
                          }}
                          disabled={asset.status === 'processing'}
                        >
                          Proxy
                        </Button>
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </section>
        </aside>

        <section className="min-h-0 overflow-y-auto p-5">
          {selectedContent ? (
            <div className="space-y-4">
              <div>
                <h2 className="text-lg font-semibold">{selectedContent.title}</h2>
                <p className="text-sm text-muted-foreground">左の素材から動画を追加するとタイムラインを開けます。</p>
              </div>
              <div className="rounded-md border border-border p-6 text-sm text-muted-foreground">
                まだ動画素材がありません。左の素材からこのコンテンツに追加してください。
              </div>
            </div>
          ) : (
            <div className="space-y-5">
              {draftAssetIds.length > 0 ? (
                <section className="rounded-md border border-border p-4">
                  <div className="grid gap-4">
                    <div>
                      <div className="flex items-center justify-between gap-2">
                        <div className="text-sm font-medium">今回使う素材</div>
                        <div className="text-xs text-muted-foreground">{draftAssets.length}個</div>
                      </div>
                      <div className="mt-2 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
                        {draftAssets.map((asset) => (
                          <div key={asset.id} className="overflow-hidden rounded-md border border-border bg-muted/30">
                            <div className="flex aspect-video items-center justify-center bg-muted">
                              {asset.thumbnail_url ? (
                                <img src={asset.thumbnail_url} alt="" className="h-full w-full object-cover" />
                              ) : asset.status === 'processing' ? (
                                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                              ) : (
                                <Film className="h-6 w-6 text-muted-foreground" />
                              )}
                            </div>
                            <div className="p-2">
                              <div className="truncate text-xs font-medium">{asset.filename || asset.original_uri}</div>
                              <div className="mt-1 text-[11px] text-muted-foreground">
                                {asset.kind} / {formatDuration(asset.metadata?.duration)}
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                    <div>
                      <div className="text-sm font-medium">制作タイプ</div>
                      <div className="mt-2 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
                        {WORKFLOW_PRESETS.map((preset) => (
                          <button
                            key={preset.id}
                            type="button"
                            onClick={() => {
                              setWorkflowPreset(preset.id);
                              setContentFormat(preset.format);
                              if (!productionBrief.trim() && preset.prompt) setProductionBrief(preset.prompt);
                            }}
                            className={`rounded-md border p-3 text-left text-sm ${
                              workflowPreset === preset.id ? 'border-primary bg-primary/10' : 'border-border hover:bg-muted'
                            }`}
                          >
                            <div className="font-medium">{preset.label}</div>
                            <div className="mt-1 text-xs text-muted-foreground">{preset.format}</div>
                          </button>
                        ))}
                      </div>
                    </div>
                    <div className="grid gap-2 md:grid-cols-[1fr_120px]">
                      <div className="grid gap-1.5">
                        <Label className="text-xs">タイトル</Label>
                        <Input value={newContentTitle} onChange={(e) => setNewContentTitle(e.target.value)} placeholder="例: StyleUp UGC 01" />
                      </div>
                      <div className="grid gap-1.5">
                        <Label className="text-xs">形式</Label>
                        <select
                          value={contentFormat}
                          onChange={(e) => setContentFormat(e.target.value)}
                          className="h-10 rounded-md border border-input bg-background px-2 text-sm"
                        >
                          <option value="9:16">9:16</option>
                          <option value="1:1">1:1</option>
                          <option value="16:9">16:9</option>
                          <option value="4:5">4:5</option>
                        </select>
                      </div>
                    </div>
                    <div className="grid gap-1.5">
                      <Label className="text-xs">何を作るか</Label>
                      <Textarea
                        value={productionBrief}
                        onChange={(e) => setProductionBrief(e.target.value)}
                        placeholder="例: StyleUpの縦型UGC広告。冒頭はサロンボード投稿の手作業感、途中で操作デモ、最後にLINE無料投稿CTA。自然なスマホ撮影風で。"
                        className="min-h-28"
                      />
                    </div>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <Button variant="outline" onClick={() => setDraftAssetIds([])}>
                        選択解除
                      </Button>
                      <div className="flex items-center gap-3">
                        <div className="text-xs text-muted-foreground">{draftAssetIds.length}個の素材を選択中</div>
                        <Button onClick={() => void createContent()}>
                          <Plus className="mr-1 h-4 w-4" />
                          制作開始
                        </Button>
                      </div>
                    </div>
                  </div>
                </section>
              ) : null}
              <section className="grid gap-3">
                {contents.length === 0 ? (
                  <div className="rounded-md border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
                    左で素材を追加して選択すると、制作タイプと内容を決められます。
                  </div>
                ) : (
                  contents.map((content) => {
                    const linkedAssets = assets.filter((asset) => content.asset_ids.includes(asset.id));
                    const videoAsset = linkedAssets.find((asset) => asset.kind === 'video');
                    const openContent = () => {
                      setSelectedContent(content);
                      setUrlContentId(content.id);
                    };
                    return (
                      <div
                        key={content.id}
                        role="button"
                        tabIndex={0}
                        onClick={openContent}
                        onKeyDown={(event) => {
                          if (event.key === 'Enter' || event.key === ' ') {
                            event.preventDefault();
                            openContent();
                          }
                        }}
                        className="grid cursor-pointer gap-3 rounded-md border border-border p-3 text-left hover:bg-muted md:grid-cols-[160px_1fr]"
                      >
                        <div className="flex aspect-video items-center justify-center overflow-hidden rounded bg-muted">
                          {videoAsset?.thumbnail_url ? (
                            <img src={videoAsset.thumbnail_url} alt="" className="h-full w-full object-cover" />
                          ) : (
                            <Clapperboard className="h-8 w-8 text-muted-foreground" />
                          )}
                        </div>
                        <div className="min-w-0">
                          <div className="flex items-start gap-2">
                            <div className="min-w-0 flex-1">
                              <div className="truncate font-medium">{content.title}</div>
                              <div className="mt-1 text-sm text-muted-foreground">{content.format} / {content.status}</div>
                            </div>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-8 w-8 shrink-0 text-muted-foreground hover:text-destructive"
                              onClick={(event) => {
                                event.preventDefault();
                                event.stopPropagation();
                                void deleteContent(content);
                              }}
                            >
                              <Trash2 className="h-4 w-4" />
                            </Button>
                          </div>
                          <div className="mt-2 text-xs text-muted-foreground">
                            {linkedAssets.length}個の素材
                          </div>
                        </div>
                      </div>
                    );
                  })
                )}
              </section>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
