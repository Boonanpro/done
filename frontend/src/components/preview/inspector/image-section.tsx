'use client';

import { useEffect, useMemo, useState } from 'react';
import { Loader2, Wand2 } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';

import { usePreviewStore, findMediaInScope, queueInspectorEdit } from '@/stores/preview-store';
import { SectionHeader, SelectInput, SliderInput } from './controls';
import { FocalPointPad, type FocalPoint } from './focal-point-pad';
import { HistoryStrip, type HistoryItem } from './history-strip';

function parseObjectPosition(raw: string | undefined): FocalPoint {
  if (!raw) return { x: 50, y: 50 };
  const parts = raw.trim().split(/\s+/);
  const toPct = (s: string): number => {
    if (s.endsWith('%')) return parseFloat(s);
    const keywords: Record<string, number> = {
      left: 0, center: 50, right: 100, top: 0, bottom: 100,
    };
    if (s in keywords) return keywords[s];
    return 50;
  };
  const x = toPct(parts[0] || '50%');
  const y = parts[1] ? toPct(parts[1]) : 50;
  return { x, y };
}

export function ImageSection() {
  const liveTarget = usePreviewStore((s) => s.liveTarget);
  const projectId = usePreviewStore((s) => s.projectId);
  const applyStyleTo = usePreviewStore((s) => s.applyStyleTo);
  void usePreviewStore((s) => s.styleVersion);
  const [prompt, setPrompt] = useState('');
  const [generating, setGenerating] = useState(false);

  // 選択要素の周辺から <img> を探す（自身・子孫・先祖の順）
  const img = useMemo<HTMLImageElement | null>(() => {
    return findMediaInScope(liveTarget, 'img') as HTMLImageElement | null;
  }, [liveTarget]);
  const currentSrc = img?.getAttribute('src') || '';
  const currentAlt = img?.getAttribute('alt') || '';
  const [altDraft, setAltDraft] = useState(currentAlt);

  useEffect(() => {
    setAltDraft(currentAlt);
  }, [currentAlt]);

  const cs = useMemo(() => {
    if (!img) return null;
    const win = img.ownerDocument?.defaultView;
    return win ? win.getComputedStyle(img) : null;
  }, [img]);

  const focalPoint = parseObjectPosition(cs?.objectPosition);

  const { data: historyItems = [] } = useQuery<HistoryItem[]>({
    queryKey: ['generated-images', projectId],
    queryFn: async () => {
      const url = projectId
        ? `/api/v1/images?project_id=${projectId}`
        : '/api/v1/images';
      const res = await fetch(url, { credentials: 'include' });
      if (!res.ok) return [];
      const rows = await res.json();
      return rows.map((r: { id: string; url: string; prompt?: string; created_at?: string; kind?: string }) => ({
        id: r.id,
        url: r.url,
        prompt: r.prompt,
        created_at: r.created_at,
        kind: r.kind,
      }));
    },
    enabled: !!projectId,
    staleTime: 10_000,
  });

  const applySrc = (url: string) => {
    if (!img) return;
    img.setAttribute('src', url);
    queueInspectorEdit({ target: img, attrsOnly: { src: url } });
  };

  const applyAlt = () => {
    if (!img) return;
    img.setAttribute('alt', altDraft);
    queueInspectorEdit({ target: img, attrsOnly: { alt: altDraft } });
  };

  const handleRegenerate = async () => {
    if (!currentSrc || !prompt.trim() || generating) return;
    setGenerating(true);
    try {
      const res = await fetch('/api/v1/images/edit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          prompt: prompt.trim(),
          reference_url: currentSrc,
          project_id: projectId,
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      applySrc(data.url);
      setPrompt('');
    } catch (e) {
      console.error('regen failed', e);
      alert('画像の再生成に失敗しました');
    } finally {
      setGenerating(false);
    }
  };

  // focal point / object-fit は <img> 自体に直接書く。applyStyleTo が
  // styleVersion を bump するので、このコンポーネントも再描画される
  const onFocalChange = (v: FocalPoint) => {
    if (!img) return;
    applyStyleTo(img, 'object-position', `${v.x.toFixed(1)}% ${v.y.toFixed(1)}%`);
  };

  const setObjectFit = (v: string) => {
    if (!img) return;
    applyStyleTo(img, 'object-fit', v);
  };

  // overlay（暗転/ぼかし）は画像自体に CSS filter で適用する。
  // 個別の overlay div は作らない方針
  const parseFilter = (raw: string): { darken: number; blur: number } => {
    if (!raw || raw === 'none') return { darken: 0, blur: 0 };
    const brightMatch = raw.match(/brightness\(([\d.]+)\)/);
    const blurMatch = raw.match(/blur\(([\d.]+)px\)/);
    const brightness = brightMatch ? parseFloat(brightMatch[1]) : 1;
    const blur = blurMatch ? parseFloat(blurMatch[1]) : 0;
    return { darken: Math.round((1 - brightness) * 100), blur };
  };
  const currentFilter = parseFilter(cs?.filter || '');
  const writeFilter = (next: { darken: number; blur: number }) => {
    if (!img) return;
    const parts: string[] = [];
    if (next.darken > 0) parts.push(`brightness(${((100 - next.darken) / 100).toFixed(2)})`);
    if (next.blur > 0) parts.push(`blur(${next.blur}px)`);
    applyStyleTo(img, 'filter', parts.join(' ') || 'none');
  };

  if (!img) return null;

  return (
    <section className="flex flex-col gap-3">
      <SectionHeader title="Image" />

      {/* サムネ */}
      <div className="flex items-start gap-2">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={currentSrc}
          alt=""
          className="h-16 w-24 shrink-0 rounded border border-border object-cover"
        />
        <div className="min-w-0 flex-1 space-y-1">
          <div className="truncate text-[10px] text-muted-foreground">{currentSrc}</div>
          <input
            type="text"
            value={altDraft}
            onChange={(e) => setAltDraft(e.target.value)}
            onBlur={applyAlt}
            placeholder="alt 説明"
            className="w-full rounded border border-border bg-input/30 px-1.5 py-0.5 text-xs"
          />
        </div>
      </div>

      {/* object-fit / focal point */}
      <SelectInput
        label="object-fit"
        value={cs?.objectFit || 'fill'}
        options={[
          { value: 'cover', label: 'cover' },
          { value: 'contain', label: 'contain' },
          { value: 'fill', label: 'fill' },
          { value: 'scale-down', label: 'scale-down' },
          { value: 'none', label: 'none' },
        ]}
        onChange={setObjectFit}
      />
      <FocalPointPad
        value={focalPoint}
        onChange={onFocalChange}
        backgroundSrc={currentSrc}
      />

      {/* Overlay（画像に直接かかる暗転/ぼかし） */}
      <div className="flex flex-col gap-1.5">
        <span className="text-xs font-medium text-muted-foreground">Overlay</span>
        <SliderInput
          label="darken"
          value={currentFilter.darken}
          min={0}
          max={80}
          unit="%"
          onChange={(v) => writeFilter({ ...currentFilter, darken: v })}
        />
        <SliderInput
          label="blur"
          value={currentFilter.blur}
          min={0}
          max={20}
          step={0.5}
          unit="px"
          onChange={(v) => writeFilter({ ...currentFilter, blur: v })}
        />
      </div>

      {/* 再生成 */}
      <div className="flex flex-col gap-1.5 rounded-md border border-border bg-muted/20 p-2">
        <label className="text-xs text-muted-foreground">画像を再生成</label>
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="どう変えたいか（例: 色を暖色に、被写体はそのまま）"
          rows={2}
          className="resize-none rounded border border-border bg-background p-1.5 text-xs"
        />
        <button
          onClick={handleRegenerate}
          disabled={!prompt.trim() || generating}
          className="flex items-center justify-center gap-1 rounded bg-primary px-2 py-1 text-xs font-medium text-primary-foreground hover:opacity-90 disabled:opacity-40"
        >
          {generating ? (
            <>
              <Loader2 className="h-3 w-3 animate-spin" />
              生成中...
            </>
          ) : (
            <>
              <Wand2 className="h-3 w-3" />
              再生成
            </>
          )}
        </button>
      </div>

      {/* 履歴 */}
      <HistoryStrip
        items={historyItems}
        currentUrl={currentSrc}
        onSelect={(it) => applySrc(it.url)}
      />
    </section>
  );
}
