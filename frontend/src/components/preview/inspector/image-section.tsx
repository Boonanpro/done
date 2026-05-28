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

/** computed style の background-image から url を取り出す。`none` や gradient のみなら ''。 */
function extractBgUrl(raw: string | undefined): string {
  if (!raw || raw === 'none') return '';
  const m = raw.match(/url\((['"]?)(.*?)\1\)/);
  return m ? m[2] : '';
}

/** 編集対象の画像。<img> 要素を最優先、無ければ background-image を持つ要素（liveTarget）。 */
type ImageTarget =
  | { mode: 'img'; el: HTMLImageElement }
  | { mode: 'bg'; el: HTMLElement };

export function ImageSection() {
  const liveTarget = usePreviewStore((s) => s.liveTarget);
  const projectId = usePreviewStore((s) => s.projectId);
  const applyStyleTo = usePreviewStore((s) => s.applyStyleTo);
  void usePreviewStore((s) => s.styleVersion);
  const [prompt, setPrompt] = useState('');
  const [generating, setGenerating] = useState(false);

  // 選択要素の周辺から <img> を探す（自身・子孫）。無ければ背景画像 div を対象にする。
  const target = useMemo<ImageTarget | null>(() => {
    const imgEl = findMediaInScope(liveTarget, 'img') as HTMLImageElement | null;
    if (imgEl) return { mode: 'img', el: imgEl };
    if (liveTarget) {
      const el = liveTarget as HTMLElement;
      const win = el.ownerDocument?.defaultView;
      const bg = win ? win.getComputedStyle(el).backgroundImage : '';
      if (extractBgUrl(bg)) return { mode: 'bg', el };
    }
    return null;
  }, [liveTarget]);

  const isBg = target?.mode === 'bg';
  const el = target?.el ?? null;

  const cs = useMemo(() => {
    if (!el) return null;
    const win = el.ownerDocument?.defaultView;
    return win ? win.getComputedStyle(el) : null;
  }, [el]);

  const currentSrc = isBg
    ? extractBgUrl(cs?.backgroundImage)
    : (el?.getAttribute('src') || '');
  const currentAlt = (!isBg && el?.getAttribute('alt')) || '';
  const [altDraft, setAltDraft] = useState(currentAlt);

  useEffect(() => {
    setAltDraft(currentAlt);
  }, [currentAlt]);

  // focal point: img は object-position、bg は background-position
  const focalPoint = parseObjectPosition(
    isBg ? cs?.backgroundPosition : cs?.objectPosition
  );

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

  // 新しい画像 URL を反映。img は src 属性、bg は background-image スタイルに書く。
  // どちらも writeback で JSX に永続化される（属性 or style={{}} としてマージ）。
  const applyUrl = (url: string) => {
    if (!el) return;
    if (isBg) {
      // url() は引用符なし（Supabase URL は特殊文字を含まないのでエスケープ不要）
      applyStyleTo(el, 'background-image', `url(${url})`);
    } else {
      el.setAttribute('src', url);
      queueInspectorEdit({ target: el, attrsOnly: { src: url } });
    }
  };

  const applyAlt = () => {
    if (!el || isBg) return;
    el.setAttribute('alt', altDraft);
    queueInspectorEdit({ target: el, attrsOnly: { alt: altDraft } });
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
      applyUrl(data.url);
      setPrompt('');
    } catch (e) {
      console.error('regen failed', e);
      alert('画像の再生成に失敗しました');
    } finally {
      setGenerating(false);
    }
  };

  // focal point / object-fit は対象要素に直接書く。applyStyleTo が styleVersion を
  // bump するので、このコンポーネントも再描画される
  const onFocalChange = (v: FocalPoint) => {
    if (!el) return;
    applyStyleTo(
      el,
      isBg ? 'background-position' : 'object-position',
      `${v.x.toFixed(1)}% ${v.y.toFixed(1)}%`
    );
  };

  const setFit = (v: string) => {
    if (!el) return;
    applyStyleTo(el, isBg ? 'background-size' : 'object-fit', v);
  };

  // overlay（暗転/ぼかし）は <img> 自体に CSS filter で適用する。
  // bg-image div では filter が子要素（テキスト等）も暗くしてしまうため出さない。
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
    if (!el) return;
    const parts: string[] = [];
    if (next.darken > 0) parts.push(`brightness(${((100 - next.darken) / 100).toFixed(2)})`);
    if (next.blur > 0) parts.push(`blur(${next.blur}px)`);
    applyStyleTo(el, 'filter', parts.join(' ') || 'none');
  };

  if (!target) return null;

  return (
    <section className="flex flex-col gap-3">
      <SectionHeader title={isBg ? 'Background Image' : 'Image'} />

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
          {isBg ? (
            <div className="text-[10px] text-muted-foreground">
              背景画像（&lt;{el?.tagName.toLowerCase()}&gt; の background-image）
            </div>
          ) : (
            <input
              type="text"
              value={altDraft}
              onChange={(e) => setAltDraft(e.target.value)}
              onBlur={applyAlt}
              placeholder="alt 説明"
              className="w-full rounded border border-border bg-input/30 px-1.5 py-0.5 text-xs"
            />
          )}
        </div>
      </div>

      {/* object-fit(img) / background-size(bg) + focal point */}
      <SelectInput
        label={isBg ? 'background-size' : 'object-fit'}
        value={(isBg ? cs?.backgroundSize : cs?.objectFit) || (isBg ? 'cover' : 'fill')}
        options={
          isBg
            ? [
                { value: 'cover', label: 'cover' },
                { value: 'contain', label: 'contain' },
                { value: 'auto', label: 'auto' },
                { value: '100% 100%', label: 'stretch' },
              ]
            : [
                { value: 'cover', label: 'cover' },
                { value: 'contain', label: 'contain' },
                { value: 'fill', label: 'fill' },
                { value: 'scale-down', label: 'scale-down' },
                { value: 'none', label: 'none' },
              ]
        }
        onChange={setFit}
      />
      <FocalPointPad
        value={focalPoint}
        onChange={onFocalChange}
        backgroundSrc={currentSrc}
      />

      {/* Overlay（画像に直接かかる暗転/ぼかし）— img のみ */}
      {!isBg && (
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
      )}

      {/* 再生成 */}
      <div className="flex flex-col gap-1.5 rounded-md border border-border bg-muted/20 p-2">
        <label className="text-xs text-muted-foreground">
          {isBg ? '背景画像を再生成' : '画像を再生成'}
        </label>
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
        onSelect={(it) => applyUrl(it.url)}
      />
    </section>
  );
}
