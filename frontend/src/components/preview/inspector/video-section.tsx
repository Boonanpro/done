'use client';

import { useEffect, useState } from 'react';
import { Loader2, Wand2 } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';

import { usePreviewStore } from '@/stores/preview-store';
import { SectionHeader, SelectInput, SliderInput, ToggleGroup } from './controls';
import { FocalPointPad, type FocalPoint } from './focal-point-pad';
import { HistoryStrip, type HistoryItem } from './history-strip';

function parseObjectPosition(raw: string | undefined): FocalPoint {
  if (!raw) return { x: 50, y: 50 };
  const parts = raw.trim().split(/\s+/);
  const toPct = (s: string): number => {
    if (s.endsWith('%')) return parseFloat(s);
    const keywords: Record<string, number> = { left: 0, center: 50, right: 100, top: 0, bottom: 100 };
    if (s in keywords) return keywords[s];
    return 50;
  };
  const x = toPct(parts[0] || '50%');
  const y = parts[1] ? toPct(parts[1]) : 50;
  return { x, y };
}

export function VideoSection() {
  const selectedElement = usePreviewStore((s) => s.selectedElement);
  const projectId = usePreviewStore((s) => s.projectId);
  const applyStyleTo = usePreviewStore((s) => s.applyStyleTo);
  const applyAttrs = usePreviewStore((s) => s.applyAttrs);
  void usePreviewStore((s) => s.styleVersion);
  const [prompt, setPrompt] = useState('');
  const [generating, setGenerating] = useState(false);
  const [aspectRatio, setAspectRatio] = useState<'16:9' | '9:16' | '1:1'>('16:9');
  // 再生オプションは UI 用ローカル state（cross-origin では DOM プロパティを直接読めない）
  const [playbackFlags, setPlaybackFlags] = useState({
    autoplay: false, loop: true, muted: true, controls: false, playsinline: true,
  });

  const key = selectedElement?.elementKey;
  const cs = selectedElement?.computedStyles || {};
  const currentSrc = selectedElement?.media?.src || '';
  const currentPoster = selectedElement?.media?.poster || '';
  const [posterDraft, setPosterDraft] = useState(currentPoster);
  useEffect(() => { setPosterDraft(currentPoster); }, [currentPoster]);

  const focalPoint = parseObjectPosition(cs.objectPosition);

  const { data: historyItems = [] } = useQuery<HistoryItem[]>({
    queryKey: ['generated-videos', projectId],
    queryFn: async () => {
      const url = projectId ? `/api/v1/videos?project_id=${projectId}` : '/api/v1/videos';
      const res = await fetch(url, { credentials: 'include' });
      if (!res.ok) return [];
      const rows = await res.json();
      return rows.map((r: { id: string; url: string; prompt?: string; created_at?: string; kind?: string }) => ({
        id: r.id, url: r.url, prompt: r.prompt, created_at: r.created_at, kind: r.kind,
      }));
    },
    enabled: !!projectId,
    staleTime: 10_000,
  });

  const applySrc = (url: string) => { if (key) applyAttrs(key, { src: url }); };
  const applyPoster = () => { if (key) applyAttrs(key, { poster: posterDraft }); };

  // cross-origin: 真偽属性の付与のみ反映（除去は step7 で対応）。UI は即時更新。
  const toggleAttribute = (
    attr: 'autoplay' | 'loop' | 'muted' | 'controls' | 'playsinline',
    on: boolean
  ) => {
    setPlaybackFlags((p) => ({ ...p, [attr]: on }));
    if (key && on) applyAttrs(key, { [attr]: '' });
  };

  const onFocalChange = (v: FocalPoint) => { if (key) applyStyleTo(key, 'object-position', `${v.x.toFixed(1)}% ${v.y.toFixed(1)}%`); };
  const setObjectFit = (v: string) => { if (key) applyStyleTo(key, 'object-fit', v); };

  const parseFilter = (raw: string): { darken: number; blur: number } => {
    if (!raw || raw === 'none') return { darken: 0, blur: 0 };
    const brightMatch = raw.match(/brightness\(([\d.]+)\)/);
    const blurMatch = raw.match(/blur\(([\d.]+)px\)/);
    const brightness = brightMatch ? parseFloat(brightMatch[1]) : 1;
    const blur = blurMatch ? parseFloat(blurMatch[1]) : 0;
    return { darken: Math.round((1 - brightness) * 100), blur };
  };
  const currentFilter = parseFilter(cs.filter || '');
  const writeFilter = (next: { darken: number; blur: number }) => {
    if (!key) return;
    const parts: string[] = [];
    if (next.darken > 0) parts.push(`brightness(${((100 - next.darken) / 100).toFixed(2)})`);
    if (next.blur > 0) parts.push(`blur(${next.blur}px)`);
    applyStyleTo(key, 'filter', parts.join(' ') || 'none');
  };

  const handleRegenerate = async () => {
    if (!prompt.trim() || generating) return;
    setGenerating(true);
    try {
      const res = await fetch('/api/v1/videos/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ prompt: prompt.trim(), aspect_ratio: aspectRatio, reference_image_url: currentPoster || undefined, project_id: projectId }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      applySrc(data.url);
      setPrompt('');
    } catch (e) {
      console.error('video regen failed', e);
      alert('動画の再生成に失敗しました');
    } finally {
      setGenerating(false);
    }
  };

  if (selectedElement?.media?.kind !== 'video' || !key) return null;

  return (
    <section className="flex flex-col gap-3">
      <SectionHeader title="Video" />

      <div className="flex items-start gap-2">
        <video src={currentSrc} className="h-16 w-24 shrink-0 rounded border border-border object-cover" muted playsInline />
        <div className="min-w-0 flex-1 space-y-1">
          <div className="truncate text-[10px] text-muted-foreground">{currentSrc}</div>
          <input
            type="text"
            value={posterDraft}
            onChange={(e) => setPosterDraft(e.target.value)}
            onBlur={applyPoster}
            placeholder="poster 画像 URL（省略可）"
            className="w-full rounded border border-border bg-input/30 px-1.5 py-0.5 text-xs"
          />
        </div>
      </div>

      <div className="flex flex-col gap-1">
        <span className="text-xs text-muted-foreground">再生オプション</span>
        <div className="grid grid-cols-2 gap-1">
          {([
            ['autoplay', 'autoplay'],
            ['loop', 'loop'],
            ['muted', 'muted'],
            ['controls', 'controls'],
            ['playsinline', 'playsInline'],
          ] as const).map(([attr, label]) => {
            const on = playbackFlags[attr];
            return (
              <button
                key={attr}
                onClick={() => toggleAttribute(attr, !on)}
                className={`rounded border px-2 py-0.5 text-xs transition-colors ${
                  on ? 'border-primary bg-primary/10 text-primary' : 'border-border bg-background text-muted-foreground hover:bg-muted'
                }`}
              >
                {label}
              </button>
            );
          })}
        </div>
      </div>

      <SelectInput
        label="object-fit"
        value={cs.objectFit || 'fill'}
        options={[
          { value: 'cover', label: 'cover' },
          { value: 'contain', label: 'contain' },
          { value: 'fill', label: 'fill' },
          { value: 'scale-down', label: 'scale-down' },
        ]}
        onChange={setObjectFit}
      />
      <FocalPointPad value={focalPoint} onChange={onFocalChange} backgroundSrc={currentPoster || undefined} />

      <div className="flex flex-col gap-1.5">
        <span className="text-xs font-medium text-muted-foreground">Overlay</span>
        <SliderInput label="darken" value={currentFilter.darken} min={0} max={80} unit="%" onChange={(v) => writeFilter({ ...currentFilter, darken: v })} />
        <SliderInput label="blur" value={currentFilter.blur} min={0} max={20} step={0.5} unit="px" onChange={(v) => writeFilter({ ...currentFilter, blur: v })} />
      </div>

      <div className="flex flex-col gap-1.5 rounded-md border border-border bg-muted/20 p-2">
        <label className="text-xs text-muted-foreground">動画を再生成（30〜60秒）</label>
        <ToggleGroup
          label="aspect"
          value={aspectRatio}
          options={[
            { value: '16:9', label: '16:9' },
            { value: '9:16', label: '9:16' },
            { value: '1:1', label: '1:1' },
          ]}
          onChange={(v) => setAspectRatio(v as '16:9' | '9:16' | '1:1')}
        />
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="動きの指示（例: 波が静かに打ち寄せる、カメラは固定）"
          rows={2}
          className="resize-none rounded border border-border bg-background p-1.5 text-xs"
        />
        <button
          onClick={handleRegenerate}
          disabled={!prompt.trim() || generating}
          className="flex items-center justify-center gap-1 rounded bg-primary px-2 py-1 text-xs font-medium text-primary-foreground hover:opacity-90 disabled:opacity-40"
        >
          {generating ? (<><Loader2 className="h-3 w-3 animate-spin" />生成中...</>) : (<><Wand2 className="h-3 w-3" />再生成</>)}
        </button>
      </div>

      <HistoryStrip items={historyItems} currentUrl={currentSrc} onSelect={(it) => applySrc(it.url)} isVideo />
    </section>
  );
}
