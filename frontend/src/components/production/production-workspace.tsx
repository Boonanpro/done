'use client';

import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowLeft, ChevronDown, ChevronRight, Clapperboard, Film, Folder, FolderOpen, Image as ImageIcon, Loader2, Music, Plus, RefreshCw, Sparkles, Trash2, X } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { aiDurationFor, aiModelFor } from '@/lib/ai-video-models';
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
  // 長い録画だけにある、画面で見るための小さい写し。あればこちらを再生する（書き出しは元から）。
  view_url?: string | null;
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
  return asset.view_url || asset.proxy_url || undefined;
}

function sequenceAssetForEditor(asset: ProductionAsset) {
  // Stills are served by the room's media route (the review route only streams video files).
  const stillUrl = asset.kind === 'image' && !asset.proxy_url
    ? `/api/v1/production-assets/media?room_id=${encodeURIComponent(asset.room_id)}&asset_id=${encodeURIComponent(asset.id)}&variant=original`
    : undefined;
  return {
    id: asset.id,
    url: asset.view_url || asset.proxy_url || stillUrl,
    path: asset.view_url || asset.proxy_url || stillUrl ? undefined : assetMediaPath(asset),
    thumbnail_url: asset.thumbnail_url || undefined,
    label: asset.filename || asset.original_uri,
    fps: asset.metadata?.fps as string | number | undefined,
    kind: asset.kind,
  };
}

// Every picture the timeline draws: the content's own videos plus any video/image a clip points
// at (Dan adds generated or imported pictures to the room without adding them to asset_ids).
function sequencePictureAssets(content: ProductionContent, assets: ProductionAsset[]) {
  const sequence = (content.timeline?.sequence || {}) as { tracks?: Array<{ clips?: Array<{ asset_id?: string }> }> };
  const used = new Set(content.asset_ids);
  for (const track of sequence.tracks || []) for (const clip of track.clips || []) if (clip.asset_id) used.add(clip.asset_id);
  return assets.filter((asset) => (asset.kind === 'video' || asset.kind === 'image') && used.has(asset.id));
}

export function ProductionWorkspace({
  roomId,
  onContentChange,
}: {
  roomId: string;
  /** ライブラリの真ん中に大きく置く「ダンと制作」の会話（制作の窓だけが渡す） */
  /** 開いている作品が替わった（null = ライブラリ）。エディターの窓の「ダンと制作」が部屋を替える */
  onContentChange?: (contentId: string | null) => void;
}) {
  const [assets, setAssets] = useState<ProductionAsset[]>([]);
  const [contents, setContents] = useState<ProductionContent[]>([]);
  const [selectedContent, setSelectedContent] = useState<ProductionContent | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  // If we deep-linked into a content (refresh while editing), show a loading state until the
  // content loads — NOT the project/material list, which used to flash for a moment first.
  // Starts true so the SERVER renders the loader (not the list) — the server can't read the URL,
  // so a window-based initializer would SSR the list and flash it before the client corrects.
  const [booting, setBooting] = useState(true);
  const [jobs, setJobs] = useState<ProductionJob[]>([]);
  const [jobEvents, setJobEvents] = useState<ProductionJobEvent[]>([]);
  const [activeVideoAssetId, setActiveVideoAssetId] = useState<string | null>(null);
  const [assetsOpen, setAssetsOpen] = useState(false); // 使用素材（プレビュー左上）も折りたたみ既定

  const hasProcessing = useMemo(() => assets.some((a) => a.status === 'processing'), [assets]);
  const selectedContentAssets = useMemo(
    () => (selectedContent ? assets.filter((asset) => selectedContent.asset_ids.includes(asset.id)) : []),
    [assets, selectedContent]
  );
  const selectedSourceAssets = useMemo(
    () => selectedContentAssets.filter((asset) => asset.source_type !== 'generated'),
    [selectedContentAssets]
  );
  const [openFolders, setOpenFolders] = useState<Record<string, boolean>>({});
  const [previewAsset, setPreviewAsset] = useState<ProductionAsset | null>(null);
  const [creating, setCreating] = useState(false);
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

  // Job ids we've already reacted to as terminal (done/failed). Without this, loadJobs would
  // call loadAll on EVERY poll as long as any terminal job exists (a finished build is always
  // 'done'), and loadAll churns selectedContent's identity -> loadJobs re-fires -> loadAll ...
  // an infinite fetch loop (~1/s) that re-parses the 324-clip contents JSON and OOMs the renderer.
  const reactedTerminalJobsRef = useRef<Set<string>>(new Set());

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
      setSelectedContent((current) => {
        const targetId = current?.id || urlContentId;
        const found = targetId
          ? nextContents.find((content: ProductionContent) => content.id === targetId) || null
          : null;
        // Keep the existing object reference when nothing actually changed, so selectedContent's
        // identity stays stable and dependent effects (loadJobs) don't re-fire on every refresh.
        if (current && found && found.id === current.id && found.updated_at === current.updated_at) {
          return current;
        }
        return found;
      });
    } catch (error) {
      toast.error('Failed to load production workspace', { description: String(error).slice(0, 160) });
    } finally {
      setIsLoading(false);
      setBooting(false);
    }
  }, [roomId]);

  useEffect(() => {
    // No deep-linked content -> drop the loader immediately so the list shows without waiting.
    if (!new URLSearchParams(window.location.search).get('content_id')) setBooting(false);
  }, []);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  useEffect(() => {
    if (!hasProcessing) return;
    const timer = window.setInterval(() => void loadAll(), 4000);
    return () => window.clearInterval(timer);
  }, [hasProcessing, loadAll]);

  const selectedContentId = selectedContent?.id ?? null;
  useEffect(() => {
    if (!booting) onContentChange?.(selectedContentId);
  }, [booting, selectedContentId, onContentChange]);

  // ライブラリを見ている間、素材と作品が変わったら（ダンが「ダンと制作」から足した時など）すぐ読み直す。
  // 一覧そのもの（大きい部屋で1MB超）は変わった時だけ取り、毎回は数バイトの印だけを見る。
  const libraryStampRef = useRef('');
  useEffect(() => {
    if (!roomId || selectedContentId) return;
    let stopped = false;
    const tick = async () => {
      if (document.hidden) return;
      try {
        const res = await fetch(`/api/v1/production-assets/library-stamp?room_id=${encodeURIComponent(roomId)}`, { credentials: 'include' });
        if (!res.ok || stopped) return;
        const stamp = JSON.stringify(await res.json());
        if (libraryStampRef.current && libraryStampRef.current !== stamp) void loadAll();
        libraryStampRef.current = stamp;
      } catch {
        /* 次の回で読み直す */
      }
    };
    void tick();
    const timer = window.setInterval(() => void tick(), 3000);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [roomId, selectedContentId, loadAll]);

  // ライブラリを見ている時は、ダンに「今はライブラリ」と知らせる（作品の画面ではエディターが再生位置ごと知らせる）
  useEffect(() => {
    if (!roomId || booting || selectedContentId || !onContentChange) return;
    void fetch('/api/v1/production-assets/editor-state', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ room_id: roomId, screen: 'library' }),
    }).catch(() => {});
  }, [roomId, booting, selectedContentId, onContentChange]);

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
      // Only refresh assets/contents when a job has JUST transitioned to terminal — not while a
      // terminal job merely exists (that re-triggers loadAll forever; see reactedTerminalJobsRef).
      const newlyTerminal = nextJobs.filter(
        (job) => (job.status === 'done' || job.status === 'failed') && !reactedTerminalJobsRef.current.has(job.id)
      );
      for (const job of nextJobs) {
        if (job.status === 'done' || job.status === 'failed') reactedTerminalJobsRef.current.add(job.id);
      }
      if (newlyTerminal.length > 0) {
        void loadAll();
      }
    } catch (error) {
      // Polled every 2s; a transient failure (e.g. the sandbox restarting on deploy)
      // self-heals on the next tick, so don't spam a toast for it.
      console.warn('loadJobs failed (will retry):', String(error).slice(0, 160));
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

  const deleteAsset = async (asset: ProductionAsset) => {
    if (!window.confirm(`素材「${asset.filename || asset.original_uri}」を削除しますか？
元動画・プロキシ・サムネイルを完全に削除します（タイムライン削除とは別です）。`)) return;
    const url = (force: boolean) => `/api/v1/production-assets/${asset.id}?room_id=${encodeURIComponent(roomId)}${force ? '&force=true' : ''}`;
    try {
      let res = await fetch(url(false), { method: 'DELETE', credentials: 'include' });
      if (res.status === 409) {
        const body = await res.json().catch(() => null);
        const titles = ((body?.detail?.contents as Array<{ title: string }>) || []).map((c) => c.title).join('、');
        if (!window.confirm(`この素材は「${titles}」で使用中です。
削除すると該当プロジェクトのその部分が表示されなくなります。
それでも削除しますか？`)) return;
        res = await fetch(url(true), { method: 'DELETE', credentials: 'include' });
      }
      if (!res.ok) throw new Error(await res.text());
      toast.success('素材を削除しました');
      await loadAll();
    } catch (error) {
      toast.error('素材の削除に失敗', { description: String(error).slice(0, 180) });
    }
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

  const currentTimeline = (selectedContent?.timeline || {}) as { annotations?: Array<{ id?: string; intent?: string; start?: number; end?: number; note?: string }> };
  const pendingAnnotations = Array.isArray(currentTimeline.annotations) ? currentTimeline.annotations : [];

  // 範囲の「ダンに指示」をダンに渡す（タイムラインの指示クリップごとの実行ボタンから）。
  const requestDanEdit = async (revision?: string, executedAnns?: Array<{ id?: string; intent?: string; start?: number; end?: number; note?: string }>): Promise<boolean> => {
    if (!selectedContent) return false;
    const selectedAssets = selectedSourceAssets;
    if (selectedAssets.length === 0) {
      toast.error('素材がありません');
      return false;
    }
    const timeline = selectedContent.timeline || {};
    const baseBrief = typeof timeline.brief === 'string' ? timeline.brief : '';
    const trimmedRevision = (revision || '').trim();
    const hasSequence = !!(timeline as { sequence?: unknown }).sequence;
    // Stage 3: partial, non-destructive edit. Keep the CURRENT sequence and pass the
    // instruction text + creative instruction-clip regions; the backend patches only the
    // in-scope clips and preserves the rest. (Fallback to a full dan_edit only if there is
    // no sequence yet — i.e. nothing to patch.)
    const instruction = {
      mode: hasSequence ? 'dan_revise' : 'dan_edit',
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
      brief: baseBrief,
      revision_text: trimmedRevision,
      revision_regions: (executedAnns || []).map((a) => ({
        intent: a.intent, start: a.start, end: a.end, note: a.note,
      })),
      workflow_preset: typeof timeline.workflow_preset === 'string' ? timeline.workflow_preset : 'video_ugc',
      timeline: {
        ...timeline,
        format: selectedContent.format,
        source_asset_ids: selectedAssets.map((asset) => asset.id),
        // Keep the existing sequence so the edit is applied ON it (non-destructive).
        // On success the backend REPLACES timeline with this — so keep ALL current
        // annotations (blur/cut included; sending only creative ones used to drop them),
        // minus the instruction clips being executed (consumed = auto-removed).
        annotations: (() => {
          const executedIds = new Set((executedAnns || []).map((a) => a.id).filter(Boolean));
          return pendingAnnotations.filter((a) => !a.id || !executedIds.has(a.id));
        })(),
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
      toast.success('Danに修正を依頼しました（指示した箇所だけ直します）');
      await loadJobs();
      window.setTimeout(() => {
        void loadJobs();
        void loadAll();
      }, 1200);
      return true;
    } catch (error) {
      toast.error('Danへの制作依頼に失敗しました', { description: String(error).slice(0, 180) });
      return false;
    }
  };

  // Per-clip 実行: run Dan scoped to a SINGLE instruction clip (生成/ダンに指示) so the result is
  // visible without re-editing the whole content. Reuses the non-destructive dan_revise path.
  // Returns whether the job was accepted (the editor removes the consumed clip only then).
  const executeInstructionClip = async (ann: ReviewAnnotation): Promise<boolean> => {
    return requestDanEdit(ann.note || '', [{ id: ann.id, intent: ann.intent, start: ann.start, end: ann.end ?? undefined, note: ann.note ?? undefined }]);
  };

  // 「生成」ペン注釈は Dan の解釈を挟まず、選択モデルへそのまま渡す。
  // 完了ジョブが素材登録・映像レーン配置まで行うので、以後は普通のクリップとして手で調整できる。
  const generateFromAnnotation = async (ann: ReviewAnnotation): Promise<boolean> => {
    if (!selectedContent) return false;
    const prompt = (ann.note || '').trim();
    if (!prompt) {
      toast.error('生成したい映像の指示を入力してください');
      return false;
    }
    const span = Math.max(0.1, (ann.end ?? ann.start + 5) - ann.start);
    const model = aiModelFor(span, (ann.data as { model?: string } | undefined)?.model);
    const instruction = {
      mode: 'higgsfield_generate',
      prompt,
      model: model.id,
      aspect_ratio: selectedContent.format === '4:5' ? '9:16' : selectedContent.format,
      duration: aiDurationFor(model, span),
      annotation: ann,
    };
    try {
      const res = await fetch('/api/v1/production-assets/jobs', {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ room_id: roomId, content_id: selectedContent.id, instruction }),
      });
      if (!res.ok) throw new Error(await res.text());
      toast.success(`${model.label}で映像を作り始めました`);
      await loadJobs();
      return true;
    } catch (error) {
      toast.error('映像を作り始められませんでした', { description: String(error).slice(0, 180) });
      return false;
    }
  };

  const saveContentTimeline = async (timeline: SessionPayload) => {
    if (!selectedContent) return;
    // Merge into the existing timeline so format / source_asset_ids / screen_blur (Dan-driven
    // blur) aren't dropped when only the sequence or annotations change.
    const merged = { ...(selectedContent.timeline as Record<string, unknown>), ...timeline };
    const res = await fetch(
      `/api/v1/production-assets/contents/${selectedContent.id}?room_id=${encodeURIComponent(roomId)}`,
      {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ timeline: merged }),
      }
    );
    if (!res.ok) throw new Error(await res.text());
    const updated = await res.json();
    setSelectedContent(updated);
    setContents((prev) => prev.map((content) => (content.id === updated.id ? updated : content)));
  };


  // Caption audio-sync: ask the backend for per-word timings under each caption (cached Whisper,
  // else runs it) so karaoke/typewriter follow the real voice. Returns {captionId: words[]} which
  // the editor merges into its own clips (so the user's just-picked design isn't clobbered).
  const syncCaptionAudio = async (
    captionIds: string[],
  ): Promise<Record<string, { text: string; start: number; end: number }[]>> => {
    if (!selectedContent) return {};
    try {
      const res = await fetch(
        `/api/v1/production-assets/contents/${selectedContent.id}/caption-sync`,
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ room_id: roomId, caption_ids: captionIds }),
        },
      );
      if (!res.ok) {
        toast.error('音声同期に失敗しました', { description: (await res.text()).slice(0, 160) });
        return {};
      }
      const body = await res.json();
      const map = (body.words_by_caption || {}) as Record<string, { text: string; start: number; end: number }[]>;
      const n = Object.values(map).filter((w) => w && w.length).length;
      toast[n ? 'success' : 'message'](n ? `音声に同期しました（${n}字幕）` : '同期できる音声が見つかりませんでした（この字幕の下に解析可能な発話がありません）');
      return map;
    } catch (error) {
      toast.error('音声同期に失敗しました', { description: String(error).slice(0, 160) });
      return {};
    }
  };

  // 追従ぼかし: OCR-track the TEXT in the drawn box. anchor = time the box was drawn; scan window
  // = the whole clip. Returns the path + the visible time range (which DEFINES the clip length).
  const trackBlurRegion = async (
    box: { x: number; y: number; width: number; height: number },
    anchor: number,
    scanStart: number,
    scanEnd: number,
  ): Promise<{ boxes: Record<string, number[]>; text?: string; t_start?: number | null; t_end?: number | null; found?: boolean }> => {
    if (!selectedContent) return { boxes: {} };
    try {
      const res = await fetch(
        `/api/v1/production-assets/contents/${selectedContent.id}/blur/track`,
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ room_id: roomId, x: box.x, y: box.y, width: box.width, height: box.height, anchor, start: scanStart, end: scanEnd }),
        },
      );
      if (!res.ok) {
        toast.error('追跡解析に失敗しました', { description: (await res.text()).slice(0, 160) });
        return { boxes: {} };
      }
      const body = await res.json();
      const boxes = (body.boxes || {}) as Record<string, number[]>;
      if (body.found && body.text) {
        const s = typeof body.t_start === 'number' ? body.t_start.toFixed(1) : '?';
        const e = typeof body.t_end === 'number' ? body.t_end.toFixed(1) : '?';
        toast.success(`「${body.text}」を追跡しました（${s}〜${e}秒）`);
      } else {
        toast.message('文字が見つかりませんでした（枠を文字に合わせてください／任意物体の追従は近日対応）');
      }
      return { boxes, text: body.text, t_start: body.t_start, t_end: body.t_end, found: !!body.found };
    } catch (error) {
      toast.error('追跡解析に失敗しました', { description: String(error).slice(0, 160) });
      return { boxes: {} };
    }
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

  // 新規作成した作品は映像が無くても空のタイムラインで開き、ダンが目の前で組み立てていく
  const hasTimeline = !!selectedContent && !!(selectedContent.timeline as { sequence?: unknown } | undefined)?.sequence;
  if (selectedContent && (primaryVideo || hasTimeline)) {
    const mediaUrl = primaryVideo ? assetMediaUrl(primaryVideo) : undefined;
    return (
      <VideoReviewEditor
        key={primaryVideo ? primaryVideo.id : `content-${selectedContent.id}`}
        embedded
        roomId={roomId}
        contentId={selectedContent.id}
        title={selectedContent.title}
        onExternalEdit={() => void loadAll()}
        initialPath={mediaUrl || !primaryVideo ? undefined : assetMediaPath(primaryVideo)}
        initialUrl={mediaUrl}
        initialThumbnailUrl={primaryVideo?.thumbnail_url || undefined}
        initialFps={primaryVideo?.metadata?.fps as string | number | undefined}
        initialAnnotations={(selectedContent.timeline?.annotations as ReviewAnnotation[] | undefined) || undefined}
        initialSequence={(selectedContent.timeline?.sequence as EditSequence | undefined) || undefined}
        sequenceAssets={sequencePictureAssets(selectedContent, assets).map(sequenceAssetForEditor)}
        previewTopLeft={
          assetsOpen ? (
            <div className="w-72 rounded-md border border-border bg-background/95 shadow-lg backdrop-blur">
              <button
                type="button"
                onClick={() => setAssetsOpen(false)}
                className="flex w-full items-center justify-between px-3 py-2 text-sm font-medium text-foreground"
              >
                <span>使用素材（{selectedSourceAssets.length}）</span>
                <span className="text-xs text-muted-foreground">▲</span>
              </button>
              <div className="max-h-[50vh] overflow-y-auto px-2 pb-2">
                <div className="grid grid-cols-2 gap-2">
                  {selectedSourceAssets.map((asset) => (
                    <div
                      key={asset.id}
                      draggable={asset.kind === 'video'}
                      onDragStart={(event) => {
                        if (asset.kind !== 'video') return;
                        // payload shape matches the editor's ASSET_DND_TYPE consumer
                        const payload = {
                          id: asset.id,
                          kind: asset.kind,
                          duration: asset.metadata?.duration,
                          label: asset.filename || asset.original_uri,
                        };
                        event.dataTransfer.setData('application/x-dan-asset', JSON.stringify(payload));
                        event.dataTransfer.effectAllowed = 'copy';
                        // dataTransfer.getData is unreadable during dragover, so expose the asset
                        // (for the timeline's live drop-preview ghost) via window until dragend.
                        (window as unknown as { __danDragAsset?: typeof payload }).__danDragAsset = payload;
                      }}
                      onDragEnd={() => {
                        delete (window as unknown as { __danDragAsset?: unknown }).__danDragAsset;
                      }}
                      title={asset.kind === 'video' ? 'ドラッグでタイムラインに追加' : undefined}
                      className={`overflow-hidden rounded border border-border bg-muted/30 ${asset.kind === 'video' ? 'cursor-grab active:cursor-grabbing' : ''}`}
                    >
                      <div className="flex aspect-video items-center justify-center bg-muted">
                        {asset.thumbnail_url ? (
                          <img src={asset.thumbnail_url} alt="" className="pointer-events-none h-full w-full object-cover" />
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
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setAssetsOpen(true)}
              className="flex items-center gap-1.5 rounded-md border border-border bg-background/90 px-3 py-1.5 text-xs font-medium text-foreground shadow backdrop-blur hover:bg-muted"
            >
              <Film className="h-3.5 w-3.5" />
              使用素材（{selectedSourceAssets.length}）
              <span className="text-muted-foreground">▼</span>
            </button>
          )
        }
        sidePanelTop={
          <div className="mb-3 space-y-3">
            {latestJob && (latestJob.status === 'queued' || latestJob.status === 'running') ? (
              <div className="rounded-md border border-border p-3">
                <div className="mb-2 flex items-center gap-2 text-sm font-medium">
                  <Loader2 className="h-4 w-4 animate-spin text-primary" />
                  {latestJob.instruction?.mode === 'higgsfield_generate' ? 'Higgsfieldが動画を生成中…' : 'Danが制作中…'}
                </div>
                {jobEvents.length > 0 ? (
                  <div className="max-h-40 space-y-1 overflow-y-auto rounded border border-border bg-muted/30 p-2 text-xs">
                    {jobEvents.slice(-8).map((event, index) => (
                      <div key={`${event.created_at || index}-${index}`} className="text-muted-foreground">
                        <span className="mr-1 text-[10px] uppercase">{event.type || 'event'}</span>
                        <span>{event.name ? `${event.name}: ` : ''}{event.text || ''}</span>
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : latestJob?.status === 'failed' ? (
              <div className="rounded-md border border-destructive/40 p-3 text-xs text-destructive">
                前回の制作が失敗しました。{latestJob.error || ''}
              </div>
            ) : null}
          </div>
        }
        onBack={() => {
          setSelectedContent(null);
          setUrlContentId(null);
        }}
        onSaveTimeline={saveContentTimeline}
        onSyncCaptionAudio={syncCaptionAudio}
        onTrackBlur={trackBlurRegion}
        onExecuteClip={executeInstructionClip}
        onGenerateClip={generateFromAnnotation}
        onExecute={createProductionJob}
      />
    );
  }

  // Deep-linked into a content (refresh while editing): show a loader instead of flashing the
  // project/material list while the content loads.
  if (booting) {
    return (
      <div className="flex h-full min-h-0 items-center justify-center bg-background text-muted-foreground">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        タイムラインを開いています…
      </div>
    );
  }

  // 映像がまだ無い作品（ダンが作り始めたところ・AIで作っている途中）を開いた時
  if (selectedContent) {
    const generating = latestJob && (latestJob.status === 'queued' || latestJob.status === 'running');
    return (
      <div className="flex h-full min-h-0 flex-col bg-background">
        <header className="flex shrink-0 items-center gap-3 border-b border-border px-4 py-2.5">
          <Button variant="ghost" size="sm" onClick={() => { setSelectedContent(null); setUrlContentId(null); }} title="ライブラリへ戻る">
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <h1 className="min-w-0 flex-1 truncate text-sm font-semibold">{selectedContent.title}</h1>
        </header>
        <div className="flex flex-1 items-center justify-center p-6">
          <div className="max-w-md text-center text-sm text-muted-foreground">
            {generating ? (
              <div className="space-y-3">
                <div className="flex items-center justify-center gap-2 font-medium text-foreground"><Loader2 className="h-4 w-4 animate-spin text-primary" />映像を作っています…</div>
                {jobEvents.length > 0 ? <div className="space-y-1 rounded border bg-muted/30 p-2 text-left text-xs">{jobEvents.slice(-4).map((event, index) => <div key={`${event.created_at || index}-${index}`}>{event.text || ''}</div>)}</div> : null}
                <p>できたらこの画面がタイムラインに替わります。</p>
              </div>
            ) : latestJob?.status === 'failed' ? (
              <div className="text-destructive">映像を作れませんでした。{latestJob.error || ''}</div>
            ) : (
              'この作品にはまだ映像がありません。右の「ダンと制作」で、どんな動画にしたいかを話してください。'
            )}
          </div>
        </div>
      </div>
    );
  }

  const folders = ASSET_FOLDERS
    .map((folder) => ({ ...folder, items: assets.filter(folder.test) }))
    .filter((folder) => folder.items.length > 0);
  const openContent = (content: ProductionContent) => {
    setSelectedContent(content);
    setUrlContentId(content.id);
  };
  // 「新規作成」: 空のタイムラインの作品を作ってすぐ開く。右の「ダンと制作」で話しながら組み立てる
  // （2026-11-12 本人「新規作成ボタンを押したらタイムラインを開いて、そこで会話する。喋りながら動画が出来ていく」）。
  const createContent = async () => {
    if (creating) return;
    setCreating(true);
    try {
      const now = new Date();
      const res = await fetch('/api/v1/production-assets/contents', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          room_id: roomId,
          title: `新しい作品 ${now.getMonth() + 1}/${now.getDate()} ${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`,
          format: '16:9',
          timeline: { sequence: { format: '16:9', frame_rate: 30, duration: 0, tracks: [] } },
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      const created = (await res.json()) as ProductionContent;
      setContents((prev) => [...prev, created]);
      openContent(created);
    } catch (error) {
      toast.error('作品を作れませんでした', { description: String(error).slice(0, 160) });
    } finally {
      setCreating(false);
    }
  };
  const sortedContents = [...contents].sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime());

  // ライブラリ: 左に作品と素材のフォルダ、真ん中に大きく「ダンと制作」（2026-11-12 本人「左のサイドバーに
  // プロジェクト一覧と素材フォルダ、真ん中にチャットをどでかく、それだけでいい」）。素材を足すのも作品を作るのも会話で頼む。
  return (
    <div className="flex h-full min-h-0 bg-background">
      <aside className="flex w-[280px] shrink-0 flex-col border-r border-border bg-muted/20" aria-label="作品と素材">
        <div className="flex shrink-0 items-center gap-2 px-4 py-3">
          <Clapperboard className="h-4 w-4 text-primary" />
          <span className="flex-1 text-sm font-semibold">ダン 制作</span>
          <button type="button" onClick={() => void loadAll()} title="読み直す" className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground">
            <RefreshCw className={`h-3.5 w-3.5 ${isLoading ? 'animate-spin' : ''}`} />
          </button>
        </div>
        <div className="shrink-0 px-3 pb-2">
          <Button className="w-full" size="sm" onClick={() => void createContent()} disabled={creating}>
            {creating ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Plus className="mr-1 h-4 w-4" />}
            新規作成
          </Button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto pb-4">
          <div className="px-4 pb-1 pt-2 text-[11px] font-semibold text-muted-foreground">作品</div>
          {sortedContents.length === 0 ? (
            <p className="px-4 py-2 text-xs text-muted-foreground">まだありません。「新規作成」から始めます。</p>
          ) : (
            <ul className="px-2" aria-label="作品">
              {sortedContents.map((content) => {
                const cover = assets.find((asset) => content.asset_ids.includes(asset.id) && asset.kind === 'video')
                  || assets.find((asset) => content.asset_ids.includes(asset.id) && asset.kind === 'image');
                return (
                  <li key={content.id} className="group relative">
                    <button
                      type="button"
                      onClick={() => openContent(content)}
                      className="flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left hover:bg-muted"
                    >
                      <span className="flex h-9 w-14 shrink-0 items-center justify-center overflow-hidden rounded bg-muted">
                        {cover ? <AssetThumb asset={cover} fallback={<Film className="h-4 w-4 text-muted-foreground" />} /> : <Film className="h-4 w-4 text-muted-foreground" />}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[13px] font-medium">{content.title}</span>
                        <span className="block text-[11px] text-muted-foreground">
                          {content.format}・{new Date(content.updated_at).toLocaleDateString('ja-JP', { month: 'numeric', day: 'numeric' })}
                          {content.status === 'running' ? '・作成中' : ''}
                        </span>
                      </span>
                    </button>
                    <button
                      type="button"
                      title="この作品を消す"
                      onClick={() => {
                        if (window.confirm(`作品「${content.title}」を消しますか？`)) void deleteContent(content);
                      }}
                      className="absolute right-1.5 top-1/2 hidden -translate-y-1/2 rounded p-1 text-muted-foreground hover:bg-background hover:text-destructive group-hover:block"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </li>
                );
              })}
            </ul>
          )}

          <div className="px-4 pb-1 pt-4 text-[11px] font-semibold text-muted-foreground">素材</div>
          {folders.length === 0 ? (
            <p className="px-4 py-2 text-xs text-muted-foreground">まだありません。作品の画面の「ダンと制作」に貼るか、集めてと頼むと入ります。</p>
          ) : (
            <ul className="px-2" aria-label="素材のフォルダ">
              {folders.map((folder) => {
                const open = !!openFolders[folder.key];
                return (
                  <li key={folder.key}>
                    <button
                      type="button"
                      onClick={() => setOpenFolders((current) => ({ ...current, [folder.key]: !open }))}
                      className="flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-[13px] hover:bg-muted"
                    >
                      {open ? <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" /> : <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />}
                      {open ? <FolderOpen className="h-4 w-4 text-amber-500" /> : <Folder className="h-4 w-4 text-amber-500" />}
                      <span className="flex-1">{folder.label}</span>
                      <span className="text-[11px] text-muted-foreground">{folder.items.length}</span>
                    </button>
                    {open ? (
                      <div className="grid grid-cols-2 gap-1.5 px-2 pb-2 pt-1">
                        {folder.items.map((asset) => (
                          <button
                            key={asset.id}
                            type="button"
                            onClick={() => setPreviewAsset(asset)}
                            title={asset.filename || asset.original_uri}
                            className="overflow-hidden rounded border border-border bg-background text-left hover:border-primary"
                          >
                            <span className="relative flex aspect-video items-center justify-center bg-muted">
                              {asset.status === 'processing' ? (
                                <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                              ) : (
                                <AssetThumb asset={asset} fallback={<folder.icon className="h-4 w-4 text-muted-foreground" />} />
                              )}
                              {asset.kind === 'video' && asset.metadata?.duration ? (
                                <span className="absolute bottom-0.5 right-0.5 rounded bg-black/70 px-1 text-[9px] text-white">{formatDuration(asset.metadata.duration)}</span>
                              ) : null}
                            </span>
                            <span className="block truncate px-1 py-0.5 text-[10px]">{asset.filename || asset.original_uri}</span>
                          </button>
                        ))}
                      </div>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </aside>

      <main className="min-h-0 min-w-0 flex-1 overflow-y-auto p-6" aria-label="作品の一覧">
        <div className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-4">
          <button
            type="button"
            onClick={() => void createContent()}
            disabled={creating}
            className="flex aspect-video flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-primary/50 text-primary hover:bg-primary/5"
          >
            {creating ? <Loader2 className="h-7 w-7 animate-spin" /> : <Plus className="h-7 w-7" />}
            <span className="text-sm font-semibold">新規作成</span>
            <span className="text-[11px] text-muted-foreground">タイムラインを開いて、ダンと話しながら作ります</span>
          </button>
          {sortedContents.map((content) => {
            const cover = assets.find((asset) => content.asset_ids.includes(asset.id) && asset.kind === 'video')
              || assets.find((asset) => content.asset_ids.includes(asset.id) && asset.kind === 'image');
            return (
              <button
                key={content.id}
                type="button"
                onClick={() => openContent(content)}
                className="overflow-hidden rounded-lg border border-border text-left hover:border-primary"
              >
                <span className="flex aspect-video items-center justify-center overflow-hidden bg-muted">
                  {cover ? <AssetThumb asset={cover} fallback={<Film className="h-6 w-6 text-muted-foreground" />} /> : <Film className="h-6 w-6 text-muted-foreground" />}
                </span>
                <span className="block truncate px-2.5 pt-2 text-[13px] font-medium">{content.title}</span>
                <span className="block px-2.5 pb-2 text-[11px] text-muted-foreground">
                  {content.format}・{new Date(content.updated_at).toLocaleDateString('ja-JP', { month: 'numeric', day: 'numeric' })}
                </span>
              </button>
            );
          })}
        </div>
      </main>

      {previewAsset ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-8" onClick={() => setPreviewAsset(null)}>
          <div className="flex max-h-full w-full max-w-4xl flex-col overflow-hidden rounded-lg bg-background shadow-xl" onClick={(event) => event.stopPropagation()}>
            <div className="flex items-center gap-2 border-b border-border px-4 py-2">
              <span className="min-w-0 flex-1 truncate text-sm font-medium">{previewAsset.filename || previewAsset.original_uri}</span>
              <span className="text-xs text-muted-foreground">
                {formatDuration(previewAsset.metadata?.duration)}
                {previewAsset.metadata?.width && previewAsset.metadata?.height ? `・${String(previewAsset.metadata.width)}×${String(previewAsset.metadata.height)}` : ''}
              </span>
              <button
                type="button"
                title="この素材を消す"
                onClick={() => { const asset = previewAsset; setPreviewAsset(null); void deleteAsset(asset); }}
                className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-destructive"
              >
                <Trash2 className="h-4 w-4" />
              </button>
              <button type="button" title="閉じる" onClick={() => setPreviewAsset(null)} className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="flex min-h-0 flex-1 items-center justify-center bg-black">
              {previewAsset.kind === 'video' ? (
                <video src={assetPreviewUrl(previewAsset)} controls autoPlay className="max-h-[75vh] w-full" />
              ) : previewAsset.kind === 'image' ? (
                <img src={assetPreviewUrl(previewAsset)} alt="" className="max-h-[75vh] max-w-full object-contain" />
              ) : previewAsset.kind === 'audio' ? (
                <audio src={assetPreviewUrl(previewAsset)} controls autoPlay className="m-10 w-full max-w-md" />
              ) : (
                <div className="p-10 text-sm text-white/70">この素材は画面で開けません。</div>
              )}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

// ライブラリの素材のフォルダ（種類ごと）。AIで作った素材は別のフォルダにまとめる。
const ASSET_FOLDERS: Array<{ key: string; label: string; icon: typeof Film; test: (asset: ProductionAsset) => boolean }> = [
  { key: 'video', label: '動画', icon: Film, test: (a) => a.kind === 'video' && a.source_type !== 'generated' },
  { key: 'image', label: '画像', icon: ImageIcon, test: (a) => a.kind === 'image' && a.source_type !== 'generated' },
  { key: 'audio', label: '音声', icon: Music, test: (a) => a.kind === 'audio' && a.source_type !== 'generated' },
  { key: 'file', label: 'そのほか', icon: Folder, test: (a) => a.kind === 'file' && a.source_type !== 'generated' },
  { key: 'generated', label: 'AIで作った素材', icon: Sparkles, test: (a) => a.source_type === 'generated' },
];

function assetPreviewUrl(asset: ProductionAsset): string {
  if (asset.kind === 'video' && (asset.view_url || asset.proxy_url)) return asset.view_url || asset.proxy_url || '';
  return `/api/v1/production-assets/media?room_id=${encodeURIComponent(asset.room_id)}&asset_id=${encodeURIComponent(asset.id)}&variant=original`;
}

// 素材の小さな絵。サムネイルが無い動画は最初の方の1コマを、画像はその画像を（見えた時だけ）読む。
function AssetThumb({ asset, fallback }: { asset: ProductionAsset; fallback: ReactNode }) {
  if (asset.thumbnail_url) return <img src={asset.thumbnail_url} alt="" loading="lazy" className="h-full w-full object-cover" />;
  if (asset.kind === 'image') return <img src={assetPreviewUrl(asset)} alt="" loading="lazy" className="h-full w-full object-cover" />;
  if (asset.kind === 'video') {
    return <video src={`${assetPreviewUrl(asset)}#t=1`} preload="metadata" muted playsInline className="pointer-events-none h-full w-full object-cover" />;
  }
  return <>{fallback}</>;
}
