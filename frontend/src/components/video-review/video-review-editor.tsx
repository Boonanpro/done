'use client';

import { type CSSProperties, type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  CAPTION_DESIGN_PRESETS,
  CAPTION_FONTS,
  CAPTION_FONT_FACE_CSS,
  type CaptionAnimation,
  type CaptionDesign,
  type CaptionFontId,
} from './caption-design';
import {
  ArrowLeft,
  Check,
  Eraser,
  MessageSquare,
  MousePointer2,
  Pause,
  Pencil,
  Play,
  Save,
  Scissors,
  Square,
  Trash2,
  Redo2,
  Undo2,
} from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { TimelinePreview } from './timeline-preview';

type Tool = 'select' | 'rect' | 'freehand' | 'marker';
type Intent = 'blur' | 'cut_keep' | 'cut_remove' | 'caption' | 'replace' | 'generate' | 'motion' | 'audio' | 'comment';

type Point = { x: number; y: number };

export type ReviewAnnotation = {
  id: string;
  kind: 'rect' | 'freehand' | 'marker' | 'note';
  intent: Intent | string;
  label?: string | null;
  note?: string | null;
  start: number;
  end?: number | null;
  data: Record<string, unknown>;
  created_at?: string | null;
};

export type SessionPayload = {
  id?: string;
  video_path?: string | null;
  video_url?: string | null;
  duration?: number | null;
  annotations: ReviewAnnotation[];
  sequence?: EditSequence | null;
  updated_at?: string | null;
};

export type SequenceClip = {
  id: string;
  asset_id?: string | null;
  label?: string | null;
  text?: string | null;
  source_start: number;
  source_end: number;
  source_duration?: number | null;
  timeline_start: number;
  timeline_end: number;
  track?: string | null;
  composition?: 'fullscreen' | 'pip' | 'background' | 'overlay' | string | null;
  position?: { x: number; y: number; width: number; height: number } | null;
  role?: 'dialogue' | 'music' | 'sfx' | string | null;
  layer?: number | null;
  type?: string | null;
  link_id?: string | null;   // A/V link: clips sharing a link_id move/trim together
  muted?: boolean | null;
  locked?: boolean | null;
  style?: CaptionStyle | null;  // per-caption styling (color/size/position/outline)
  words?: { text: string; start: number; end: number }[] | null;  // per-word timings for karaoke/typewriter sync
  // Non-destructive source placement inside the clip's box: zoom + pan. null/absent =
  // today's cover look. scale<1 reveals the full source frame (no pixels cropped).
  transform?: { scale: number; x: number; y: number } | null;
  // Trim the source frame's edges (0-1 fraction of the source). Applied before placement.
  crop?: { top: number; bottom: number; left: number; right: number } | null;
  // Per-clip audio volume multiplier (1 = unchanged).
  volume?: number | null;
};

// Per-caption style = the rich CaptionDesign (font / color / gradient / outline / box / shadow /
// motion) shared with the renderer, plus a few legacy fields the old canvas used (bold / x / y).
// The HTML caption renderer ignores the legacy fields; they remain only for back-compat.
export type CaptionStyle = CaptionDesign & {
  bold?: boolean;
  x?: number;
  y?: number;
};

// True when the caption's current design matches a preset (for highlighting the active chip).
function captionMatchesPreset(current: CaptionStyle | null | undefined, design: CaptionDesign): boolean {
  const s = (current || {}) as CaptionDesign;
  const keys: (keyof CaptionDesign)[] = ['font', 'color', 'outlineColor', 'outlineWidth', 'animation'];
  return keys.every((k) => JSON.stringify(s[k] ?? null) === JSON.stringify(design[k] ?? null));
}

const CAPTION_ANIM_OPTIONS: { value: CaptionAnimation; label: string }[] = [
  { value: 'none', label: 'なし' },
  { value: 'pop', label: 'ポップ' },
  { value: 'fade', label: 'フェード' },
  { value: 'slide', label: 'スライド' },
  { value: 'typewriter', label: 'タイプ' },
  { value: 'karaoke', label: 'カラオケ' },
];

type LaneItem = {
  key: string;
  kind: 'clip' | 'annotation';
  itemType: string;
  start: number;
  end: number;
  clip?: SequenceClip;
  annotation?: ReviewAnnotation;
};

type TimelineLane = {
  key: string;
  label: string;
  zone: 'visual' | 'audio';
  layer: number;
  height: number;
  items: LaneItem[];
};

export type EditSequence = {
  version?: number;
  format?: string;
  duration?: number;
  tracks?: Array<{
    id: string;
    type: string;
    label?: string;
    clips?: SequenceClip[];
  }>;
};

export type SequenceAsset = {
  id: string;
  url?: string | null;
  path?: string | null;
  thumbnail_url?: string | null;
  label?: string | null;
  fps?: number | string | null;
};

// A drawn region is given a TYPE after you draw it (popover on the shape) — not pre-selected.
// ぼかし = hide it; 生成 = let Dan generate something there; ダンに指示 = free-text instruction.
const INTENTS: Array<{ value: Intent; label: string }> = [
  { value: 'blur', label: 'ぼかし' },
  { value: 'generate', label: '生成' },
  { value: 'comment', label: 'ダンに指示' },
];

function fmtTime(value: number | null | undefined): string {
  const seconds = Math.max(0, value || 0);
  const m = Math.floor(seconds / 60);
  const s = seconds - m * 60;
  return `${String(m).padStart(2, '0')}:${s.toFixed(1).padStart(4, '0')}`;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

// Default span of a freshly-drawn clip, anchored AT the playhead (seconds). Short on purpose —
// the user trims from the panel / timeline rather than starting from the whole clip.
const DEFAULT_ANN_SPAN = 3;

// The tracked-blur box position at time t = the nearest sampled frame from track_boxes
// ({"t": [x,y,w,h] normalized}). Lets the preview animate the blur along the moving object.
function trackedBoxAt(
  boxes: Record<string, number[]> | undefined,
  t: number,
): { x: number; y: number; width: number; height: number } | null {
  if (!boxes) return null;
  const keys = Object.keys(boxes);
  if (keys.length === 0) return null;
  let bestK = keys[0];
  let bestD = Infinity;
  for (const k of keys) {
    const d = Math.abs(Number(k) - t);
    if (d < bestD) { bestD = d; bestK = k; }
  }
  const b = boxes[bestK];
  if (!b || b.length < 4) return null;
  return { x: b[0], y: b[1], width: b[2], height: b[3] };
}

// Serialization-stable signature of a value: sorts object keys and rounds numbers so the
// SAME logical sequence compares equal even after a backend round-trip reorders keys or
// reformats numbers (2 -> 2.0). Used to tell an autosave echo (skip) from a genuine new
// baseline (load + reset undo history).
function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === 'object') {
    const out: Record<string, unknown> = {};
    for (const k of Object.keys(value as Record<string, unknown>).sort()) out[k] = canonicalize((value as Record<string, unknown>)[k]);
    return out;
  }
  if (typeof value === 'number') return Math.round(value * 1000) / 1000;
  return value;
}
function seqSig(seq: unknown): string {
  return JSON.stringify(canonicalize(seq ?? null));
}

function makeId(): string {
  return `ann_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

// dataTransfer key for dragging a source asset from the material list onto the timeline.
// Keep in sync with the producer (production-workspace.tsx).
const ASSET_DND_TYPE = 'application/x-dan-asset';
// Fallback clip length (s) when a dropped asset has no known duration.
const DROP_DEFAULT_LEN = 5;

type TimelineDrag = {
  id: string;
  mode: 'move' | 'start' | 'end';
  startClientX: number;
  originalStart: number;
  originalEnd: number;
};

type PendingTimelineDrag = {
  mode: 'move' | 'start' | 'end';
  startClientX: number;
  originalStart: number;
  originalEnd: number;
};

type SequenceClipDrag = {
  id: string;
  mode: 'start' | 'end' | 'move';
  startClientX: number;
  startClientY: number;
  zone: 'visual' | 'audio';
  originalLayer: number;
  originalTimelineStart: number;
  originalTimelineEnd: number;
  originalSourceStart: number;
  originalSourceEnd: number;
};

type DraftAnnotation = Omit<ReviewAnnotation, 'id' | 'created_at'>;

function trackForIntent(intent: string): 'audio' | 'visual' {
  return intent === 'audio' ? 'audio' : 'visual';
}

function audioRoleLabel(role?: string | null): string {
  switch (role) {
    case 'dialogue':
      return '台詞';
    case 'music':
      return 'BGM';
    case 'sfx':
      return 'SE';
    default:
      return '音声';
  }
}

// Effective z-order layer of a clip when not explicitly set (matches timelineLanes).
function clipDefaultLayer(clip: SequenceClip): number {
  if (clip.track === 'audio' || clip.role) return clip.role === 'sfx' ? 1 : clip.role === 'music' ? 2 : 0;
  if (clip.track === 'caption' || typeof clip.text === 'string') return 2;
  if (clip.track === 'effect') return 3;
  if (clip.track === 'overlay' || clip.composition === 'pip' || clip.composition === 'overlay') return 1;
  return 0;
}

function itemTypeBadge(itemType: string): string {
  switch (itemType) {
    case 'video':
      return '動画';
    case 'caption':
      return 'テロップ';
    case 'effect':
      return '効果';
    case 'audio':
      return '音声';
    default:
      return INTENTS.find((it) => it.value === itemType)?.label || itemType;
  }
}

function clipItemColor(itemType: string): string {
  switch (itemType) {
    case 'caption':
      return 'bg-violet-500/60';
    case 'effect':
      return 'bg-amber-600/70';
    case 'audio':
      return 'bg-lime-600/60';
    default:
      return 'bg-neutral-700/80';
  }
}

function laneColor(intent: string, selected: boolean): string {
  if (selected) return 'border-yellow-300 bg-yellow-300/80 text-black';
  if (intent === 'blur') return 'border-sky-300 bg-sky-500/55 text-white';
  if (intent === 'cut_keep') return 'border-emerald-300 bg-emerald-500/55 text-white';
  if (intent === 'cut_remove') return 'border-red-300 bg-red-500/55 text-white';
  if (intent === 'caption') return 'border-violet-300 bg-violet-500/55 text-white';
  if (intent === 'replace' || intent === 'generate' || intent === 'motion') return 'border-amber-300 bg-amber-500/60 text-black';
  if (intent === 'audio') return 'border-lime-300 bg-lime-500/55 text-black';
  return 'border-zinc-300 bg-zinc-500/55 text-white';
}

function parseFps(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value) && value > 0) return value;
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  if (trimmed.includes('/')) {
    const [num, den] = trimmed.split('/').map(Number);
    if (Number.isFinite(num) && Number.isFinite(den) && den > 0) return num / den;
    return null;
  }
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}


export function VideoReviewEditor({
  initialPath,
  initialUrl,
  initialThumbnailUrl,
  initialFps,
  initialAnnotations,
  initialSequence,
  sequenceAssets,
  embedded = false,
  onBack,
  onSaveTimeline,
  onSyncCaptionAudio,
  onTrackBlur,
  onExecuteClip,
  onExecute,
  sidePanelTop,
}: {
  initialPath?: string;
  initialUrl?: string;
  initialThumbnailUrl?: string;
  initialFps?: number | string | null;
  initialAnnotations?: ReviewAnnotation[];
  initialSequence?: EditSequence | null;
  sequenceAssets?: SequenceAsset[];
  embedded?: boolean;
  onBack?: () => void;
  onSaveTimeline?: (payload: SessionPayload) => void | Promise<void>;
  onSyncCaptionAudio?: (captionIds: string[]) => Promise<Record<string, { text: string; start: number; end: number }[]>>;
  onTrackBlur?: (box: { x: number; y: number; width: number; height: number }, anchor: number, scanStart: number, scanEnd: number) => Promise<{ boxes: Record<string, number[]>; text?: string; t_start?: number | null; t_end?: number | null; found?: boolean }>;
  onExecuteClip?: (annotation: ReviewAnnotation) => void | Promise<void>;
  onExecute?: (payload: SessionPayload) => void | Promise<void>;
  sidePanelTop?: ReactNode;
}) {
  const stageRef = useRef<HTMLDivElement | null>(null);
  const timelineRef = useRef<HTMLDivElement | null>(null);
  const timelineScrollRef = useRef<HTMLDivElement | null>(null);
  // Unified undo/redo: one stack of combined {annotations, sequence} snapshots so Ctrl+Z
  // steps back through ALL edits (clip moves/cuts/deletes AND annotation changes) in the
  // order they happened. Rapid bursts (a drag, a slider sweep) coalesce into one entry.
  type HistEntry = { annotations: ReviewAnnotation[]; sequence: EditSequence | null };
  const histPastRef = useRef<HistEntry[]>([]);
  const histFutureRef = useRef<HistEntry[]>([]);
  const histPrevRef = useRef<HistEntry | null>(null);   // last observed state (baseline for the next diff)
  const histCheckpointRef = useRef<HistEntry | null>(null); // pre-burst state pending a coalesced push
  const histTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Right-drag rubber-band selection over the timeline (left-drag is reserved for scrub/move).
  const [marquee, setMarquee] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(null);
  const marqueeStartRef = useRef<{ x: number; y: number } | null>(null);
  // Live ghost of a material being dragged over the timeline (before it's dropped).
  const [dropPreview, setDropPreview] = useState<{ zone: 'visual' | 'audio'; layer: number; start: number; len: number } | null>(null);
  const [videoPath, setVideoPath] = useState(initialPath || '');
  const [videoUrl, setVideoUrl] = useState(initialUrl || '');
  const [duration] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [tool, setTool] = useState<Tool>('rect');
  const [annotations, setAnnotations] = useState<ReviewAnnotation[]>(initialAnnotations || []);
  const [editSequence, setEditSequence] = useState<EditSequence | null>(initialSequence || null);
  const [pendingAnnotation, setPendingAnnotation] = useState<DraftAnnotation | null>(null);
  // A freshly-drawn shape waiting for the user to pick its type (ぼかし/生成/ダンに指示) from a
  // popover anchored at the shape. Nothing is committed until a type is chosen.
  const [typePicker, setTypePicker] = useState<{ kind: 'rect' | 'freehand'; data: Record<string, unknown>; cx: number; cy: number } | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [selectedSequenceClipId, setSelectedSequenceClipId] = useState<string | null>(null);
  const [selectedSequenceClipIds, setSelectedSequenceClipIds] = useState<string[]>([]);
  const [draftRect, setDraftRect] = useState<{ start: Point; end: Point } | null>(null);
  const [draftPath, setDraftPath] = useState<Point[] | null>(null);
  const [isPointerDown, setIsPointerDown] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [timelineDrag, setTimelineDrag] = useState<TimelineDrag | null>(null);
  const [pendingTimelineDrag, setPendingTimelineDrag] = useState<PendingTimelineDrag | null>(null);
  const [sequenceClipDrag, setSequenceClipDrag] = useState<SequenceClipDrag | null>(null);
  // Snapshot of the sequence at the moment a clip drag starts, so overwrite/trim of
  // neighbours is computed from the ORIGINAL state each move (non-cumulative).
  const dragSnapshotRef = useRef<EditSequence | null>(null);
  // The set of clip ids that move together for the current drag (>1 = block move of the
  // whole selection; 1 = ordinary single-clip move). Captured at drag start.
  const dragSelectionRef = useRef<string[]>([]);
  // The lane (layer) a single-clip vertical drag is currently committed to. Hysteresis: only
  // changes when the cursor is clearly inside another lane, so it doesn't flicker at borders.
  const dragLayerRef = useRef<number | null>(null);
  // Lane geometry FROZEN at drag start. Hit-testing a vertical drag against the live geometry
  // is unstable: moving the clip to another layer resizes lanes (a lane with a clip is taller),
  // which shifts borders under the cursor and makes the lane flip back and forth. Freezing the
  // geometry for the duration of the drag gives a fixed, predictable target for each Y.
  const dragLaneGeomRef = useRef<Array<{ zone: 'visual' | 'audio'; layer: number; top: number; bottom: number }> | null>(null);
  // A/V link: when on, dragging/trimming a clip also moves its linked partner (same link_id).
  const [linkAV, setLinkAV] = useState(true);
  const [extraLanes, setExtraLanes] = useState<{ visual: number; audio: number }>({ visual: 0, audio: 0 });
  const [openNoteKey, setOpenNoteKey] = useState<string | null>(null);
  const laneGeomRef = useRef<Array<{ zone: 'visual' | 'audio'; layer: number; top: number; bottom: number }>>([]);
  const [isTimelineScrubbing, setIsTimelineScrubbing] = useState(false);
  const [timelineZoom, setTimelineZoom] = useState(1);
  const [timelineHeight, setTimelineHeight] = useState(300);
  const [timelineResizeStart, setTimelineResizeStart] = useState<{ clientY: number; height: number } | null>(null);
  // The preview canvas (TimelinePreview) fills the aspect-locked stage exactly, so
  // the annotation overlay always maps to the full stage rect — no per-frame measuring.
  const videoContentStyle: CSSProperties = { inset: 0 };
  const [playing, setPlaying] = useState(false);
  const fps = useMemo(() => parseFps(initialFps) || 30, [initialFps]);

  const sequenceAssetMap = useMemo(
    () => new Map((sequenceAssets || []).map((asset) => [asset.id, asset])),
    [sequenceAssets]
  );

  const sequenceVideoClips = useMemo(
    () => (editSequence?.tracks || []).flatMap((track) => (track.type === 'video' ? track.clips || [] : [])),
    [editSequence]
  );
  const allSequenceClips = useMemo(
    () => (editSequence?.tracks || []).flatMap((track) => track.clips || []),
    [editSequence]
  );

  // NLE-style ordered lanes derived from the sequence tracks + annotations.
  // Order top→bottom: visual instructions, captions, effects, overlay video
  // layers, base video (middle), audio lanes by role, audio instructions.
  const timelineLanes = useMemo<TimelineLane[]>(() => {
    const tracks = editSequence?.tracks || [];
    // NLE-style free layers: the only fixed rule is visual-on-top / audio-on-bottom.
    // Within each zone, layers are free — any clip/annotation can sit on any layer,
    // higher layer = closer to front (z-order). Roles/types are per-item badges, not
    // dedicated lanes.
    type Agg = { zone: 'visual' | 'audio'; layer: number; item: LaneItem };
    const aggs: Agg[] = [];
    const audioRoleLayer = (role?: string | null) => (role === 'sfx' ? 1 : role === 'music' ? 2 : 0);

    let counter = 0;
    for (const track of tracks) {
      for (const clip of track.clips || []) {
        let zone: 'visual' | 'audio' = 'visual';
        let itemType = 'video';
        let layer = clip.layer ?? 0;
        if (track.type === 'audio') {
          zone = 'audio';
          itemType = 'audio';
          layer = clip.layer ?? audioRoleLayer(clip.role);
        } else if (track.type === 'caption') {
          itemType = 'caption';
          layer = clip.layer ?? 2;
        } else if (track.type === 'effect') {
          itemType = 'effect';
          layer = clip.layer ?? 3;
        } else if (track.type === 'overlay') {
          itemType = 'video';
          layer = clip.layer ?? 1;
        } else {
          const overlay = clip.composition === 'pip' || clip.composition === 'overlay';
          itemType = 'video';
          layer = clip.layer ?? (overlay ? 1 : 0);
        }
        aggs.push({
          zone,
          layer,
          item: {
            key: clip.id || `${track.id || 'tk'}-${counter++}`,
            kind: 'clip',
            itemType,
            start: clip.timeline_start,
            end: clip.timeline_end,
            clip,
          },
        });
      }
    }

    for (const a of annotations) {
      const zone = trackForIntent(a.intent);
      // Annotations carry their own lane via data.layer (default 5 = a lane above the clips), so
      // they can be dragged up/down between lanes like clips. Falls back to 5 for legacy ones.
      const annLayer = Number((a.data as { layer?: number } | undefined)?.layer);
      aggs.push({
        zone,
        layer: Number.isFinite(annLayer) ? annLayer : 5,
        item: { key: a.id, kind: 'annotation', itemType: a.intent, start: a.start, end: a.end ?? a.start + 0.2, annotation: a },
      });
    }

    const buildZone = (zone: 'visual' | 'audio'): TimelineLane[] => {
      const zoneAggs = aggs.filter((g) => g.zone === zone);
      const layers = new Set(zoneAggs.map((g) => g.layer));
      // ALWAYS keep one spare empty lane (plus any added via "+段") so a clip can always be
      // dragged up/down to a new lane — moving it there effectively creates the lane, and a
      // fresh spare appears. This is why video/audio clips couldn't move before: with only one
      // used lane there was no target.
      const maxUsed = layers.size ? Math.max(...layers) : 0;
      for (let k = 1; k <= extraLanes[zone] + 1; k += 1) layers.add(maxUsed + k);
      if (layers.size === 0) layers.add(0);
      const ordered = Array.from(layers).sort((x, y) => (zone === 'visual' ? y - x : x - y));
      return ordered.map((layer, i) => {
        const items = zoneAggs.filter((g) => g.layer === layer).map((g) => g.item);
        const hasVideo = items.some((it) => it.itemType === 'video');
        return {
          key: `${zone}-${layer}`,
          label: `${zone === 'visual' ? '映像' : '音声'}${i + 1}`,
          zone,
          layer,
          height: zone === 'audio' ? 26 : hasVideo ? 52 : 30,
          items,
        };
      });
    };

    return [...buildZone('visual'), ...buildZone('audio')];
  }, [editSequence, annotations, extraLanes]);

  // Y-geometry of each lane within the tracks column, for vertical drag hit-testing.
  const laneGeom = useMemo(() => {
    const out: Array<{ zone: 'visual' | 'audio'; layer: number; top: number; bottom: number }> = [];
    let cursor = 0;
    timelineLanes.forEach((lane, i) => {
      if (i > 0) cursor += timelineLanes[i - 1].zone !== lane.zone ? 14 : 4;
      const top = cursor;
      cursor += lane.height;
      out.push({ zone: lane.zone, layer: lane.layer, top, bottom: cursor });
    });
    return out;
  }, [timelineLanes]);
  laneGeomRef.current = laneGeom;

  const sessionQuery = useMemo(() => {
    const params = new URLSearchParams();
    if (videoPath) params.set('video_path', videoPath);
    if (videoUrl) params.set('video_url', videoUrl);
    return params.toString();
  }, [videoPath, videoUrl]);

  const selected = annotations.find((a) => a.id === selectedId) || null;
  const selectedSequenceClip = allSequenceClips.find((clip) => clip.id === selectedSequenceClipId) || null;
  // Clips that should appear selected: the explicitly selected ones, PLUS their A/V-linked
  // partners (so clicking audio also highlights its video and vice versa) when link is on.
  const highlightedClipIds = useMemo(() => {
    const ids = new Set(selectedSequenceClipIds);
    if (linkAV) {
      const linkIds = new Set(
        allSequenceClips.filter((c) => ids.has(c.id) && c.link_id).map((c) => c.link_id)
      );
      allSequenceClips.forEach((c) => {
        if (c.link_id && linkIds.has(c.link_id)) ids.add(c.id);
      });
    }
    return ids;
  }, [allSequenceClips, linkAV, selectedSequenceClipIds]);
  // Sync the working copy from the prop ONLY when its content genuinely changes
  // (e.g. a fresh Dan render), NOT on every parent re-render / poll. The parent
  // re-creates an equal-value sequence object on each poll; without this guard the
  // effect would reset editSequence every few seconds and wipe in-progress manual
  // edits (drag/trim/delete appeared to "do nothing").
  // The single source of truth for "what value is in sync with the backend". Advanced when we
  // adopt a parent value AND when we autosave. The parent polls and can lag (serve a value the
  // backend had a moment ago); comparing the INCOMING value against this — not against the live
  // edit — means a stale echo (== lastSynced) is skipped, so local edits/undo aren't reverted
  // during the save lag. Only an incoming value that differs from lastSynced is a genuine new
  // baseline (Dan render / external change) → adopt it and reset the undo history. Canonical
  // compare ignores key order / number reformat from the round-trip.
  const lastSyncedSig = useRef<string>(seqSig(initialSequence));
  // Annotations (blur boxes etc.) autosave separately — the sequence sig doesn't cover them, so
  // without this a drawn blur never reaches the backend/export. Echo-safe via seqSig.
  const lastSyncedAnnSig = useRef<string>(seqSig(initialAnnotations || []));
  // Every value the editor itself has held (current + recent past). The parent POLLS the server
  // (loadAll every few seconds) and can hand back a value that LAGS our latest edit — e.g. right
  // after we save a resize, an in-flight poll returns the pre-save length. Comparing only against
  // the single lastSynced sig, that lagging echo looks like an external change and gets adopted
  // for one frame ("revert to old length, then back"). A value we've ALREADY produced locally is
  // never a genuine external change, so down-sync skips it. Only a sig we've never held (a real
  // Dan render /外部更新) is adopted. Bounded so it can't grow without limit.
  const localSeqSigs = useRef<Set<string>>(new Set([seqSig(initialSequence)]));
  const localAnnSigs = useRef<Set<string>>(new Set([seqSig(initialAnnotations || [])]));
  const rememberLocalSig = (set: React.MutableRefObject<Set<string>>, sig: string) => {
    const s = set.current;
    s.add(sig);
    if (s.size > 80) s.delete(s.values().next().value as string);
  };
  useEffect(() => { rememberLocalSig(localSeqSigs, seqSig(editSequence)); }, [editSequence]);
  useEffect(() => { rememberLocalSig(localAnnSigs, seqSig(annotations)); }, [annotations]);
  useEffect(() => {
    const sig = seqSig(initialSequence);
    // Skip if this is the current sync point OR any state we've held locally (a lagging poll echo).
    if (sig === lastSyncedSig.current || localSeqSigs.current.has(sig)) return;
    lastSyncedSig.current = sig;
    // genuine new baseline: reset undo history and pre-sync histPrevRef so the resulting
    // setEditSequence isn't itself recorded as an undoable step.
    histPastRef.current = [];
    histFutureRef.current = [];
    histCheckpointRef.current = null;
    if (histTimerRef.current) { clearTimeout(histTimerRef.current); histTimerRef.current = null; }
    histPrevRef.current = { annotations, sequence: initialSequence || null };
    setEditSequence(initialSequence || null);
  }, [annotations, initialSequence]);

  const sequenceDuration = useMemo(
    () => Number(editSequence?.duration || Math.max(0, ...sequenceVideoClips.map((clip) => clip.timeline_end || 0))),
    [editSequence, sequenceVideoClips]
  );
  // Real content end (used for the time readout and playback).
  const contentDuration = sequenceDuration > 0 ? sequenceDuration : duration;
  // The timeline VIEW spans a bit past the content so there's breathing room at the end to
  // drop/move clips (otherwise the last clip is flush against the right edge = cramped).
  // Every px<->sec mapping uses this, so clips, drags and scrub all stay consistent.
  const timelineDuration = contentDuration > 0 ? contentDuration + Math.max(3, contentDuration * 0.08) : contentDuration;
  const previewAspect = useMemo(() => {
    const [a, b] = (editSequence?.format || initialSequence?.format || '9:16').split(':');
    return `${Number(a) || 9} / ${Number(b) || 16}`;
  }, [editSequence?.format, initialSequence?.format]);
  // Stable callbacks: passing inline arrows would change every render and re-run the
  // preview's playback effect each frame, resetting its master clock (stutter/rewind).
  const handlePreviewTime = useCallback((t: number) => setCurrentTime(t), []);
  const handlePreviewEnded = useCallback(() => setPlaying(false), []);
  const seekTimeline = useCallback(
    (time: number) => {
      const maxDuration = timelineDuration || duration || 0;
      const nextTime = Number(clamp(time, 0, maxDuration).toFixed(3));
      setPlaying(false);
      setCurrentTime(nextTime);
    },
    [duration, timelineDuration]
  );
  const isActiveAnnotation = useCallback(
    (annotation: Pick<ReviewAnnotation, 'start' | 'end'>) => (
      currentTime >= annotation.start && currentTime <= (annotation.end ?? annotation.start + 0.2)
    ),
    [currentTime]
  );
  const effectiveDrawStart = useMemo(() => {
    return Number(currentTime.toFixed(2));
  }, [currentTime]);
  // Blur regions active at the current time, resolved to their tracked position. Drawn ON the
  // canvas (in TimelinePreview) — NOT via CSS backdrop-filter, which flickers when the canvas
  // under it repaints / the component re-renders.
  const activeBlurRegions = useMemo(() => {
    return annotations
      .filter((a) => a.intent === 'blur' && a.kind === 'rect' && isActiveAnnotation(a))
      .map((a) => {
        const d = (a.data || {}) as { x?: number; y?: number; width?: number; height?: number; track?: boolean; track_boxes?: Record<string, number[]> };
        const tracked = d.track ? trackedBoxAt(d.track_boxes, currentTime) : null;
        return tracked || { x: Number(d.x || 0), y: Number(d.y || 0), width: Number(d.width || 0), height: Number(d.height || 0) };
      });
  }, [annotations, currentTime, isActiveAnnotation]);

  const payload: SessionPayload = useMemo(
    () => ({
      video_path: videoPath || null,
      video_url: videoUrl || null,
      duration,
      annotations,
      sequence: editSequence,
    }),
    [annotations, duration, editSequence, videoPath, videoUrl]
  );

  // Push the pending pre-burst checkpoint into the undo stack (called when the coalesce
  // window closes, or eagerly right before an undo/redo so nothing in-flight is lost).
  const flushHistory = useCallback(() => {
    if (histTimerRef.current) { clearTimeout(histTimerRef.current); histTimerRef.current = null; }
    if (histCheckpointRef.current) {
      histPastRef.current = [...histPastRef.current.slice(-79), histCheckpointRef.current];
      histFutureRef.current = [];
      histCheckpointRef.current = null;
    }
  }, []);

  useEffect(() => {
    const cur: HistEntry = { annotations, sequence: editSequence };
    if (histPrevRef.current === null) { histPrevRef.current = cur; return; }
    const prev = histPrevRef.current;
    // Programmatic restores (undo/redo/baseline/load) pre-set histPrevRef to the value they
    // apply, so this comparison sees "no change" and records nothing — no fragile flag needed.
    if (prev.annotations === annotations && prev.sequence === editSequence) return;
    // Open a coalesce window capturing the state BEFORE this burst; reset the timer on each
    // change so a continuous gesture lands as a single undo step.
    if (histCheckpointRef.current === null) histCheckpointRef.current = prev;
    histPrevRef.current = cur;
    if (histTimerRef.current) clearTimeout(histTimerRef.current);
    histTimerRef.current = setTimeout(() => {
      histTimerRef.current = null;
      if (histCheckpointRef.current) {
        histPastRef.current = [...histPastRef.current.slice(-79), histCheckpointRef.current];
        histFutureRef.current = [];
        histCheckpointRef.current = null;
      }
    }, 300);
  }, [annotations, editSequence]);

  const getPoint = useCallback((event: React.PointerEvent): Point | null => {
    const stage = stageRef.current;
    if (!stage) return null;
    const stageRect = stage.getBoundingClientRect();
    const left = Number(videoContentStyle.left || 0);
    const top = Number(videoContentStyle.top || 0);
    const width = Number(videoContentStyle.width || stageRect.width);
    const height = Number(videoContentStyle.height || stageRect.height);
    return {
      x: clamp((event.clientX - stageRect.left - left) / width, 0, 1),
      y: clamp((event.clientY - stageRect.top - top) / height, 0, 1),
    };
  }, [videoContentStyle]);

  const loadSession = useCallback(async () => {
    if (!sessionQuery) return;
    try {
      const res = await fetch(`/api/v1/video-review/sessions?${sessionQuery}`, { credentials: 'include' });
      if (!res.ok) {
        // Non-fatal: keep editing with the current state rather than blocking the UI.
        console.warn('review session load failed', res.status);
        return;
      }
      const data = (await res.json()) as SessionPayload;
      const loadedAnnotations = data.annotations || [];
      const nextAnnotations = loadedAnnotations.length > 0 ? loadedAnnotations : initialAnnotations || [];
      // Only adopt a GENUINELY external change. Skip the current sync point AND any annotation
      // state we've held locally — a lagging poll echo (parent returns the pre-save annotations
      // right after we save a new blur) is a past local value, not external, so adopting it would
      // make the just-created blur "disappear then reappear". (Also covers the "vanishes after
      // 0.3s" in-flight case.)
      const nextSig = seqSig(nextAnnotations);
      if (nextSig === lastSyncedAnnSig.current || localAnnSigs.current.has(nextSig)) return;
      histPastRef.current = [];
      histFutureRef.current = [];
      histCheckpointRef.current = null;
      // pre-sync the baseline so this load isn't recorded as an undoable edit
      histPrevRef.current = { annotations: nextAnnotations, sequence: histPrevRef.current?.sequence ?? null };
      lastSyncedAnnSig.current = seqSig(nextAnnotations); // adopted from parent -> not our edit to re-save
      setAnnotations(nextAnnotations);
    } catch (err) {
      // Network blip (e.g. the sandbox restarting mid-edit) must NOT crash the editor —
      // a thrown fetch() here previously surfaced as a "Failed to fetch" runtime overlay.
      console.warn('review session fetch failed (keeping current edits)', err);
    }
  }, [initialAnnotations, sessionQuery]);

  useEffect(() => {
    void loadSession();
  }, [loadSession]);

  const saveSession = useCallback(async () => {
    if (!videoPath && !videoUrl) {
      toast.error('動画パスかURLを指定してください');
      return;
    }
    setIsSaving(true);
    try {
      const res = await fetch('/api/v1/video-review/sessions', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(await res.text());
      await onSaveTimeline?.(payload);
      toast.success('レビュー情報を保存しました');
    } catch (error) {
      toast.error('保存に失敗しました', { description: String(error).slice(0, 180) });
    } finally {
      setIsSaving(false);
    }
  }, [onSaveTimeline, payload, videoPath, videoUrl]);

  // Auto-save manual edits (debounced) so a page refresh keeps them. The parent
  // re-creates onSaveTimeline/payload on every poll-driven re-render, so we hold them
  // in a ref and re-arm the debounce ONLY when the edited sequence actually changes
  // (canonical compare) — otherwise the timer would be cleared every couple seconds and
  // never fire, and we'd re-save echoes/undo round-trips in a loop.
  const autoSaveRef = useRef<{ save?: typeof onSaveTimeline; payload: SessionPayload }>({ save: onSaveTimeline, payload });
  autoSaveRef.current = { save: onSaveTimeline, payload };
  useEffect(() => {
    const sig = seqSig(editSequence);
    if (sig === lastSyncedSig.current) return; // unchanged since last sync/save -> nothing to save
    const timer = window.setTimeout(() => {
      lastSyncedSig.current = sig; // our save is now the known in-sync value (parent echoes skip)
      void autoSaveRef.current.save?.(autoSaveRef.current.payload);
    }, 1200);
    return () => window.clearTimeout(timer);
  }, [editSequence]);

  // Autosave annotation edits (blur boxes etc.) — separate from the sequence save above.
  useEffect(() => {
    const sig = seqSig(annotations);
    if (sig === lastSyncedAnnSig.current) return;
    const timer = window.setTimeout(() => {
      lastSyncedAnnSig.current = sig;
      void autoSaveRef.current.save?.(autoSaveRef.current.payload);
    }, 1200);
    return () => window.clearTimeout(timer);
  }, [annotations]);

  const makeDraftAnnotation = useCallback(
    (annotation: Omit<ReviewAnnotation, 'id' | 'intent' | 'note' | 'start' | 'end' | 'created_at'>, intentArg: Intent = 'blur'): DraftAnnotation => {
      const fallbackStart = effectiveDrawStart;
      const fallbackEnd = Number(Math.min(duration || fallbackStart + 1, fallbackStart + 1).toFixed(2));
      const start = Math.min(fallbackStart, fallbackEnd);
      const end = Math.max(fallbackStart, fallbackEnd);
      return {
        ...annotation,
        intent: intentArg,
        note: null,
        start,
        end: end > start ? end : start + 0.5,
      };
    },
    [duration, effectiveDrawStart]
  );

  useEffect(() => {
    if (!timelineResizeStart) return;
    const moveResize = (event: PointerEvent) => {
      const delta = timelineResizeStart.clientY - event.clientY;
      setTimelineHeight(clamp(timelineResizeStart.height + delta, 180, 520));
    };
    const stopResize = () => setTimelineResizeStart(null);
    window.addEventListener('pointermove', moveResize);
    window.addEventListener('pointerup', stopResize);
    window.addEventListener('pointercancel', stopResize);
    return () => {
      window.removeEventListener('pointermove', moveResize);
      window.removeEventListener('pointerup', stopResize);
      window.removeEventListener('pointercancel', stopResize);
    };
  }, [timelineResizeStart]);

  const selectAnnotation = useCallback((id: string, additive = false) => {
    setSelectedSequenceClipId(null);
    setSelectedSequenceClipIds([]);
    setSelectedIds((current) => {
      if (!additive) return [id];
      return current.includes(id) ? current.filter((item) => item !== id) : [...current, id];
    });
    setSelectedId((current) => {
      if (!additive) return id;
      return current === id ? null : id;
    });
  }, []);

  const selectSequenceClip = useCallback((id: string, additive = false) => {
    setSelectedId(null);
    setSelectedIds([]);
    setSelectedSequenceClipIds((current) => {
      if (!additive) return [id];
      return current.includes(id) ? current.filter((item) => item !== id) : [...current, id];
    });
    setSelectedSequenceClipId((current) => {
      if (!additive) return id;
      return current === id ? null : id;
    });
  }, []);

  const clearSelection = useCallback(() => {
    setSelectedId(null);
    setSelectedIds([]);
    setSelectedSequenceClipId(null);
    setSelectedSequenceClipIds([]);
  }, []);

  const confirmPendingAnnotation = useCallback(() => {
    if (!pendingAnnotation) return;
    const next: ReviewAnnotation = {
      ...pendingAnnotation,
      id: makeId(),
      created_at: new Date().toISOString(),
    };
    setAnnotations((prev) => [...prev, next]);
    setSelectedId(next.id);
    setSelectedIds([next.id]);
    setPendingAnnotation(null);
  }, [pendingAnnotation]);

  // Commit an annotation immediately on draw — no "タイムラインに追加" step. Selected so the
  // options show right away; deletable with Delete. The clip is ANCHORED AT THE PLAYHEAD (red
  // line) with a short default span (NOT the whole clip / not [0,playhead]). Trim start/end on
  // the timeline, or with the "開始/終了＝再生位置" buttons.
  const commitAnnotation = useCallback(
    (annotation: Omit<ReviewAnnotation, 'id' | 'intent' | 'note' | 'start' | 'end' | 'created_at'>, intentArg: Intent = 'blur') => {
      const draft = makeDraftAnnotation(annotation, intentArg);
      const maxDur = contentDuration > 0 ? contentDuration : effectiveDrawStart + DEFAULT_ANN_SPAN;
      const start = Number(clamp(effectiveDrawStart, 0, Math.max(0, maxDur - 0.1)).toFixed(2));
      const end = Number(clamp(start + DEFAULT_ANN_SPAN, start + 0.1, maxDur).toFixed(2));
      const next: ReviewAnnotation = {
        ...draft,
        id: makeId(),
        created_at: new Date().toISOString(),
        start,
        end,
      };
      setAnnotations((prev) => [...prev, next]);
      setSelectedId(next.id);
      setSelectedIds([next.id]);
      setPendingAnnotation(null);
    },
    [contentDuration, effectiveDrawStart, makeDraftAnnotation]
  );

  const updateSelected = useCallback((patch: Partial<ReviewAnnotation>) => {
    if (!selectedId) return;
    setAnnotations((prev) => prev.map((a) => (a.id === selectedId ? { ...a, ...patch } : a)));
  }, [selectedId]);

  // Per-clip 実行 (生成/ダンに指示): dispatch this one instruction clip to Dan and reflect it.
  const [executingId, setExecutingId] = useState<string | null>(null);
  const runExecuteClip = useCallback(async (ann: ReviewAnnotation) => {
    if (!onExecuteClip) return;
    setExecutingId(ann.id);
    try {
      await onExecuteClip(ann);
    } finally {
      setExecutingId(null);
    }
  }, [onExecuteClip]);

  // 追従ぼかし: run the tracker on a drawn box; store its per-frame path (track_boxes) on the
  // annotation so the preview animates the blur box along the moving object (real tracking).
  const [trackingId, setTrackingId] = useState<string | null>(null);
  const runTrackBlur = useCallback(async (ann: ReviewAnnotation) => {
    if (!onTrackBlur || ann.kind !== 'rect') return;
    const d = (ann.data || {}) as { x?: number; y?: number; width?: number; height?: number };
    setTrackingId(ann.id);
    try {
      // anchor = the playhead frame the box was drawn on; scan the WHOLE clip so tracking can
      // discover the time range the text is visible (track-first: that range becomes the clip).
      const scanEnd = contentDuration > 0 ? contentDuration : 0;
      const r = await onTrackBlur(
        { x: Number(d.x || 0), y: Number(d.y || 0), width: Number(d.width || 0), height: Number(d.height || 0) },
        Number(currentTime || 0),
        0,
        scanEnd,
      );
      const hasPath = r.found && r.boxes && Object.keys(r.boxes).length > 0;
      setAnnotations((prev) => prev.map((a) => {
        if (a.id !== ann.id) return a;
        const nextStart = hasPath && typeof r.t_start === 'number' ? Number(r.t_start.toFixed(2)) : a.start;
        const nextEnd = hasPath && typeof r.t_end === 'number' ? Number(r.t_end.toFixed(2)) : a.end;
        return {
          ...a,
          // track-first: the tracked range DEFINES the clip span.
          start: nextStart,
          end: nextEnd,
          data: { ...(a.data as object), track: true, track_boxes: r.boxes || {}, track_text: r.text || '' },
        };
      }));
    } finally {
      setTrackingId(null);
    }
  }, [onTrackBlur, currentTime, contentDuration]);

  const updatePending = useCallback((patch: Partial<DraftAnnotation>) => {
    setPendingAnnotation((current) => (current ? { ...current, ...patch } : current));
  }, []);

  const updatePendingTime = useCallback((start: number, end: number) => {
    const maxDuration = duration || Math.max(end, start + 0.1);
    const nextStart = Number(clamp(start, 0, maxDuration).toFixed(2));
    const nextEnd = Number(clamp(end, nextStart + 0.1, maxDuration).toFixed(2));
    setPendingAnnotation((current) => (current ? { ...current, start: nextStart, end: nextEnd } : current));
  }, [duration]);

  const deleteSelected = useCallback(() => {
    const annotationIds = selectedIds.length > 0 ? selectedIds : selectedId ? [selectedId] : [];
    const clipIds = selectedSequenceClipIds.length > 0 ? selectedSequenceClipIds : selectedSequenceClipId ? [selectedSequenceClipId] : [];
    if (annotationIds.length === 0 && clipIds.length === 0) return;
    if (annotationIds.length > 0) {
      const selectedSet = new Set(annotationIds);
      setAnnotations((prev) => prev.filter((a) => !selectedSet.has(a.id)));
    }
    if (clipIds.length > 0) {
      const selectedSet = new Set(clipIds);
      setEditSequence((current) => {
        if (!current) return current;
        const allClips = (current.tracks || []).flatMap((t) => t.clips || []);
        // With A/V link on, deleting a clip also deletes its linked partner.
        if (linkAV) {
          const linkIds = new Set(allClips.filter((c) => selectedSet.has(c.id) && c.link_id).map((c) => c.link_id));
          allClips.forEach((c) => { if (c.link_id && linkIds.has(c.link_id)) selectedSet.add(c.id); });
        }
        const tracks = (current.tracks || []).map((track) => ({
          ...track,
          clips: (track.clips || []).filter((clip) => !selectedSet.has(clip.id)),
        }));
        const nextDuration = Math.max(0, ...tracks.flatMap((track) => (track.clips || []).map((clip) => clip.timeline_end || 0)));
        return { ...current, duration: Number(nextDuration.toFixed(3)), tracks };
      });
    }
    clearSelection();
  }, [clearSelection, linkAV, selectedId, selectedIds, selectedSequenceClipId, selectedSequenceClipIds]);

  // Ripple delete: remove the selected clip(s) (+ A/V-link partners) and close the gap ONLY on
  // each affected lane (same track+layer) — later clips on that lane slide left to fill the
  // hole. Clips on OTHER lanes are left exactly where they are (a clip that merely overlaps in
  // time is NOT touched). Each remaining clip shifts left by the total duration of deleted
  // clips that ended before it on its own lane, so multiple deletions and clips between them
  // are handled correctly.
  const rippleDelete = useCallback(() => {
    const clipIds = selectedSequenceClipIds.length > 0 ? selectedSequenceClipIds : selectedSequenceClipId ? [selectedSequenceClipId] : [];
    if (clipIds.length === 0) { deleteSelected(); return; }
    setEditSequence((current) => {
      if (!current) return current;
      const r = (v: number) => Number(v.toFixed(2));
      const eps = 0.01;
      const del = new Set(clipIds);
      const laneKey = (c: SequenceClip, fallbackTrack?: string) => `${c.track || fallbackTrack || ''}#${c.layer ?? 0}`;
      const allClips = (current.tracks || []).flatMap((t) => (t.clips || []).map((c) => ({ ...c, track: c.track || t.type })));
      if (linkAV) {
        const linkIds = new Set(allClips.filter((c) => del.has(c.id) && c.link_id).map((c) => c.link_id));
        allClips.forEach((c) => { if (c.link_id && linkIds.has(c.link_id)) del.add(c.id); });
      }
      const delClips = allClips.filter((c) => del.has(c.id));
      if (delClips.length === 0) return current;
      // group the deleted clips' durations by lane
      const delByLane = new Map<string, Array<{ end: number; dur: number }>>();
      for (const c of delClips) {
        const k = laneKey(c);
        if (!delByLane.has(k)) delByLane.set(k, []);
        delByLane.get(k)!.push({ end: c.timeline_end, dur: c.timeline_end - c.timeline_start });
      }
      const tracks = (current.tracks || []).map((track) => {
        const out: SequenceClip[] = [];
        for (const c of track.clips || []) {
          if (del.has(c.id)) continue; // removed
          const dels = delByLane.get(laneKey(c, track.type));
          if (!dels) { out.push(c); continue; } // lane untouched
          // shift left by the total deleted duration that sat before this clip on the same lane
          const shift = dels.reduce((s, d) => s + (d.end <= c.timeline_start + eps ? d.dur : 0), 0);
          out.push(shift > eps ? { ...c, timeline_start: r(c.timeline_start - shift), timeline_end: r(c.timeline_end - shift) } : c);
        }
        return { ...track, clips: out };
      });
      const nextDuration = Math.max(0, ...tracks.flatMap((t) => (t.clips || []).map((c) => c.timeline_end || 0)));
      return { ...current, duration: Number(nextDuration.toFixed(3)), tracks };
    });
    clearSelection();
  }, [clearSelection, deleteSelected, linkAV, selectedSequenceClipId, selectedSequenceClipIds]);

  // Cut at the playhead: every targeted clip the playhead crosses becomes two clips that
  // join exactly at `t` with continuous source ranges (no frame gained/lost). With a
  // selection we cut only those clips (+ their A/V-link partner); with no selection we cut
  // every clip under the playhead. Each pair of right-halves gets a fresh shared link_id so
  // A/V partners stay paired on both sides of the cut. Total duration is unchanged.
  const splitClipAtTime = useCallback((t: number, clipIds?: Set<string>) => {
    setEditSequence((current) => {
      if (!current) return current;
      const r = (v: number) => Number(v.toFixed(2));
      const inside = (c: SequenceClip) => t > c.timeline_start + 0.05 && t < c.timeline_end - 0.05;
      const allClips = (current.tracks || []).flatMap((tr) => tr.clips || []);
      let targets: Set<string>;
      if (clipIds && clipIds.size > 0) {
        targets = new Set(clipIds);
        if (linkAV) {
          const linkIds = new Set(allClips.filter((c) => targets.has(c.id) && c.link_id).map((c) => c.link_id));
          allClips.forEach((c) => { if (c.link_id && linkIds.has(c.link_id)) targets.add(c.id); });
        }
      } else {
        targets = new Set(allClips.filter(inside).map((c) => c.id));
      }
      if (targets.size === 0) return current;
      const rightLink = new Map<string, string>(); // original link_id -> new link_id for right halves
      let cut = 0;
      const tracks = (current.tracks || []).map((track) => {
        const out: SequenceClip[] = [];
        for (const c of track.clips || []) {
          if (!(targets.has(c.id) && inside(c))) { out.push(c); continue; }
          cut += 1;
          const d = t - c.timeline_start;
          const isAV = Number.isFinite(c.source_end as number);
          let newLink: string | undefined;
          if (c.link_id) {
            newLink = rightLink.get(c.link_id);
            if (!newLink) { newLink = `lk_${makeId()}`; rightLink.set(c.link_id, newLink); }
          }
          out.push({ ...c, timeline_end: r(t), ...(isAV ? { source_end: r(Number(c.source_start || 0) + d) } : {}) });
          out.push({ ...c, id: `${c.id}__s_${makeId()}`, timeline_start: r(t),
            ...(isAV ? { source_start: r(Number(c.source_start || 0) + d) } : {}),
            ...(newLink ? { link_id: newLink } : {}) });
        }
        return { ...track, clips: out };
      });
      if (cut === 0) return current;
      return { ...current, tracks };
    });
  }, [linkAV]);

  const splitAtPlayhead = useCallback(() => {
    const ids = new Set(selectedSequenceClipIds.length > 0 ? selectedSequenceClipIds : selectedSequenceClipId ? [selectedSequenceClipId] : []);
    splitClipAtTime(currentTime, ids);
  }, [currentTime, selectedSequenceClipId, selectedSequenceClipIds, splitClipAtTime]);

  const undo = useCallback(() => {
    flushHistory();
    const previous = histPastRef.current.pop();
    if (!previous) return;
    histFutureRef.current = [{ annotations, sequence: editSequence }, ...histFutureRef.current].slice(0, 80);
    histPrevRef.current = previous; // pre-sync so restoring doesn't record a new entry
    setAnnotations(previous.annotations);
    setEditSequence(previous.sequence);
    clearSelection();
  }, [annotations, editSequence, flushHistory, clearSelection]);

  const redo = useCallback(() => {
    const next = histFutureRef.current.shift();
    if (!next) return;
    histPastRef.current = [...histPastRef.current.slice(-79), { annotations, sequence: editSequence }];
    histPrevRef.current = next;
    setAnnotations(next.annotations);
    setEditSequence(next.sequence);
    clearSelection();
  }, [annotations, editSequence, clearSelection]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      // Don't steal keys while typing, but DO allow Space/Delete/arrows when a button
      // has focus (e.g. right after clicking Play or a tool) — Space/etc. handlers
      // below call preventDefault so the focused button isn't also triggered.
      if (target?.closest('input, textarea, select, [contenteditable="true"]')) return;
      const modKey = event.ctrlKey || event.metaKey;
      if (modKey && event.key.toLowerCase() === 'z') {
        event.preventDefault();
        if (event.shiftKey) redo();
        else undo();
        return;
      }
      if (modKey && event.key.toLowerCase() === 'y') {
        event.preventDefault();
        redo();
        return;
      }
      if (event.code === 'Space') {
        event.preventDefault();
        setPlaying((p) => !p);
        return;
      }
      if (event.key === 'Delete' || event.key === 'Backspace') {
        event.preventDefault();
        if (event.shiftKey) rippleDelete(); // close the gap
        else deleteSelected();              // leave a gap
        return;
      }
      // Cut at the playhead — S (Premiere C/B style) or Ctrl/Cmd+B.
      if ((!modKey && (event.key === 's' || event.key === 'S')) || (modKey && event.key.toLowerCase() === 'b')) {
        event.preventDefault();
        splitAtPlayhead();
        return;
      }
      if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
        event.preventDefault();
        setPlaying(false);
        const unit = (event.shiftKey ? 10 : 1) / fps;
        const direction = event.key === 'ArrowRight' ? 1 : -1;
        const nextTime = Number(clamp(currentTime + direction * unit, 0, timelineDuration || duration || 0).toFixed(3));
        seekTimeline(nextTime);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [currentTime, deleteSelected, duration, fps, redo, rippleDelete, seekTimeline, splitAtPlayhead, timelineDuration, undo]);

  const handlePointerDown = useCallback(
    (event: React.PointerEvent) => {
      if (event.target === event.currentTarget) clearSelection();
      const point = getPoint(event);
      if (!point) return;
      setIsPointerDown(true);
      if (tool === 'select') return;
      // Starting a new drawing clears any in-progress draft/pending immediately (on the FIRST
      // click), so the old rectangle disappears the moment you start redrawing — not on release.
      setDraftRect(null);
      setDraftPath(null);
      setPendingAnnotation(null);
      setTypePicker(null);
      if (tool === 'rect') {
        setDraftRect({ start: point, end: point });
      } else if (tool === 'freehand') {
        setDraftPath([point]);
      } else if (tool === 'marker') {
        // A marker is a point note → always a "ダンに指示" pin (no type choice needed).
        commitAnnotation({ kind: 'marker', label: 'comment', data: { point } }, 'comment');
      }
    },
    [clearSelection, commitAnnotation, getPoint, tool]
  );

  const handlePointerMove = useCallback(
    (event: React.PointerEvent) => {
      if (!isPointerDown) return;
      const point = getPoint(event);
      if (!point) return;
      if (draftRect) setDraftRect({ ...draftRect, end: point });
      if (draftPath) setDraftPath((prev) => (prev ? [...prev, point] : [point]));
    },
    [draftPath, draftRect, getPoint, isPointerDown]
  );

  const handlePointerUp = useCallback(() => {
    setIsPointerDown(false);
    // On release we DON'T commit — we open a type picker at the shape so the user chooses
    // ぼかし / 生成 / ダンに指示. Drawing a shape no longer implies "ぼかし".
    if (draftRect) {
      const x = Math.min(draftRect.start.x, draftRect.end.x);
      const y = Math.min(draftRect.start.y, draftRect.end.y);
      const width = Math.abs(draftRect.end.x - draftRect.start.x);
      const height = Math.abs(draftRect.end.y - draftRect.start.y);
      if (width > 0.008 && height > 0.008) {
        setTypePicker({ kind: 'rect', data: { x, y, width, height }, cx: x + width / 2, cy: y + height / 2 });
      }
      setDraftRect(null);
    }
    if (draftPath) {
      if (draftPath.length > 1) {
        const xs = draftPath.map((p) => p.x);
        const ys = draftPath.map((p) => p.y);
        const cx = (Math.min(...xs) + Math.max(...xs)) / 2;
        const cy = (Math.min(...ys) + Math.max(...ys)) / 2;
        setTypePicker({ kind: 'freehand', data: { points: draftPath }, cx, cy });
      }
      setDraftPath(null);
    }
  }, [draftPath, draftRect]);

  const rectStyle = (data: Record<string, unknown>) => {
    const x = Number(data.x || 0);
    const y = Number(data.y || 0);
    const width = Number(data.width || 0);
    const height = Number(data.height || 0);
    return {
      left: `${x * 100}%`,
      top: `${y * 100}%`,
      width: `${width * 100}%`,
      height: `${height * 100}%`,
    };
  };

  const draftRectStyle = draftRect
    ? {
        left: `${Math.min(draftRect.start.x, draftRect.end.x) * 100}%`,
        top: `${Math.min(draftRect.start.y, draftRect.end.y) * 100}%`,
        width: `${Math.abs(draftRect.end.x - draftRect.start.x) * 100}%`,
        height: `${Math.abs(draftRect.end.y - draftRect.start.y) * 100}%`,
      }
    : null;

  const timelineTrackStyle = useMemo(
    () => ({
      width: `${timelineZoom * 100}%`,
      minWidth: '100%',
    }),
    [timelineZoom]
  );

  const getTimelineTime = useCallback(
    (event: React.PointerEvent | PointerEvent): number => {
      const rect = timelineRef.current?.getBoundingClientRect();
      if (!rect || !timelineDuration) return 0;
      const ratio = (event.clientX - rect.left) / rect.width;
      return Number(clamp(ratio * timelineDuration, 0, timelineDuration).toFixed(2));
    },
    [timelineDuration]
  );

  const updateAnnotationTime = useCallback(
    (id: string, start: number, end: number, layer?: number) => {
      const maxDuration = duration || Math.max(end, start + 0.1);
      const nextStart = Number(clamp(start, 0, maxDuration).toFixed(2));
      const nextEnd = Number(clamp(end, nextStart + 0.1, maxDuration).toFixed(2));
      setAnnotations((prev) => prev.map((a) => (a.id === id
        ? { ...a, start: nextStart, end: nextEnd, ...(typeof layer === 'number' ? { data: { ...(a.data as object), layer } } : {}) }
        : a)));
    },
    [duration]
  );

  useEffect(() => {
    if (!timelineDrag) return;
    const moveDrag = (event: PointerEvent) => {
      if (!timelineDuration) return;
      const rect = timelineRef.current?.getBoundingClientRect();
      if (!rect) return;
      const delta = ((event.clientX - timelineDrag.startClientX) / rect.width) * timelineDuration;
      const length = Math.max(0.1, timelineDrag.originalEnd - timelineDrag.originalStart);
      if (timelineDrag.mode === 'move') {
        const nextStart = clamp(timelineDrag.originalStart + delta, 0, Math.max(0, timelineDuration - length));
        // Vertical: dragging into another lane (same zone) changes the annotation's layer = up/down
        // lane move, like sequence clips. Frozen geometry + 8px deadband keep it from oscillating.
        let layer: number | undefined;
        const ann = annotations.find((a) => a.id === timelineDrag.id);
        if (ann) {
          const zone = trackForIntent(ann.intent);
          const yWithin = event.clientY - rect.top;
          const geom = dragLaneGeomRef.current || laneGeomRef.current;
          const cand = geom.find((g) => g.zone === zone && yWithin >= g.top + 8 && yWithin < g.bottom - 8);
          if (cand) layer = cand.layer;
        }
        updateAnnotationTime(timelineDrag.id, nextStart, nextStart + length, layer);
      } else if (timelineDrag.mode === 'start') {
        updateAnnotationTime(timelineDrag.id, timelineDrag.originalStart + delta, timelineDrag.originalEnd);
      } else {
        updateAnnotationTime(timelineDrag.id, timelineDrag.originalStart, timelineDrag.originalEnd + delta);
      }
    };
    const clearDrag = () => { setTimelineDrag(null); dragLaneGeomRef.current = null; };
    window.addEventListener('pointermove', moveDrag);
    window.addEventListener('pointerup', clearDrag);
    window.addEventListener('pointercancel', clearDrag);
    return () => {
      window.removeEventListener('pointermove', moveDrag);
      window.removeEventListener('pointerup', clearDrag);
      window.removeEventListener('pointercancel', clearDrag);
    };
  }, [timelineDuration, timelineDrag, updateAnnotationTime, annotations]);

  useEffect(() => {
    if (!pendingTimelineDrag || !pendingAnnotation) return;
    const moveDrag = (event: PointerEvent) => {
      if (!timelineDuration) return;
      const rect = timelineRef.current?.getBoundingClientRect();
      if (!rect) return;
      const delta = ((event.clientX - pendingTimelineDrag.startClientX) / rect.width) * timelineDuration;
      const length = Math.max(0.1, pendingTimelineDrag.originalEnd - pendingTimelineDrag.originalStart);
      if (pendingTimelineDrag.mode === 'move') {
        const nextStart = clamp(pendingTimelineDrag.originalStart + delta, 0, Math.max(0, timelineDuration - length));
        updatePendingTime(nextStart, nextStart + length);
      } else if (pendingTimelineDrag.mode === 'start') {
        updatePendingTime(pendingTimelineDrag.originalStart + delta, pendingTimelineDrag.originalEnd);
      } else {
        updatePendingTime(pendingTimelineDrag.originalStart, pendingTimelineDrag.originalEnd + delta);
      }
    };
    const clearDrag = () => setPendingTimelineDrag(null);
    window.addEventListener('pointermove', moveDrag);
    window.addEventListener('pointerup', clearDrag);
    window.addEventListener('pointercancel', clearDrag);
    return () => {
      window.removeEventListener('pointermove', moveDrag);
      window.removeEventListener('pointerup', clearDrag);
      window.removeEventListener('pointercancel', clearDrag);
    };
  }, [pendingAnnotation, pendingTimelineDrag, timelineDuration, updatePendingTime]);

  useEffect(() => {
    if (!isTimelineScrubbing) return;
    const moveScrub = (event: PointerEvent) => {
      const nextTime = getTimelineTime(event);
      seekTimeline(nextTime);
    };
    const stopScrub = () => setIsTimelineScrubbing(false);
    window.addEventListener('pointermove', moveScrub);
    window.addEventListener('pointerup', stopScrub);
    window.addEventListener('pointercancel', stopScrub);
    return () => {
      window.removeEventListener('pointermove', moveScrub);
      window.removeEventListener('pointerup', stopScrub);
      window.removeEventListener('pointercancel', stopScrub);
    };
  }, [getTimelineTime, isTimelineScrubbing, seekTimeline]);

  const handleTimelinePointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (event.button !== 0) return; // right-drag is rubber-band select, not scrub
      event.preventDefault();
      clearSelection();
      const nextTime = getTimelineTime(event);
      seekTimeline(nextTime);
      setIsTimelineScrubbing(true);
    },
    [clearSelection, getTimelineTime, seekTimeline]
  );

  const handleTimelineWheel = useCallback((event: React.WheelEvent<HTMLDivElement>) => {
    if (!event.shiftKey) return;
    event.preventDefault();
    const direction = event.deltaY > 0 ? -1 : 1;
    setTimelineZoom((value) => Number(clamp(value + direction * 0.2, 1, 8).toFixed(2)));
    window.requestAnimationFrame(() => {
      const scroller = timelineScrollRef.current;
      const track = timelineRef.current;
      if (!scroller || !track || !timelineDuration) return;
      const redlineX = (currentTime / timelineDuration) * track.offsetWidth;
      scroller.scrollLeft = track.offsetLeft + redlineX - scroller.clientWidth / 2;
    });
  }, [currentTime, timelineDuration]);

  useEffect(() => {
    const scroller = timelineScrollRef.current;
    const track = timelineRef.current;
    if (!scroller || !track || !timelineDuration) return;
    const redlineX = (currentTime / timelineDuration) * track.offsetWidth;
    scroller.scrollLeft = track.offsetLeft + redlineX - scroller.clientWidth / 2;
  }, [currentTime, timelineDuration, timelineZoom]);

  const startTimelineDrag = useCallback(
    (event: React.PointerEvent, annotation: ReviewAnnotation, mode: TimelineDrag['mode']) => {
      event.preventDefault();
      event.stopPropagation();
      selectAnnotation(annotation.id, event.shiftKey || event.ctrlKey || event.metaKey);
      // Freeze lane geometry for stable vertical hit-testing (no reflow oscillation while dragging).
      dragLaneGeomRef.current = laneGeomRef.current.map((g) => ({ ...g }));
      setTimelineDrag({
        id: annotation.id,
        mode,
        startClientX: event.clientX,
        originalStart: annotation.start,
        originalEnd: annotation.end ?? annotation.start + 0.5,
      });
      try {
        (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
      } catch {
        /* ignore */
      }
    },
    [selectAnnotation]
  );

  const startPendingTimelineDrag = useCallback(
    (event: React.PointerEvent, mode: PendingTimelineDrag['mode']) => {
      if (!pendingAnnotation) return;
      event.preventDefault();
      event.stopPropagation();
      setPendingTimelineDrag({
        mode,
        startClientX: event.clientX,
        originalStart: pendingAnnotation.start,
        originalEnd: pendingAnnotation.end ?? pendingAnnotation.start + 0.5,
      });
      try {
        (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
      } catch {
        /* ignore */
      }
    },
    [pendingAnnotation]
  );

  const updateSequenceClips = useCallback((clipIds: Set<string>, patch: Partial<SequenceClip>) => {
    if (clipIds.size === 0) return;
    setEditSequence((current) => {
      if (!current) return current;
      const tracks = (current.tracks || []).map((track) => ({
        ...track,
        clips: (track.clips || []).map((clip) => (clipIds.has(String(clip.id)) ? { ...clip, ...patch } : clip)),
      }));
      const nextDuration = Math.max(0, ...tracks.flatMap((track) => (track.clips || []).map((clip) => clip.timeline_end || 0)));
      return { ...current, duration: Number(nextDuration.toFixed(3)), tracks };
    });
  }, []);

  const updateSequenceClip = useCallback((clipId: string, patch: Partial<SequenceClip>) => {
    updateSequenceClips(new Set([clipId]), patch);
  }, [updateSequenceClips]);

  // Edits from the side panel apply to ALL selected clips (absolute values), so resize /
  // crop / position / volume can be set on many clips at once.
  const updateSelectedSequenceClip = useCallback((patch: Partial<SequenceClip>) => {
    const ids = new Set(selectedSequenceClipIds.length > 0 ? selectedSequenceClipIds : selectedSequenceClipId ? [selectedSequenceClipId] : []);
    updateSequenceClips(ids, patch);
  }, [selectedSequenceClipId, selectedSequenceClipIds, updateSequenceClips]);

  // Speech-following captions (karaoke / typewriter) auto-sync to the actual voice — no manual
  // step. Whenever such a caption lacks up-to-date per-word timings for its current position, we
  // derive them once (debounced). Keyed by id+span+animation so a moved or re-styled caption
  // re-syncs but it never loops (the words we write don't change the key).
  const autoSyncSigRef = useRef<Map<string, string>>(new Map());
  useEffect(() => {
    if (!onSyncCaptionAudio) return;
    const need = allSequenceClips
      .filter((c) => {
        if (c.track !== 'caption' && typeof c.text !== 'string') return false;
        const anim = (c.style as CaptionDesign | null | undefined)?.animation;
        if (anim !== 'karaoke' && anim !== 'typewriter') return false;
        const sig = `${c.timeline_start}|${c.timeline_end}|${anim}`;
        return autoSyncSigRef.current.get(String(c.id)) !== sig;
      })
      .map((c) => String(c.id));
    if (!need.length) return;
    const timer = window.setTimeout(async () => {
      const byId = new Map(allSequenceClips.map((c) => [String(c.id), c]));
      need.forEach((id) => {
        const c = byId.get(id);
        if (!c) return;
        const anim = (c.style as CaptionDesign | null | undefined)?.animation;
        autoSyncSigRef.current.set(id, `${c.timeline_start}|${c.timeline_end}|${anim}`);
      });
      try {
        const map = await onSyncCaptionAudio(need);
        Object.entries(map).forEach(([cid, words]) => {
          updateSequenceClips(new Set([cid]), { words: words && words.length ? words : null });
        });
      } catch {
        need.forEach((id) => autoSyncSigRef.current.delete(id)); // allow a retry on the next change
      }
    }, 700);
    return () => window.clearTimeout(timer);
  }, [allSequenceClips, onSyncCaptionAudio, updateSequenceClips]);

  // Insert a new clip from a dragged source asset at the drop time/lane. Video assets only for
  // now (the dominant case; the material list is video-content). The video lands on the 'video'
  // track at the dropped lane's layer (0 = fullscreen, higher = overlay/PiP) and its AUDIO lands
  // on the 'audio' track, A/V-linked (shared link_id) so they move/trim/delete together. The
  // clip spans the asset's FULL length (no cap) from source 0, so the whole material is placed.
  const insertSequenceClip = useCallback(
    (payload: { id: string; kind?: string; duration?: number | string | null; label?: string | null }, dropTime: number, zone: 'visual' | 'audio', layer: number) => {
      if (zone !== 'visual' || payload.kind !== 'video') return; // video onto a visual lane
      const rawLen = Number(payload.duration);
      const len = Number.isFinite(rawLen) && rawLen > 0 ? rawLen : DROP_DEFAULT_LEN;
      const start = Math.max(0, Number(dropTime) || 0);
      const ts = Number(start.toFixed(2)), te = Number((start + len).toFixed(2)), se = Number(len.toFixed(2));
      const linkId = `lk_${makeId()}`;
      const videoId = `clip_${makeId()}`;
      const videoClip: SequenceClip = {
        id: videoId, asset_id: payload.id, label: payload.label || '素材',
        source_start: 0, source_end: se, timeline_start: ts, timeline_end: te,
        track: 'video', layer, composition: layer > 0 ? 'overlay' : 'fullscreen', link_id: linkId,
      };
      const audioClip: SequenceClip = {
        id: `clip_${makeId()}`, asset_id: payload.id, label: payload.label || '素材',
        source_start: 0, source_end: se, timeline_start: ts, timeline_end: te,
        track: 'audio', layer: 0, role: 'dialogue', link_id: linkId,
      };
      setEditSequence((current) => {
        const base = current || { tracks: [] };
        const tracks = (base.tracks || []).map((t) => ({ ...t, clips: [...(t.clips || [])] }));
        let vt = tracks.find((t) => t.type === 'video');
        if (!vt) { vt = { id: `tk_${makeId()}`, type: 'video', clips: [] }; tracks.push(vt); }
        vt.clips = [...(vt.clips || []), videoClip];
        let at = tracks.find((t) => t.type === 'audio');
        if (!at) { at = { id: `tk_${makeId()}`, type: 'audio', clips: [] }; tracks.push(at); }
        at.clips = [...(at.clips || []), audioClip];
        const nextDuration = Math.max(0, ...tracks.flatMap((t) => (t.clips || []).map((c) => c.timeline_end || 0)));
        return { ...base, tracks, duration: Number(nextDuration.toFixed(3)) };
      });
      selectSequenceClip(videoId);
    },
    [selectSequenceClip]
  );

  // While a material is dragged over the timeline, show a live ghost of where it will land
  // (and how long it is) so it's visually clear it entered — even before the button is
  // released. The drag payload isn't readable during dragover (HTML5), so the source side
  // stashes the asset on window at dragstart; we read its duration for the ghost width.
  const dropTimeFromEvent = useCallback((clientX: number) => {
    const rect = timelineRef.current?.getBoundingClientRect();
    if (!rect || !timelineDuration) return null;
    const frac = (clientX - rect.left) / rect.width;
    return clamp(frac * timelineDuration, 0, timelineDuration);
  }, [timelineDuration]);

  const handleLaneDragOver = useCallback((event: React.DragEvent, lane: TimelineLane) => {
    if (!Array.from(event.dataTransfer.types).includes(ASSET_DND_TYPE)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = 'copy';
    if (lane.zone !== 'visual') { setDropPreview(null); return; } // video lands on a visual lane
    const start = dropTimeFromEvent(event.clientX);
    if (start === null) return;
    const dragged = (typeof window !== 'undefined' ? (window as unknown as { __danDragAsset?: { duration?: number | string | null } }).__danDragAsset : null) || null;
    const rawLen = Number(dragged?.duration);
    const len = Number.isFinite(rawLen) && rawLen > 0 ? rawLen : DROP_DEFAULT_LEN;
    setDropPreview({ zone: lane.zone, layer: lane.layer, start, len });
  }, [dropTimeFromEvent]);

  const handleLaneDrop = useCallback(
    (event: React.DragEvent, lane: TimelineLane) => {
      setDropPreview(null);
      const raw = event.dataTransfer.getData(ASSET_DND_TYPE);
      if (!raw) return;
      event.preventDefault();
      let payload: { id: string; kind?: string; duration?: number | string | null; label?: string | null };
      try { payload = JSON.parse(raw); } catch { return; }
      const dropTime = dropTimeFromEvent(event.clientX);
      if (dropTime === null) return;
      insertSequenceClip(payload, dropTime, lane.zone, lane.layer);
    },
    [insertSequenceClip, dropTimeFromEvent]
  );

  // DaVinci/Premiere-style overwrite: place the dragged clip at its new range and trim,
  // delete, or split any same-lane (same-track+layer) neighbour it now overlaps. With A/V
  // link on, the dragged clip's linked partner (same link_id) gets the SAME shift and
  // overwrites its own lane too. Computed from the drag-start snapshot (non-cumulative).
  // Shared commit for any set of "moved" clips (single drag or multi-clip block): place each
  // moved clip at its new fields and overwrite same-lane (track+layer) NON-moved neighbours it
  // now overlaps — trim the overhang, delete if fully covered, or split if covered in the
  // middle (DaVinci/Premiere overwrite). The overlap-aware target lookup lets several moved
  // clips on one lane each overwrite their own neighbour.
  const commitMovedSet = useCallback((snap: EditSequence, moved: Map<string, Partial<SequenceClip>>) => {
    const r = (v: number) => Number(v.toFixed(2));
    const allOrig = (snap.tracks || []).flatMap((t) => (t.clips || []).map((c) => ({ ...c, track: c.track || t.type })));
    const targets = Array.from(moved.entries()).map(([id, f]) => {
      const o = allOrig.find((c) => c.id === id)!;
      return {
        id,
        lane: `${o.track || ''}#${f.layer ?? o.layer ?? 0}`,
        as: Number(f.timeline_start ?? o.timeline_start),
        ae: Number(f.timeline_end ?? o.timeline_end),
      };
    });
    const tracks = (snap.tracks || []).map((track) => {
      const out: SequenceClip[] = [];
      for (const c of track.clips || []) {
        const mv = moved.get(c.id);
        if (mv) { out.push({ ...c, ...mv }); continue; }
        const lane = `${c.track || track.type || ''}#${c.layer ?? 0}`;
        const t = targets.find((x) => x.lane === lane && x.id !== c.id && x.ae > c.timeline_start + 0.001 && x.as < c.timeline_end - 0.001);
        if (!t) { out.push(c); continue; } // not overlapped by any moved clip on this lane
        const bs = c.timeline_start, be = c.timeline_end;
        const isAV = Number.isFinite(c.source_end as number);
        if (t.as <= bs + 0.001 && t.ae >= be - 0.001) continue; // fully covered -> delete
        if (t.as <= bs + 0.001) {
          const d = t.ae - bs;
          out.push({ ...c, timeline_start: r(t.ae), ...(isAV ? { source_start: r(Number(c.source_start || 0) + d) } : {}) });
        } else if (t.ae >= be - 0.001) {
          const d = be - t.as;
          out.push({ ...c, timeline_end: r(t.as), ...(isAV ? { source_end: r(Number(c.source_end || 0) - d) } : {}) });
        } else {
          const dl = t.as - bs, dr = t.ae - bs;
          out.push({ ...c, timeline_end: r(t.as), ...(isAV ? { source_end: r(Number(c.source_start || 0) + dl) } : {}) });
          out.push({ ...c, id: `${c.id}__r`, timeline_start: r(t.ae), ...(isAV ? { source_start: r(Number(c.source_start || 0) + dr) } : {}) });
        }
      }
      return { ...track, clips: out };
    });
    const nextDuration = Math.max(0, ...tracks.flatMap((t) => (t.clips || []).map((c) => c.timeline_end || 0)));
    setEditSequence({ ...snap, duration: Number(nextDuration.toFixed(3)), tracks });
  }, []);

  const applyDragOverwrite = useCallback((draggedId: string, fields: Partial<SequenceClip>) => {
    const snap = dragSnapshotRef.current;
    if (!snap) return;
    const allOrig = (snap.tracks || []).flatMap((t) => (t.clips || []).map((c) => ({ ...c, track: c.track || t.type })));
    const original = allOrig.find((c) => c.id === draggedId);
    if (!original) return;
    const r = (v: number) => Number(v.toFixed(2));

    // Build the set of clips being moved (dragged + its linked partner) with their new fields.
    const moved = new Map<string, Partial<SequenceClip>>();
    moved.set(draggedId, fields);
    const partner = linkAV && original.link_id
      ? allOrig.find((c) => c.id !== draggedId && c.link_id === original.link_id)
      : null;
    if (partner) {
      // Mirror the drag to the linked partner. CRITICAL: only shift the partner's SOURCE when
      // the dragged clip's source is also changing (a trim of the start/end handle). On a pure
      // MOVE (timeline shifts, source stays) the partner's source must NOT shift — otherwise
      // its timeline and source move by the same delta and cancel out, so the audio looks moved
      // but plays the exact same content at the same instant (the "voice doesn't follow" bug).
      const dStart = Number(fields.timeline_start ?? original.timeline_start) - original.timeline_start;
      const dEnd = Number(fields.timeline_end ?? original.timeline_end) - original.timeline_end;
      const pf: Partial<SequenceClip> = {};
      if (fields.timeline_start !== undefined) {
        pf.timeline_start = r(partner.timeline_start + dStart);
        if (fields.source_start !== undefined && Number.isFinite(partner.source_start as number)) {
          pf.source_start = r(Number(partner.source_start || 0) + dStart);
        }
      }
      if (fields.timeline_end !== undefined) {
        pf.timeline_end = r(partner.timeline_end + dEnd);
        if (fields.source_end !== undefined && Number.isFinite(partner.source_end as number)) {
          pf.source_end = r(Number(partner.source_end || 0) + dEnd);
        }
      }
      // Collision avoidance: the partner follows the drag automatically (you didn't grab it), so
      // it must NOT delete other clips it lands on. If its new range overlaps a clip on its lane,
      // bump it down to the first free lane (auto-created — a clip on a new layer makes its lane).
      const pStart = Number(pf.timeline_start ?? partner.timeline_start);
      const pEnd = Number(pf.timeline_end ?? partner.timeline_end);
      const pTrack = partner.track || '';
      const overlapsAt = (L: number) => allOrig.some((c) =>
        c.id !== partner.id && !moved.has(c.id) && (c.track || '') === pTrack && (c.layer ?? 0) === L &&
        pEnd > c.timeline_start + 0.001 && pStart < c.timeline_end - 0.001);
      let pLayer = partner.layer ?? 0;
      let guard = 0;
      while (overlapsAt(pLayer) && guard++ < 50) pLayer += 1;
      if (pLayer !== (partner.layer ?? 0)) pf.layer = pLayer;
      moved.set(partner.id, pf);
    }
    commitMovedSet(snap, moved);
  }, [linkAV, commitMovedSet]);

  // Block move: shift every selected clip (+ A/V-link partners) by the SAME timeline delta,
  // preserving their relative spacing and source ranges (a move, not a trim). Non-moved
  // neighbours the block now overlaps get trimmed/deleted/split just like a single-clip move.
  // Computed from the drag-start snapshot (non-cumulative); clamped so the earliest clip
  // never crosses 0.
  const applyBlockMove = useCallback((delta: number, ids: string[]) => {
    const snap = dragSnapshotRef.current;
    if (!snap) return;
    const r = (v: number) => Number(v.toFixed(2));
    const allOrig = (snap.tracks || []).flatMap((t) => t.clips || []);
    const set = new Set(ids);
    if (linkAV) {
      const linkIds = new Set(allOrig.filter((c) => set.has(c.id) && c.link_id).map((c) => c.link_id));
      allOrig.forEach((c) => { if (c.link_id && linkIds.has(c.link_id)) set.add(c.id); });
    }
    const inSet = allOrig.filter((c) => set.has(c.id));
    if (inSet.length === 0) return;
    const minStart = Math.min(...inSet.map((c) => c.timeline_start));
    const eff = Math.max(delta, -minStart); // keep the block at/after t=0
    const moved = new Map<string, Partial<SequenceClip>>();
    for (const c of inSet) moved.set(c.id, { timeline_start: r(c.timeline_start + eff), timeline_end: r(c.timeline_end + eff) });
    commitMovedSet(snap, moved);
  }, [linkAV, commitMovedSet]);

  const startSequenceClipDrag = useCallback(
    (event: React.PointerEvent, clip: SequenceClip, mode: SequenceClipDrag['mode']) => {
      if (event.button !== 0) return; // let right-drag fall through to rubber-band select
      event.preventDefault();
      event.stopPropagation();
      // If the grabbed clip is already part of a multi-selection, keep the whole selection and
      // move it as a block. Otherwise (re)select just this clip (shift/ctrl toggles into a set).
      const additive = event.shiftKey || event.ctrlKey || event.metaKey;
      const inMulti = !additive && selectedSequenceClipIds.length > 1 && selectedSequenceClipIds.includes(clip.id);
      if (!inMulti) selectSequenceClip(clip.id, additive);
      dragSelectionRef.current = inMulti ? [...selectedSequenceClipIds] : [clip.id];
      dragLayerRef.current = clip.layer ?? clipDefaultLayer(clip);
      dragLaneGeomRef.current = laneGeomRef.current.map((g) => ({ ...g })); // freeze for stable hit-testing
      seekTimeline(getTimelineTime(event));
      dragSnapshotRef.current = editSequence;
      setSequenceClipDrag({
        id: clip.id,
        mode,
        startClientX: event.clientX,
        startClientY: event.clientY,
        // Zone is the clip's TRACK only — NOT its role. dan_plan video clips carry a role too,
        // and keying off role wrongly put video clips in the audio zone, so the lane hit-test
        // never matched the visual lanes and video clips couldn't move up/down at all.
        zone: clip.track === 'audio' ? 'audio' : 'visual',
        originalLayer: clip.layer ?? clipDefaultLayer(clip),
        originalTimelineStart: clip.timeline_start,
        originalTimelineEnd: clip.timeline_end,
        originalSourceStart: Number(clip.source_start || 0),
        originalSourceEnd: Number(clip.source_end || 0),
      });
      // pointer capture is best-effort; the window pointermove/up listeners drive
      // the drag regardless, so a throw here must not abort starting the drag.
      try {
        (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
      } catch {
        /* ignore */
      }
    },
    [editSequence, getTimelineTime, seekTimeline, selectSequenceClip, selectedSequenceClipIds]
  );

  useEffect(() => {
    if (!sequenceClipDrag || !timelineDuration) return;
    const moveDrag = (event: PointerEvent) => {
      const rect = timelineRef.current?.getBoundingClientRect();
      if (!rect) return;
      const delta = ((event.clientX - sequenceClipDrag.startClientX) / rect.width) * timelineDuration;
      const clip = allSequenceClips.find((item) => item.id === sequenceClipDrag.id);
      if (!clip) return;
      const isVideoClip = clip.track === 'video' || Number.isFinite(clip.source_end);
      const sourceDuration = clip.source_duration || Math.max(Number(clip.source_end || 0), sequenceClipDrag.originalSourceEnd);
      // The dragged clip moves/resizes freely; applyDragOverwrite then trims, deletes, or
      // splits any same-lane neighbour it now overlaps (DaVinci/Premiere overwrite).
      if (sequenceClipDrag.mode === 'start') {
        const nextTimelineStart = clamp(sequenceClipDrag.originalTimelineStart + delta, 0, sequenceClipDrag.originalTimelineEnd - 0.1);
        const fields: Partial<SequenceClip> = { timeline_start: Number(nextTimelineStart.toFixed(2)) };
        if (isVideoClip) {
          fields.source_start = Number(clamp(sequenceClipDrag.originalSourceStart + delta, 0, sequenceClipDrag.originalSourceEnd - 0.1).toFixed(2));
        }
        applyDragOverwrite(sequenceClipDrag.id, fields);
      } else if (sequenceClipDrag.mode === 'end') {
        const nextTimelineEnd = clamp(sequenceClipDrag.originalTimelineEnd + delta, sequenceClipDrag.originalTimelineStart + 0.1, timelineDuration);
        const fields: Partial<SequenceClip> = { timeline_end: Number(nextTimelineEnd.toFixed(2)) };
        if (isVideoClip) {
          fields.source_end = Number(clamp(sequenceClipDrag.originalSourceEnd + delta, sequenceClipDrag.originalSourceStart + 0.1, sourceDuration).toFixed(2));
        }
        applyDragOverwrite(sequenceClipDrag.id, fields);
      } else if (dragSelectionRef.current.length > 1) {
        // Block move: shift the whole selection together (no lane change, no overwrite).
        applyBlockMove(delta, dragSelectionRef.current);
      } else {
        const length = sequenceClipDrag.originalTimelineEnd - sequenceClipDrag.originalTimelineStart;
        const nextStart = clamp(sequenceClipDrag.originalTimelineStart + delta, 0, Math.max(0, timelineDuration - length));
        const fields: Partial<SequenceClip> = {
          timeline_start: Number(nextStart.toFixed(2)),
          timeline_end: Number((nextStart + length).toFixed(2)),
        };
        // Vertical: dropping onto another lane in the same zone changes the clip's layer.
        // Hysteresis — only switch when the cursor is well INSIDE another lane (a deadband
        // around each border), so jitter near a boundary doesn't flip the lane back and forth
        // (which would also reflow the lanes and fight the cursor).
        const yWithin = event.clientY - rect.top;
        const MARGIN = 8;
        const geom = dragLaneGeomRef.current || laneGeomRef.current; // frozen geometry
        const cand = geom.find(
          (g) => g.zone === sequenceClipDrag.zone && yWithin >= g.top + MARGIN && yWithin < g.bottom - MARGIN
        );
        if (cand) dragLayerRef.current = cand.layer;
        // ALWAYS carry the committed layer: applyDragOverwrite rebuilds the clip from the
        // drag-start snapshot, so omitting it (when the live layer already matches) would let
        // the overwrite revert the clip to its original layer — that was the frame-by-frame
        // lane oscillation. The frozen geometry + hysteresis keep the committed layer stable.
        if (dragLayerRef.current !== null) fields.layer = dragLayerRef.current;
        applyDragOverwrite(sequenceClipDrag.id, fields);
      }
    };
    const clearDrag = () => {
      setSequenceClipDrag(null);
      dragSnapshotRef.current = null;
      dragSelectionRef.current = [];
      dragLayerRef.current = null;
      dragLaneGeomRef.current = null;
    };
    window.addEventListener('pointermove', moveDrag);
    window.addEventListener('pointerup', clearDrag);
    window.addEventListener('pointercancel', clearDrag);
    return () => {
      window.removeEventListener('pointermove', moveDrag);
      window.removeEventListener('pointerup', clearDrag);
      window.removeEventListener('pointercancel', clearDrag);
    };
  }, [allSequenceClips, sequenceClipDrag, timelineDuration, applyDragOverwrite, applyBlockMove]);

  // Rubber-band (marquee) select: while a right-drag is active, draw the rectangle and on
  // release select every clip bar (data-clip-id) whose on-screen box intersects it. A tiny
  // drag (< 5px) is treated as a no-op so a plain right-click doesn't change the selection.
  // Clear the drag ghost when the drag operation ends anywhere (drop, cancel, or leaving).
  useEffect(() => {
    const clear = () => setDropPreview(null);
    window.addEventListener('dragend', clear);
    window.addEventListener('drop', clear);
    return () => {
      window.removeEventListener('dragend', clear);
      window.removeEventListener('drop', clear);
    };
  }, []);

  const marqueeActive = marquee !== null;
  useEffect(() => {
    if (!marqueeActive) return;
    const move = (event: PointerEvent) => {
      setMarquee((m) => (m ? { ...m, x1: event.clientX, y1: event.clientY } : m));
    };
    const up = (event: PointerEvent) => {
      const start = marqueeStartRef.current;
      marqueeStartRef.current = null;
      setMarquee(null);
      if (!start) return;
      const left = Math.min(start.x, event.clientX), right = Math.max(start.x, event.clientX);
      const top = Math.min(start.y, event.clientY), bottom = Math.max(start.y, event.clientY);
      if (right - left < 5 && bottom - top < 5) return; // plain right-click, not a drag
      const intersects = (el: Element) => {
        const r = el.getBoundingClientRect();
        return r.right >= left && r.left <= right && r.bottom >= top && r.top <= bottom;
      };
      const clipIds: string[] = [];
      const annIds: string[] = [];
      // Marquee selects EVERY clip kind it covers — sequence clips AND annotation/blur clips.
      document.querySelectorAll('[data-clip-id]').forEach((el) => {
        if (intersects(el)) { const id = el.getAttribute('data-clip-id'); if (id) clipIds.push(id); }
      });
      document.querySelectorAll('[data-annotation-id]').forEach((el) => {
        if (intersects(el)) { const id = el.getAttribute('data-annotation-id'); if (id) annIds.push(id); }
      });
      if (clipIds.length > 0 || annIds.length > 0) {
        setSelectedSequenceClipIds(clipIds);
        setSelectedSequenceClipId(clipIds.length ? clipIds[clipIds.length - 1] : null);
        setSelectedIds(annIds);
        setSelectedId(annIds.length ? annIds[annIds.length - 1] : null);
      }
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
    window.addEventListener('pointercancel', up);
    return () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      window.removeEventListener('pointercancel', up);
    };
  }, [marqueeActive]);

  return (
    <div className={`flex h-full bg-background text-foreground ${embedded ? 'min-h-0' : 'min-h-screen'}`}>
      {marquee ? (
        <div
          className="pointer-events-none fixed z-50 border border-sky-400 bg-sky-400/15"
          style={{
            left: Math.min(marquee.x0, marquee.x1),
            top: Math.min(marquee.y0, marquee.y1),
            width: Math.abs(marquee.x1 - marquee.x0),
            height: Math.abs(marquee.y1 - marquee.y0),
          }}
        />
      ) : null}
      <main className="flex min-w-0 flex-1 flex-col">
        <div className="flex shrink-0 items-center gap-2 border-b border-border px-4 py-3">
          {onBack ? (
            <Button variant="ghost" size="sm" onClick={onBack}>
              <ArrowLeft className="h-4 w-4" />
            </Button>
          ) : null}
          <div className="min-w-0 flex-1">
            <div className="text-sm font-semibold">Dan Review Editor</div>
            <div className="truncate text-xs text-muted-foreground">{videoPath || videoUrl || 'No video selected'}</div>
          </div>
          <Button variant="ghost" size="sm" onClick={undo} title="元に戻す (Ctrl+Z)">
            <Undo2 className="h-4 w-4" />
          </Button>
          <Button variant="ghost" size="sm" onClick={redo} title="やり直す (Ctrl+Shift+Z)">
            <Redo2 className="h-4 w-4" />
          </Button>
          <Button variant="outline" size="sm" onClick={() => void saveSession()} disabled={isSaving}>
            <Save className="mr-1 h-4 w-4" />
            Save
          </Button>
          {onExecute ? (
            <Button
              size="sm"
              disabled={isSaving}
              title="今のタイムラインをMP4に書き出します（投稿・共有用）"
              onClick={async () => {
                await saveSession();
                await onExecute(payload);
              }}
            >
              MP4で書き出す
            </Button>
          ) : null}
        </div>

        <div className="flex flex-1 overflow-hidden">
          <div className="flex min-w-0 flex-1 flex-col bg-neutral-950">
            <div className="flex min-h-0 flex-1 items-center justify-center p-4">
              <div
                ref={stageRef}
                className="relative h-full max-h-full max-w-full overflow-hidden bg-black"
                style={{ aspectRatio: previewAspect }}
              >
                <TimelinePreview
                  sequence={editSequence}
                  assets={sequenceAssets || []}
                  blurRegions={activeBlurRegions}
                  currentTime={currentTime}
                  playing={playing}
                  format={editSequence?.format || initialSequence?.format || '9:16'}
                  onTimeChange={handlePreviewTime}
                  onEnded={handlePreviewEnded}
                  className="h-full w-full"
                  selectedClipId={selectedSequenceClipId}
                  onPositionChange={(clipId, position) => updateSequenceClip(clipId, { position })}
                  onTransformChange={(clipId, transform) => updateSequenceClip(clipId, { transform })}
                />

                <div
                  className={`absolute ${tool === 'select' ? 'pointer-events-none' : 'pointer-events-auto'}`}
                  style={videoContentStyle}
                  onPointerDown={handlePointerDown}
                  onPointerMove={handlePointerMove}
                  onPointerUp={handlePointerUp}
                  onPointerLeave={handlePointerUp}
                />
                <div className="pointer-events-none absolute" style={videoContentStyle}>
                  {annotations.filter(isActiveAnnotation).map((a) => {
                    if (a.kind === 'rect') {
                      // For a tracked blur, follow the analysed path (track_boxes) at the current
                      // time so the box moves with the object — real tracking, not a static box.
                      const tracked = a.intent === 'blur' && (a.data as { track?: boolean } | undefined)?.track
                        ? trackedBoxAt((a.data as { track_boxes?: Record<string, number[]> } | undefined)?.track_boxes, currentTime)
                        : null;
                      return (
                        <button
                          key={a.id}
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            selectAnnotation(a.id, e.shiftKey || e.ctrlKey || e.metaKey);
                          }}
                          className={`pointer-events-auto absolute border-2 ${
                            selectedIds.includes(a.id) ? 'border-yellow-300' : a.intent === 'blur' ? 'border-sky-300/70' : 'border-sky-400'
                          } ${a.intent === 'blur' ? '' : 'bg-red-500/15'}`}
                          style={{
                            // The blur itself is painted on the canvas (TimelinePreview blurRegions),
                            // so this is just a thin selectable outline — NO backdrop-filter (which
                            // flickered when the canvas repainted).
                            ...rectStyle(tracked || a.data),
                          }}
                          title={a.note || a.intent}
                        />
                      );
                    }
                    if (a.kind === 'marker') {
                      const p = a.data.point as Point | undefined;
                      if (!p) return null;
                      return (
                        <button
                          key={a.id}
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            selectAnnotation(a.id, e.shiftKey || e.ctrlKey || e.metaKey);
                          }}
                          className={`pointer-events-auto absolute h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 ${
                            selectedIds.includes(a.id) ? 'border-yellow-300 bg-yellow-300' : 'border-emerald-300 bg-emerald-400'
                          }`}
                          style={{ left: `${p.x * 100}%`, top: `${p.y * 100}%` }}
                          title={a.note || a.intent}
                        />
                      );
                    }
                    return null;
                  })}
                  {pendingAnnotation?.kind === 'rect' && isActiveAnnotation(pendingAnnotation) ? (
                    <div className="absolute border-2 border-orange-300 bg-orange-500/20" style={rectStyle(pendingAnnotation.data)} />
                  ) : null}
                  {pendingAnnotation?.kind === 'marker' && isActiveAnnotation(pendingAnnotation) && (pendingAnnotation.data.point as Point | undefined) ? (
                    <div
                      className="absolute h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-orange-300 bg-orange-400"
                      style={{
                        left: `${((pendingAnnotation.data.point as Point).x || 0) * 100}%`,
                        top: `${((pendingAnnotation.data.point as Point).y || 0) * 100}%`,
                      }}
                    />
                  ) : null}
                  <svg className="absolute inset-0 h-full w-full" viewBox="0 0 100 100" preserveAspectRatio="none">
                    {annotations
                      .filter((a) => a.kind === 'freehand')
                      .filter(isActiveAnnotation)
                      .map((a) => {
                        const points = (a.data.points as Point[] | undefined) || [];
                        const d = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x * 100} ${p.y * 100}`).join(' ');
                        return (
                          <path
                            key={a.id}
                            d={d}
                            fill="none"
                            stroke={selectedIds.includes(a.id) ? '#fde047' : '#38bdf8'}
                            strokeWidth="0.7"
                            vectorEffect="non-scaling-stroke"
                          />
                        );
                      })}
                    {draftPath && (
                      <path
                        d={draftPath.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x * 100} ${p.y * 100}`).join(' ')}
                        fill="none"
                        stroke="#f97316"
                        strokeWidth="0.7"
                        vectorEffect="non-scaling-stroke"
                      />
                    )}
                    {pendingAnnotation?.kind === 'freehand' && isActiveAnnotation(pendingAnnotation) && (
                      <path
                        d={((pendingAnnotation.data.points as Point[] | undefined) || []).map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x * 100} ${p.y * 100}`).join(' ')}
                        fill="none"
                        stroke="#fb923c"
                        strokeWidth="0.9"
                        vectorEffect="non-scaling-stroke"
                      />
                    )}
                    {typePicker?.kind === 'freehand' && (
                      <path
                        d={((typePicker.data.points as Point[] | undefined) || []).map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x * 100} ${p.y * 100}`).join(' ')}
                        fill="none"
                        stroke="#fb923c"
                        strokeWidth="0.9"
                        strokeDasharray="2 1.5"
                        vectorEffect="non-scaling-stroke"
                      />
                    )}
                  </svg>
                  {draftRectStyle && (
                    <div className="absolute border-2 border-orange-400 bg-orange-500/15" style={draftRectStyle} />
                  )}
                  {typePicker ? (
                    <>
                      {typePicker.kind === 'rect' ? (
                        <div className="absolute border-2 border-dashed border-orange-300 bg-orange-500/15" style={rectStyle(typePicker.data)} />
                      ) : null}
                      <div
                        className="pointer-events-auto absolute z-30 flex -translate-x-1/2 items-center gap-0.5 rounded-md border border-white/15 bg-neutral-900/95 p-1 shadow-xl"
                        style={{ left: `${clamp(typePicker.cx, 0.08, 0.92) * 100}%`, top: `${clamp(typePicker.cy, 0.04, 0.96) * 100}%` }}
                        onPointerDown={(e) => e.stopPropagation()}
                      >
                        {INTENTS.map((it) => (
                          <button
                            key={it.value}
                            type="button"
                            className="rounded px-2 py-1 text-xs font-medium text-white hover:bg-white/20"
                            onClick={() => {
                              commitAnnotation({ kind: typePicker.kind, label: it.value, data: typePicker.data }, it.value);
                              setTypePicker(null);
                            }}
                          >
                            {it.label}
                          </button>
                        ))}
                        <button type="button" className="px-1 text-white/50 hover:text-white" title="取消" onClick={() => setTypePicker(null)}>
                          ✕
                        </button>
                      </div>
                    </>
                  ) : null}
                  {/* Captions are composited by TimelinePreview onto the canvas (matches the
                      final render); no separate HTML overlay needed here. */}
                </div>
              </div>
            </div>

            <div
              className="h-1.5 shrink-0 cursor-row-resize bg-border hover:bg-primary"
              onPointerDown={(event) => {
                event.preventDefault();
                setTimelineResizeStart({ clientY: event.clientY, height: timelineHeight });
              }}
              title="ドラッグしてタイムラインの高さを調整"
            />

            <div className="shrink-0 border-t border-neutral-800 bg-background p-3" style={{ height: timelineHeight }}>
              <div className="flex items-center gap-2">
                <Button variant={tool === 'select' ? 'default' : 'outline'} size="sm" onClick={() => setTool('select')}>
                  <MousePointer2 className="h-4 w-4" />
                </Button>
                <Button variant={tool === 'rect' ? 'default' : 'outline'} size="sm" onClick={() => setTool('rect')}>
                  <Square className="h-4 w-4" />
                </Button>
                <Button variant={tool === 'freehand' ? 'default' : 'outline'} size="sm" onClick={() => setTool('freehand')}>
                  <Pencil className="h-4 w-4" />
                </Button>
                <Button variant={tool === 'marker' ? 'default' : 'outline'} size="sm" onClick={() => setTool('marker')}>
                  <MessageSquare className="h-4 w-4" />
                </Button>
                <Button
                  variant={linkAV ? 'default' : 'outline'}
                  size="sm"
                  className="ml-auto h-7 px-2 text-xs"
                  title={linkAV ? '映像と音声をリンク中（クリップを一緒に動かす）。クリックで解除' : '映像と音声のリンクは解除中。クリックでリンク'}
                  onClick={() => setLinkAV((v) => !v)}
                >
                  {linkAV ? '🔗 A/Vリンク' : '🔓 A/V個別'}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 px-2 text-xs"
                  title="映像の段を追加"
                  onClick={() => setExtraLanes((s) => ({ ...s, visual: s.visual + 1 }))}
                >
                  + 映像段
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 px-2 text-xs"
                  title="音声の段を追加"
                  onClick={() => setExtraLanes((s) => ({ ...s, audio: s.audio + 1 }))}
                >
                  + 音声段
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 w-7 p-0"
                  title={playing ? '一時停止 (Space)' : '再生 (Space)'}
                  onClick={() => setPlaying((p) => !p)}
                >
                  {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 w-7 p-0"
                  title="再生ヘッドで分割 (S)"
                  onClick={splitAtPlayhead}
                >
                  <Scissors className="h-4 w-4" />
                </Button>
                <div className="flex items-center gap-2" title="タイムラインの拡大率（左端＝全体表示）">
                  <span className="text-[10px] text-muted-foreground">ズーム</span>
                  <input
                    type="range"
                    min={1}
                    max={8}
                    step={0.1}
                    value={timelineZoom}
                    aria-label="タイムラインズーム"
                    onChange={(event) => setTimelineZoom(Number(clamp(Number(event.target.value), 1, 8).toFixed(2)))}
                    onDoubleClick={() => setTimelineZoom(1)}
                    className="h-1 w-28 cursor-pointer accent-sky-500"
                  />
                  <span className="w-9 text-right text-[10px] tabular-nums text-muted-foreground">{Math.round(timelineZoom * 100)}%</span>
                </div>
                <div className="text-sm tabular-nums text-muted-foreground">
                  {fmtTime(currentTime)} / {fmtTime(contentDuration)}
                </div>
              </div>
              {openNoteKey ? (
                <div className="mt-2 flex items-start gap-2 rounded-md border border-border bg-muted/40 p-2 text-xs">
                  <span className="flex-1 whitespace-pre-wrap">{openNoteKey}</span>
                  <button type="button" className="shrink-0 text-muted-foreground hover:text-foreground" onClick={() => setOpenNoteKey(null)} aria-label="閉じる">
                    ×
                  </button>
                </div>
              ) : null}
              <div ref={timelineScrollRef} className="mt-3 h-[calc(100%-48px)] overflow-auto rounded-md border border-border bg-muted/40 p-2" onWheel={handleTimelineWheel}>
                <div className="flex gap-x-2 text-[11px]">
                  <div className="flex w-[82px] shrink-0 flex-col">
                    {timelineLanes.map((lane, i) => (
                      <div
                        key={lane.key}
                        className="flex items-center justify-end pr-1 text-right font-medium text-muted-foreground"
                        style={{ height: lane.height, marginTop: i === 0 ? 0 : timelineLanes[i - 1].zone !== lane.zone ? 14 : 4 }}
                      >
                        <span className="truncate">{lane.label}</span>
                      </div>
                    ))}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div
                      ref={timelineRef}
                      className="relative"
                      style={timelineTrackStyle}
                      onPointerDownCapture={(event) => {
                        if (event.button !== 2) return; // right button starts a rubber-band select
                        event.preventDefault();
                        event.stopPropagation();
                        marqueeStartRef.current = { x: event.clientX, y: event.clientY };
                        setMarquee({ x0: event.clientX, y0: event.clientY, x1: event.clientX, y1: event.clientY });
                      }}
                      onContextMenu={(event) => event.preventDefault()}
                    >
                      {timelineLanes.map((lane, laneIndex) => {
                        const zoneChanged = laneIndex > 0 && timelineLanes[laneIndex - 1].zone !== lane.zone;
                        const showPending =
                          !!pendingAnnotation &&
                          lane.zone === trackForIntent(pendingAnnotation.intent) &&
                          timelineLanes.findIndex((l) => l.zone === lane.zone) === laneIndex;
                        return (
                          <div
                            key={lane.key}
                            className={`relative w-full overflow-hidden rounded border ${
                              lane.zone === 'audio' ? 'border-border/60 bg-background' : 'border-white/10 bg-neutral-900'
                            } ${isTimelineScrubbing ? 'cursor-grabbing' : 'cursor-default'}`}
                            style={{ height: lane.height, marginTop: laneIndex === 0 ? 0 : zoneChanged ? 14 : 4 }}
                            onPointerDown={(event) => {
                              if (event.target === event.currentTarget) handleTimelinePointerDown(event);
                            }}
                            onPointerUp={() => setTimelineDrag(null)}
                            onPointerCancel={() => setTimelineDrag(null)}
                            onDragOver={(event) => handleLaneDragOver(event, lane)}
                            onDrop={(event) => handleLaneDrop(event, lane)}
                          >
                            <div className="pointer-events-none absolute inset-0 bg-[repeating-linear-gradient(90deg,rgba(127,127,127,0.12)_0,rgba(127,127,127,0.12)_1px,transparent_1px,transparent_48px)]" />
                            {dropPreview && dropPreview.zone === lane.zone && dropPreview.layer === lane.layer && timelineDuration ? (
                              <div
                                className="pointer-events-none absolute top-0.5 bottom-0.5 z-10 rounded border-2 border-dashed border-sky-300 bg-sky-400/25"
                                style={{
                                  left: `${(dropPreview.start / timelineDuration) * 100}%`,
                                  width: `${Math.max(0.8, (dropPreview.len / timelineDuration) * 100)}%`,
                                }}
                              >
                                <span className="px-1 text-[9px] text-sky-100">ここに追加</span>
                              </div>
                            ) : null}
                            {lane.items.map((item) => {
                              const left = timelineDuration ? (item.start / timelineDuration) * 100 : 0;
                              const width = timelineDuration ? Math.max(0.8, ((item.end - item.start) / timelineDuration) * 100) : 1;
                              if (item.kind === 'annotation' && item.annotation) {
                                const a = item.annotation;
                                return (
                                  <div
                                    key={item.key}
                                    data-annotation-id={a.id}
                                    className={`absolute top-1 flex h-[calc(100%-8px)] cursor-grab items-center overflow-hidden rounded border text-[10px] shadow-sm active:cursor-grabbing ${laneColor(a.intent, selectedIds.includes(a.id))}`}
                                    style={{ left: `${left}%`, width: `${width}%` }}
                                    onPointerDown={(event) => startTimelineDrag(event, a, 'move')}
                                    onDoubleClick={() => {
                                      selectAnnotation(a.id);
                                      seekTimeline(a.start);
                                    }}
                                    title={`${a.intent}: ${fmtTime(a.start)} - ${fmtTime(a.end)} ${a.note || ''}`}
                                  >
                                    <button
                                      type="button"
                                      className="h-full w-2 cursor-ew-resize bg-black/25"
                                      onPointerDown={(event) => startTimelineDrag(event, a, 'start')}
                                      aria-label="Resize start"
                                    />
                                    <span className="min-w-0 flex-1 truncate px-1">{itemTypeBadge(item.itemType)}</span>
                                    {a.note ? (
                                      <button
                                        type="button"
                                        className="h-full shrink-0 px-1 text-[9px] hover:bg-black/25"
                                        title="メモを読む"
                                        aria-label="メモ"
                                        onPointerDown={(event) => event.stopPropagation()}
                                        onClick={(event) => {
                                          event.stopPropagation();
                                          setOpenNoteKey((cur) => (cur === a.note ? null : a.note || null));
                                        }}
                                      >
                                        ▼
                                      </button>
                                    ) : null}
                                    <button
                                      type="button"
                                      className="h-full w-2 cursor-ew-resize bg-black/25"
                                      onPointerDown={(event) => startTimelineDrag(event, a, 'end')}
                                      aria-label="Resize end"
                                    />
                                  </div>
                                );
                              }
                              const clip = item.clip;
                              if (!clip) return null;
                              const clipAsset = clip.asset_id ? sequenceAssetMap.get(clip.asset_id) : null;
                              const selected = selectedSequenceClipIds.includes(clip.id);
                              const linkedSelected = !selected && highlightedClipIds.has(clip.id);
                              const isVideo = item.itemType === 'video';
                              const labelText =
                                item.itemType === 'caption'
                                  ? clip.text || 'テロップ'
                                  : item.itemType === 'audio'
                                    ? [audioRoleLabel(clip.role), clipAsset?.label || clip.label].filter(Boolean).join('・')
                                    : clip.label || '素材';
                              return (
                                <div
                                  key={item.key}
                                  data-clip-id={clip.id}
                                  className={`absolute flex cursor-grab items-center overflow-hidden rounded border bg-cover bg-center text-[10px] text-white shadow-sm active:cursor-grabbing ${clipItemColor(item.itemType)} ${
                                    selected
                                      ? 'border-yellow-300 ring-2 ring-yellow-300/70'
                                      : linkedSelected
                                        ? 'border-yellow-300/70 ring-2 ring-yellow-300/40 ring-dashed'
                                        : 'border-white/30'
                                  }`}
                                  style={{
                                    left: `${left}%`,
                                    width: `${width}%`,
                                    top: 3,
                                    bottom: 3,
                                    ...(isVideo && clipAsset?.thumbnail_url
                                      ? { backgroundImage: `linear-gradient(rgba(0,0,0,0.4), rgba(0,0,0,0.4)), url(${clipAsset.thumbnail_url})` }
                                      : {}),
                                  }}
                                  title={`${itemTypeBadge(item.itemType)}: ${labelText} / ${fmtTime(clip.timeline_start)}-${fmtTime(clip.timeline_end)}`}
                                >
                                  <button
                                    type="button"
                                    className="h-full w-2 shrink-0 cursor-ew-resize bg-black/30"
                                    onPointerDown={(event) => startSequenceClipDrag(event, clip, 'start')}
                                    aria-label="Resize clip start"
                                  />
                                  <div
                                    className="flex h-full min-w-0 flex-1 cursor-grab items-center gap-1 truncate px-1 active:cursor-grabbing"
                                    onPointerDown={(event) => startSequenceClipDrag(event, clip, 'move')}
                                    onDoubleClick={(event) => {
                                      event.stopPropagation();
                                      selectSequenceClip(clip.id);
                                      seekTimeline(clip.timeline_start);
                                    }}
                                  >
                                    <span className="shrink-0 rounded bg-black/45 px-1 text-[8px] leading-tight">{itemTypeBadge(item.itemType)}</span>
                                    <span className="truncate">{labelText}</span>
                                  </div>
                                  <button
                                    type="button"
                                    className="h-full w-2 shrink-0 cursor-ew-resize bg-black/30"
                                    onPointerDown={(event) => startSequenceClipDrag(event, clip, 'end')}
                                    aria-label="Resize clip end"
                                  />
                                </div>
                              );
                            })}
                            {showPending && pendingAnnotation ? (
                              <div
                                className="absolute top-1 flex h-[calc(100%-8px)] cursor-grab items-center overflow-hidden rounded border border-orange-300 bg-orange-400/65 text-[10px] text-black active:cursor-grabbing"
                                style={{
                                  left: `${timelineDuration ? (pendingAnnotation.start / timelineDuration) * 100 : 0}%`,
                                  width: `${timelineDuration ? Math.max(0.8, (((pendingAnnotation.end ?? pendingAnnotation.start + 0.2) - pendingAnnotation.start) / timelineDuration) * 100) : 1}%`,
                                }}
                                onPointerDown={(event) => startPendingTimelineDrag(event, 'move')}
                              >
                                <button
                                  type="button"
                                  className="h-full w-2 cursor-ew-resize bg-black/25"
                                  onPointerDown={(event) => startPendingTimelineDrag(event, 'start')}
                                  aria-label="Resize pending start"
                                />
                                <span className="min-w-0 flex-1 truncate px-1">未確定</span>
                                <button
                                  type="button"
                                  className="h-full w-2 cursor-ew-resize bg-black/25"
                                  onPointerDown={(event) => startPendingTimelineDrag(event, 'end')}
                                  aria-label="Resize pending end"
                                />
                              </div>
                            ) : null}
                          </div>
                        );
                      })}
                      <div
                        className="pointer-events-none absolute top-0 bottom-0 z-10 w-px bg-destructive"
                        style={{ left: `${timelineDuration ? (currentTime / timelineDuration) * 100 : 0}%` }}
                      />
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <aside className="flex w-[390px] shrink-0 flex-col border-l border-border bg-background">
            <div className="min-h-0 flex-1 overflow-y-auto p-3">
              {sidePanelTop}
              {pendingAnnotation ? (
                <div className="mb-3 rounded-md border border-orange-300 bg-orange-50 p-3 text-sm text-orange-950">
                  <div className="mb-2 flex items-center justify-between">
                    <div className="font-medium">未確定指示</div>
                    <Button variant="ghost" size="sm" onClick={() => setPendingAnnotation(null)}>
                      取消
                    </Button>
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <Label className="text-xs text-orange-950">Start</Label>
                      <Input
                        type="number"
                        step="0.1"
                        value={pendingAnnotation.start}
                        onChange={(e) => updatePending({ start: Number(e.target.value) })}
                      />
                    </div>
                    <div>
                      <Label className="text-xs text-orange-950">End</Label>
                      <Input
                        type="number"
                        step="0.1"
                        value={pendingAnnotation.end ?? pendingAnnotation.start}
                        onChange={(e) => updatePending({ end: Number(e.target.value) })}
                      />
                    </div>
                  </div>
                  <select
                    value={pendingAnnotation.intent}
                    onChange={(e) => updatePending({ intent: e.target.value })}
                    className="mt-2 h-9 w-full rounded-md border border-orange-200 bg-white px-2 text-sm"
                  >
                    {INTENTS.map((it) => (
                      <option key={it.value} value={it.value}>{it.label}</option>
                    ))}
                  </select>
                  {pendingAnnotation.intent === 'blur' && pendingAnnotation.kind === 'rect' ? (
                    <label className="mt-2 flex items-center gap-2 rounded-md border border-orange-200 bg-white p-2 text-xs text-orange-950">
                      <input
                        type="checkbox"
                        checked={!!(pendingAnnotation.data as { track?: boolean } | undefined)?.track}
                        onChange={(e) => updatePending({ data: { ...((pendingAnnotation.data as object) || {}), track: e.target.checked } })}
                      />
                      追従ぼかし（動く対象を追いかける／OFF＝静止のまま）
                    </label>
                  ) : null}
                  {pendingAnnotation.intent === 'blur' ? null : (
                    <Textarea
                      className="mt-2 bg-white"
                      value={pendingAnnotation.note || ''}
                      onChange={(e) => updatePending({ note: e.target.value })}
                      rows={3}
                      placeholder="この範囲でDanにやってほしいこと"
                    />
                  )}
                  <Button className="mt-2 w-full" size="sm" onClick={confirmPendingAnnotation}>
                    <Check className="mr-1 h-4 w-4" />
                    {pendingAnnotation.intent === 'blur' ? 'ぼかしを追加' : 'タイムラインに追加'}
                  </Button>
                </div>
              ) : null}
              <div className="mb-2 flex items-center justify-between">
                <div className="text-sm font-medium">指示 ({annotations.length})</div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setAnnotations([]);
                    clearSelection();
                  }}
                  disabled={annotations.length === 0}
                >
                  <Eraser className="mr-1 h-4 w-4" />
                  全削除
                </Button>
              </div>
              <div className="space-y-2">
                {annotations.map((a, index) => (
                  <button
                    key={a.id}
                    type="button"
                    onClick={(event) => {
                      selectAnnotation(a.id, event.shiftKey || event.ctrlKey || event.metaKey);
                      seekTimeline(a.start);
                    }}
                    className={`w-full rounded-md border p-2 text-left text-sm transition-colors ${
                      selectedIds.includes(a.id) ? 'border-primary bg-primary/10' : 'border-border hover:bg-muted'
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <span className="rounded bg-muted px-1.5 py-0.5 text-xs tabular-nums">{index + 1}</span>
                      <span className="font-medium">{INTENTS.find((it) => it.value === a.intent)?.label || a.intent}</span>
                      <span className="ml-auto text-xs tabular-nums text-muted-foreground">
                        {fmtTime(a.start)} - {fmtTime(a.end)}
                      </span>
                    </div>
                    {a.note ? <div className="mt-1 line-clamp-2 text-xs text-muted-foreground">{a.note}</div> : null}
                  </button>
                ))}
              </div>
            </div>

            {selected && (
              <div className="space-y-2 border-t border-border p-3">
                <div className="flex items-center justify-between">
                  <div className="text-sm font-medium">選択中</div>
                  <Button variant="ghost" size="sm" onClick={deleteSelected}>
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div className="space-y-1">
                    <div className="flex items-center justify-between text-[10px] text-muted-foreground">
                      <span>開始（秒）</span>
                      <button type="button" className="rounded bg-muted px-1.5 py-0.5 hover:bg-muted/70" title="開始を再生位置（赤線）に" onClick={() => updateSelected({ start: Number(currentTime.toFixed(2)) })}>
                        ＝再生位置
                      </button>
                    </div>
                    <Input
                      type="number"
                      step="0.1"
                      value={selected.start}
                      onChange={(e) => updateSelected({ start: Number(e.target.value) })}
                    />
                  </div>
                  <div className="space-y-1">
                    <div className="flex items-center justify-between text-[10px] text-muted-foreground">
                      <span>終了（秒）</span>
                      <button type="button" className="rounded bg-muted px-1.5 py-0.5 hover:bg-muted/70" title="終了を再生位置（赤線）に" onClick={() => updateSelected({ end: Number(currentTime.toFixed(2)) })}>
                        ＝再生位置
                      </button>
                    </div>
                    <Input
                      type="number"
                      step="0.1"
                      value={selected.end ?? selected.start}
                      onChange={(e) => updateSelected({ end: Number(e.target.value) })}
                    />
                  </div>
                </div>
                <select
                  value={selected.intent}
                  onChange={(e) => updateSelected({ intent: e.target.value })}
                  className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm"
                >
                  {INTENTS.map((it) => (
                    <option key={it.value} value={it.value}>{it.label}</option>
                  ))}
                </select>
                {selected.intent === 'blur' && selected.kind === 'rect' ? (() => {
                  const sd = (selected.data || {}) as { track?: boolean; track_boxes?: Record<string, number[]>; track_text?: string };
                  const analyzed = typeof sd.track_text === 'string';
                  const tracked = !!sd.track_text;
                  const isTracking = trackingId === selected.id;
                  return (
                    <div className="space-y-2 rounded-md border border-sky-500/40 bg-sky-500/10 p-2">
                      <div className="flex gap-1">
                        <button
                          type="button"
                          className={`flex-1 rounded px-2 py-1 text-xs ${!sd.track ? 'bg-sky-500 text-white' : 'bg-background text-muted-foreground'}`}
                          onClick={() => updateSelected({ data: { ...sd, track: false } })}
                        >
                          静止
                        </button>
                        <button
                          type="button"
                          className={`flex-1 rounded px-2 py-1 text-xs ${sd.track ? 'bg-sky-500 text-white' : 'bg-background text-muted-foreground'}`}
                          onClick={() => updateSelected({ data: { ...sd, track: true } })}
                        >
                          追従
                        </button>
                      </div>
                      {sd.track ? (
                        <div className="space-y-1">
                          <Button size="sm" className="w-full" disabled={isTracking || !onTrackBlur} onClick={() => runTrackBlur(selected)}>
                            {isTracking ? '解析中…' : analyzed ? '再解析' : '▶ 解析（文字を追跡）'}
                          </Button>
                          <p className="text-[10px] text-muted-foreground">
                            {isTracking
                              ? '解析中…文字を探して追跡しています。'
                              : tracked
                                ? `✓「${sd.track_text}」を追跡（${fmtTime(selected.start)}〜${fmtTime(selected.end)}）。クリップ尺はこの範囲に自動調整。`
                                : analyzed
                                  ? '文字が見つかりませんでした。枠を文字に合わせて再解析（任意物体の追従は近日対応）。'
                                  : '隠したい文字を枠で囲んで「解析」を押すと、その文字を追ってぼかし、クリップ尺も自動で決まります。'}
                          </p>
                        </div>
                      ) : (
                        <p className="text-[10px] text-muted-foreground">この枠で静止ぼかし（機械処理・即時）。</p>
                      )}
                    </div>
                  );
                })() : null}
                <Textarea
                  value={selected.note || ''}
                  onChange={(e) => updateSelected({ note: e.target.value })}
                  rows={3}
                  placeholder={selected.intent === 'blur' ? 'メモ（任意）' : 'この範囲でDanにやってほしいこと（例: ここに商品のアップ映像を生成して）'}
                />
                {(selected.intent === 'generate' || selected.intent === 'comment') && onExecuteClip ? (
                  <Button
                    size="sm"
                    className="w-full"
                    disabled={executingId === selected.id}
                    onClick={() => runExecuteClip(selected)}
                  >
                    {executingId === selected.id ? '実行中…' : '▶ 実行（Danに反映）'}
                  </Button>
                ) : null}
              </div>
            )}

            {selectedSequenceClip && (
              <div className="space-y-2 border-t border-border p-3">
                <div className="flex items-center justify-between">
                  <div className="text-sm font-medium">選択中クリップ</div>
                  <div className="flex items-center gap-1">
                    <Button variant="ghost" size="sm" className="h-7 px-2 text-[11px]" title="詰めて削除（後続を前へ・Shift+Delete）" onClick={rippleDelete}>
                      詰めて削除
                    </Button>
                    <Button variant="ghost" size="sm" className="h-7 w-7 p-0" title="削除（穴あき・Delete）" onClick={deleteSelected}>
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
                <Input
                  value={selectedSequenceClip.label || ''}
                  onChange={(e) => updateSelectedSequenceClip({ label: e.target.value })}
                  placeholder="クリップ名"
                />
                <div className="grid grid-cols-2 gap-2">
                  <Input
                    type="number"
                    step="0.1"
                    value={selectedSequenceClip.timeline_start}
                    onChange={(e) => updateSelectedSequenceClip({ timeline_start: Number(e.target.value) })}
                  />
                  <Input
                    type="number"
                    step="0.1"
                    value={selectedSequenceClip.timeline_end}
                    onChange={(e) => updateSelectedSequenceClip({ timeline_end: Number(e.target.value) })}
                  />
                </div>
                {(selectedSequenceClip.track === 'video' || selectedSequenceClip.asset_id) ? (
                  <div className="grid grid-cols-2 gap-2">
                    <Input
                      type="number"
                      step="0.1"
                      value={selectedSequenceClip.source_start || 0}
                      onChange={(e) => updateSelectedSequenceClip({ source_start: Number(e.target.value) })}
                    />
                    <Input
                      type="number"
                      step="0.1"
                      value={selectedSequenceClip.source_end || 0}
                      onChange={(e) => updateSelectedSequenceClip({ source_end: Number(e.target.value) })}
                    />
                  </div>
                ) : null}
                {selectedSequenceClip.asset_id && (selectedSequenceClip.track === 'video' || selectedSequenceClip.track === 'overlay') ? (
                  // Unified サイズ/左右/上下 for EVERY video/overlay clip (no clip-specific
                  // panel). A PiP/wipe (position box) and a base clip (transform) both expose
                  // the same three controls; we map them to whichever field the clip uses.
                  (() => {
                    const pos = selectedSequenceClip.position;
                    const isPip = !!pos && !(pos.x <= 0.001 && pos.y <= 0.001 && pos.width >= 0.999 && pos.height >= 0.999);
                    let size: number, lr: number, ud: number;
                    if (isPip && pos) {
                      size = (pos.width + pos.height) / 2;
                      lr = pos.x + pos.width / 2 - 0.5;
                      ud = pos.y + pos.height / 2 - 0.5;
                    } else {
                      const tf = selectedSequenceClip.transform || { scale: 1, x: 0, y: 0 };
                      size = tf.scale; lr = tf.x; ud = tf.y;
                    }
                    const apply = (nextSize: number, nextLr: number, nextUd: number) => {
                      if (isPip && pos) {
                        const aspect = pos.height > 0 ? pos.width / pos.height : 1;
                        const h = Math.max(0.05, Math.min(1, nextSize * 2 / (1 + aspect)));
                        const w = Math.max(0.05, Math.min(1, h * aspect));
                        const cx = 0.5 + nextLr, cy = 0.5 + nextUd;
                        // allow off-screen placement (no [0,1-w] clamp): the frame just windows it
                        updateSelectedSequenceClip({ position: {
                          x: Number((cx - w / 2).toFixed(4)),
                          y: Number((cy - h / 2).toFixed(4)),
                          width: Number(w.toFixed(4)), height: Number(h.toFixed(4)) } });
                      } else {
                        updateSelectedSequenceClip({ transform: { scale: Number(nextSize.toFixed(4)), x: Number(nextLr.toFixed(4)), y: Number(nextUd.toFixed(4)) } });
                      }
                    };
                    return (
                      <div className="space-y-2 rounded-md border border-border p-2">
                        <div className="text-xs font-medium text-muted-foreground">映像のサイズ・位置（プレビュー上でドラッグも可）</div>
                        <label className="block text-[10px] text-muted-foreground">
                          サイズ {Math.round(size * 100)}%
                          <input type="range" min={isPip ? '0.05' : '0.2'} max={isPip ? '1' : '3'} step="0.01" value={size}
                            onChange={(e) => apply(Number(e.target.value), lr, ud)} className="w-full" />
                        </label>
                        <div className="grid grid-cols-2 gap-2">
                          <label className="flex flex-col gap-1 text-[10px] text-muted-foreground">
                            左右 {Math.round(lr * 100)}%
                            <input type="range" min="-2" max="2" step="0.01" value={lr}
                              onChange={(e) => apply(size, Number(e.target.value), ud)} />
                          </label>
                          <label className="flex flex-col gap-1 text-[10px] text-muted-foreground">
                            上下 {Math.round(ud * 100)}%
                            <input type="range" min="-2" max="2" step="0.01" value={ud}
                              onChange={(e) => apply(size, lr, Number(e.target.value))} />
                          </label>
                        </div>
                        {(selectedSequenceClip.transform || isPip) ? (
                          <Button variant="ghost" size="sm" className="h-6 w-full text-[10px]"
                            onClick={() => updateSelectedSequenceClip(isPip ? { position: null } : { transform: null })}>
                            サイズ・位置をリセット
                          </Button>
                        ) : null}
                      </div>
                    );
                  })()
                ) : null}
                {(selectedSequenceClip.track === 'video' || selectedSequenceClip.track === 'overlay') && selectedSequenceClip.asset_id ? (
                  (() => {
                    const cr = selectedSequenceClip.crop || { top: 0, bottom: 0, left: 0, right: 0 };
                    const setCrop = (p: Partial<typeof cr>) => updateSelectedSequenceClip({ crop: { ...cr, ...p } });
                    return (
                      <div className="space-y-2 rounded-md border border-border p-2">
                        <div className="text-xs font-medium text-muted-foreground">クロップ（端を切り取る）</div>
                        <div className="grid grid-cols-2 gap-2">
                          {([['top', '上'], ['bottom', '下'], ['left', '左'], ['right', '右']] as const).map(([key, label]) => (
                            <label key={key} className="flex flex-col gap-1 text-[10px] text-muted-foreground">
                              {label} {Math.round((cr[key] ?? 0) * 100)}%
                              <input type="range" min="0" max="0.9" step="0.01" value={cr[key] ?? 0}
                                onChange={(e) => setCrop({ [key]: Number(e.target.value) })} />
                            </label>
                          ))}
                        </div>
                        {selectedSequenceClip.crop ? (
                          <Button variant="ghost" size="sm" className="h-6 w-full text-[10px]"
                            onClick={() => updateSelectedSequenceClip({ crop: null })}>クロップをリセット</Button>
                        ) : null}
                      </div>
                    );
                  })()
                ) : null}
                {(selectedSequenceClip.track === 'audio' || selectedSequenceClip.track === 'video' || selectedSequenceClip.track === 'overlay') && selectedSequenceClip.asset_id ? (
                  (() => {
                    const vol = selectedSequenceClip.volume ?? 1;
                    return (
                      <label className="block rounded-md border border-border p-2 text-[10px] text-muted-foreground">
                        音量 {Math.round(vol * 100)}%
                        <input type="range" min="0" max="2" step="0.05" value={vol}
                          onChange={(e) => updateSelectedSequenceClip({ volume: Number(e.target.value) })} className="w-full" />
                      </label>
                    );
                  })()
                ) : null}
                {selectedSequenceClip.track === 'caption' || typeof selectedSequenceClip.text === 'string' ? (
                  <>
                    <Textarea
                      value={selectedSequenceClip.text || ''}
                      onChange={(e) => updateSelectedSequenceClip({ text: e.target.value })}
                      rows={3}
                      placeholder="テロップ本文"
                    />
                    {(() => {
                      const st = selectedSequenceClip.style || {};
                      const setStyle = (patch: Partial<CaptionStyle>) =>
                        updateSelectedSequenceClip({ style: { ...st, ...patch } });
                      return (
                        <div className="space-y-2 rounded-md border border-border p-2">
                          <div className="text-xs font-medium text-muted-foreground">テロップのデザイン</div>
                          <style>{CAPTION_FONT_FACE_CSS}</style>
                          <div className="space-y-1">
                            <div className="text-[10px] text-muted-foreground">プリセット（クリックで適用・プレビュー＝書き出しと同じ見た目）</div>
                            <div className="grid grid-cols-4 gap-1">
                              {CAPTION_DESIGN_PRESETS.map((p) => {
                                const d = p.design;
                                const fnt = CAPTION_FONTS[d.font ?? 'noto-sans'];
                                const active = captionMatchesPreset(st, d);
                                return (
                                  <button
                                    key={p.id}
                                    type="button"
                                    title={`${p.label}${d.animation && d.animation !== 'none' ? '（動き）' : ''}`}
                                    onClick={() => updateSelectedSequenceClip({ style: { ...d } })}
                                    className={`flex flex-col items-center gap-0.5 rounded-md border px-1 py-1.5 transition ${active ? 'border-sky-500 bg-sky-500/10' : 'border-border hover:border-sky-400/60'}`}
                                  >
                                    <span
                                      className="leading-none"
                                      style={{
                                        fontFamily: `${fnt.css}, sans-serif`,
                                        fontWeight: fnt.weight,
                                        fontSize: '0.95rem',
                                        WebkitTextStroke: `${0.5 * (d.outlineWidth ?? 1)}px ${d.outlineColor || '#000'}`,
                                        paintOrder: 'stroke fill',
                                        ...(d.gradient
                                          ? { backgroundImage: `linear-gradient(180deg, ${d.gradient[0]}, ${d.gradient[1]})`, WebkitBackgroundClip: 'text', backgroundClip: 'text', color: 'transparent' }
                                          : { color: d.color || '#fff' }),
                                      }}
                                    >
                                      あA
                                    </span>
                                    <span className="text-[8px] leading-tight text-muted-foreground">{p.label}</span>
                                  </button>
                                );
                              })}
                            </div>
                            <Button
                              variant="outline"
                              size="sm"
                              className="h-6 w-full text-[10px]"
                              disabled={!st || Object.keys(st).length === 0}
                              onClick={() => {
                                const capIds = new Set(
                                  allSequenceClips
                                    .filter((c) => c.track === 'caption' || typeof c.text === 'string')
                                    .map((c) => String(c.id)),
                                );
                                if (st && Object.keys(st).length > 0) updateSequenceClips(capIds, { style: { ...st } });
                              }}
                            >
                              この見た目を全テロップに適用
                            </Button>
                          </div>
                          <div className="grid grid-cols-2 gap-2">
                            <label className="flex flex-col gap-0.5 text-[10px] text-muted-foreground">
                              フォント
                              <select
                                value={(st.font as CaptionFontId) || 'noto-sans'}
                                onChange={(e) => setStyle({ font: e.target.value as CaptionFontId })}
                                className="h-7 rounded-md border border-input bg-background px-1 text-xs text-foreground"
                              >
                                {(Object.keys(CAPTION_FONTS) as CaptionFontId[]).map((id) => (
                                  <option key={id} value={id}>{CAPTION_FONTS[id].label}</option>
                                ))}
                              </select>
                            </label>
                            <label className="flex flex-col gap-0.5 text-[10px] text-muted-foreground">
                              動き
                              <select
                                value={st.animation || 'none'}
                                onChange={(e) => setStyle({ animation: e.target.value as CaptionAnimation })}
                                className="h-7 rounded-md border border-input bg-background px-1 text-xs text-foreground"
                              >
                                {CAPTION_ANIM_OPTIONS.map((o) => (
                                  <option key={o.value} value={o.value}>{o.label}</option>
                                ))}
                              </select>
                            </label>
                          </div>
                          {st.animation === 'karaoke' ? (
                            <label className="flex items-center justify-between text-[10px] text-muted-foreground">
                              ハイライト色（喋っている単語）
                              <input
                                type="color"
                                value={st.highlightColor || '#ff3b6b'}
                                onChange={(e) => setStyle({ highlightColor: e.target.value })}
                                className="h-6 w-8 rounded border border-input bg-background"
                              />
                            </label>
                          ) : null}
                          {st.animation === 'karaoke' || st.animation === 'typewriter' ? (
                            <div className="text-[9px] text-muted-foreground">🔊 実際の声に自動で追従します</div>
                          ) : null}
                          <div className="flex items-center gap-3 text-[10px] text-muted-foreground">
                            <label className="flex items-center gap-1">
                              <input
                                type="checkbox"
                                checked={!!st.bg}
                                onChange={(e) => setStyle({ bg: e.target.checked ? { color: st.bg?.color || '#000000', opacity: st.bg?.opacity ?? 0.6, radius: 0.18, padX: 0.45, padY: 0.16 } : undefined })}
                              />
                              背景箱
                            </label>
                            {st.bg ? (
                              <input
                                type="color"
                                value={st.bg.color || '#000000'}
                                onChange={(e) => setStyle({ bg: { ...st.bg, color: e.target.value } })}
                                className="h-5 w-7 rounded border border-input bg-background"
                              />
                            ) : null}
                            <label className="flex items-center gap-1">
                              <input
                                type="checkbox"
                                checked={!!st.shadow}
                                onChange={(e) => setStyle({ shadow: e.target.checked ? { color: 'rgba(0,0,0,0.55)', blur: 16, dy: 6 } : undefined })}
                              />
                              影
                            </label>
                          </div>
                          <div className="grid grid-cols-2 gap-2">
                            <label className="flex items-center gap-2 text-xs">
                              文字色
                              <input
                                type="color"
                                value={st.color || '#ffffff'}
                                onChange={(e) => setStyle({ color: e.target.value })}
                                className="h-6 w-8 rounded border border-input bg-background"
                              />
                            </label>
                            <label className="flex items-center gap-2 text-xs">
                              フチ色
                              <input
                                type="color"
                                value={st.outlineColor || '#000000'}
                                onChange={(e) => setStyle({ outlineColor: e.target.value })}
                                className="h-6 w-8 rounded border border-input bg-background"
                              />
                            </label>
                          </div>
                          <label className="block text-xs">
                            大きさ {Math.round((st.fontSize ?? 1) * 100)}%
                            <input
                              type="range"
                              min="0.5"
                              max="2.5"
                              step="0.1"
                              value={st.fontSize ?? 1}
                              onChange={(e) => setStyle({ fontSize: Number(e.target.value) })}
                              className="w-full"
                            />
                          </label>
                          <label className="block text-xs">
                            フチの太さ {Math.round((st.outlineWidth ?? 1) * 100)}%
                            <input
                              type="range"
                              min="0"
                              max="3"
                              step="0.25"
                              value={st.outlineWidth ?? 1}
                              onChange={(e) => setStyle({ outlineWidth: Number(e.target.value) })}
                              className="w-full"
                            />
                          </label>
                          <div className="flex items-center gap-2">
                            <select
                              value={st.position || 'bottom'}
                              onChange={(e) => setStyle({ position: e.target.value as CaptionStyle['position'] })}
                              className="h-8 flex-1 rounded-md border border-input bg-background px-2 text-xs"
                            >
                              <option value="bottom">下</option>
                              <option value="center">中央</option>
                              <option value="top">上</option>
                            </select>
                            <label className="flex items-center gap-1 text-xs">
                              <input
                                type="checkbox"
                                checked={st.bold !== false}
                                onChange={(e) => setStyle({ bold: e.target.checked })}
                              />
                              太字
                            </label>
                          </div>
                          <div className="grid grid-cols-2 gap-2">
                            <label className="flex flex-col gap-1 text-[10px] text-muted-foreground">
                              左右 {Math.round((st.x ?? 0) * 100)}%
                              <input type="range" min="-0.3" max="0.3" step="0.01" value={st.x ?? 0}
                                onChange={(e) => setStyle({ x: Number(e.target.value) })} />
                            </label>
                            <label className="flex flex-col gap-1 text-[10px] text-muted-foreground">
                              上下 {Math.round((st.y ?? 0) * 100)}%
                              <input type="range" min="-0.5" max="0.5" step="0.01" value={st.y ?? 0}
                                onChange={(e) => setStyle({ y: Number(e.target.value) })} />
                            </label>
                          </div>
                          {selectedSequenceClip.style ? (
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-6 w-full text-[10px]"
                              onClick={() => updateSelectedSequenceClip({ style: null })}
                            >
                              デザインをリセット
                            </Button>
                          ) : null}
                        </div>
                      );
                    })()}
                  </>
                ) : null}
                <p className="pt-1 text-[10px] text-muted-foreground">
                  クリップを掴んで左右で移動、端でトリミング、上下の段へドラッグで重ね順（レイヤー）を変更。Deleteで削除。
                </p>
              </div>
            )}
          </aside>
        </div>
      </main>
    </div>
  );
}
