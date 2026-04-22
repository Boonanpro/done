'use client';

import { useMemo } from 'react';
import { Check } from 'lucide-react';

import { usePreviewStore, findMediaInScope, type SelectedElement } from '@/stores/preview-store';

/** 選択中要素のミニプレビュー。「選択要素そのもの」を表示する。
 *  - 選択要素が <img>/<video> → そのメディアを表示
 *  - それ以外 → 背景色+テキストで色ブロック表示（たとえ中に img/video が
 *    含まれていても、今編集してるのは wrapper なので wrapper を見せる）*/
function ElementPreview({ target }: { target: Element | null }) {
  void usePreviewStore((s) => s.styleVersion);
  if (!target) return null;

  if (target.tagName === 'IMG') {
    const src = (target as HTMLImageElement).getAttribute('src') || '';
    return (
      <div className="overflow-hidden rounded border border-border bg-muted/40">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={src} alt="" className="h-32 w-full object-cover" />
      </div>
    );
  }

  if (target.tagName === 'VIDEO') {
    const src = (target as HTMLVideoElement).getAttribute('src') || '';
    return (
      <div className="overflow-hidden rounded border border-border bg-muted/40">
        <video
          src={src}
          className="h-32 w-full object-cover"
          muted
          autoPlay
          loop
          playsInline
        />
      </div>
    );
  }

  // それ以外（wrapper / テキスト / カード / セクション 等）
  const win = (target as HTMLElement).ownerDocument?.defaultView;
  const cs = win ? win.getComputedStyle(target) : null;
  const bgColor = cs?.backgroundColor || 'rgba(0,0,0,0)';
  const color = cs?.color || 'inherit';
  const text = (target.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 80);
  const tag = target.tagName.toLowerCase();

  return (
    <div
      className="flex min-h-[80px] items-center justify-center overflow-hidden rounded border border-border p-3 text-center"
      style={{ backgroundColor: bgColor, color }}
    >
      <span className="line-clamp-3 text-xs">
        {text || <span className="font-mono opacity-60">&lt;{tag}&gt;</span>}
      </span>
    </div>
  );
}
import {
  SliderInput,
  ColorInput,
  SelectInput,
  ToggleGroup,
  SectionHeader,
  parseNumericValue,
} from './inspector/controls';
import { ImageSection } from './inspector/image-section';
import { VideoSection } from './inspector/video-section';

/** 要素の computed style を取得 */
function useComputedStyle(): CSSStyleDeclaration | null {
  const liveTarget = usePreviewStore((s) => s.liveTarget);
  return useMemo(() => {
    if (!liveTarget) return null;
    const win = (liveTarget as HTMLElement).ownerDocument?.defaultView;
    return win ? win.getComputedStyle(liveTarget) : null;
  }, [liveTarget]);
}

const TEXT_TAGS = new Set([
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'p', 'span', 'a', 'li', 'label', 'button', 'strong', 'em',
  'td', 'th', 'figcaption',
]);

function classifyElement(el: SelectedElement | null): {
  isText: boolean;
  isImage: boolean;
  isVideo: boolean;
  isContainer: boolean;
} {
  if (!el) return { isText: false, isImage: false, isVideo: false, isContainer: false };
  const t = el.tagName;
  // 厳密: target 自身が img/video の時だけ。wrapper が中に持っていても扱わない
  return {
    isText: TEXT_TAGS.has(t),
    isImage: t === 'img',
    isVideo: t === 'video',
    isContainer: !TEXT_TAGS.has(t) && t !== 'img' && t !== 'video',
  };
}

function TypographySection() {
  const cs = useComputedStyle();
  const setLive = usePreviewStore((s) => s.setLiveStyle);
  void usePreviewStore((s) => s.styleVersion);
  if (!cs) return null;

  const fontSize = parseNumericValue(cs.fontSize) ?? 16;
  const lineHeight =
    cs.lineHeight === 'normal' ? 1.4 : parseNumericValue(cs.lineHeight) ?? 1.4;
  const letterSpacing = parseNumericValue(cs.letterSpacing) ?? 0;
  const fontWeight = parseNumericValue(cs.fontWeight) ?? 400;

  return (
    <section className="flex flex-col gap-2">
      <SectionHeader title="Typography" />
      <SliderInput
        label="font-size"
        value={fontSize}
        min={10}
        max={96}
        unit="px"
        onChange={(v) => setLive('font-size', `${v}px`)}
      />
      <SliderInput
        label="font-weight"
        value={fontWeight}
        min={100}
        max={900}
        step={100}
        onChange={(v) => setLive('font-weight', String(v))}
      />
      <SliderInput
        label="line-height"
        value={typeof lineHeight === 'number' ? lineHeight : 1.4}
        min={1}
        max={3}
        step={0.05}
        onChange={(v) => setLive('line-height', String(v))}
      />
      <SliderInput
        label="letter-spacing"
        value={letterSpacing}
        min={-5}
        max={20}
        step={0.5}
        unit="px"
        onChange={(v) => setLive('letter-spacing', `${v}px`)}
      />
      <ColorInput
        label="color"
        value={cs.color}
        onChange={(v) => setLive('color', v)}
      />
      <ToggleGroup
        label="text-align"
        value={cs.textAlign}
        options={[
          { value: 'left', label: 'L' },
          { value: 'center', label: 'C' },
          { value: 'right', label: 'R' },
          { value: 'justify', label: 'J' },
        ]}
        onChange={(v) => setLive('text-align', v)}
      />
      <SelectInput
        label="font-family"
        value={cs.fontFamily}
        options={[
          { value: 'system-ui, sans-serif', label: 'System Sans' },
          { value: 'ui-serif, Georgia, serif', label: 'Serif' },
          { value: 'ui-monospace, Menlo, monospace', label: 'Mono' },
        ]}
        onChange={(v) => setLive('font-family', v)}
      />
    </section>
  );
}

function BoxSection() {
  const cs = useComputedStyle();
  const setLive = usePreviewStore((s) => s.setLiveStyle);
  const liveTarget = usePreviewStore((s) => s.liveTarget);
  const applyStyleTo = usePreviewStore((s) => s.applyStyleTo);
  // style 変更の度に再描画するためのバージョン（void で購読のみ）
  void usePreviewStore((s) => s.styleVersion);
  if (!cs) return null;

  // サイズ変更時、wrapper の aspect-ratio が効いていると width/height を
  // 片方だけ動かしても他方が勝手に追従してしまう。Tailwind の aspect-video
  // クラス等が class 経由で効くので、computedStyle で判定 → 常に auto で上書き。
  const ensureCoverOnMedia = () => {
    if (!liveTarget) return;
    const win = (liveTarget as HTMLElement).ownerDocument?.defaultView;
    const cs = win ? win.getComputedStyle(liveTarget) : null;
    if (cs && cs.aspectRatio && cs.aspectRatio !== 'auto') {
      applyStyleTo(liveTarget, 'aspect-ratio', 'auto', true);
    }
    const media =
      findMediaInScope(liveTarget, 'video') ||
      findMediaInScope(liveTarget, 'img');
    if (!media) return;
    applyStyleTo(media, 'width', '100%', true);
    applyStyleTo(media, 'height', '100%', true);
    const mcs = media.ownerDocument?.defaultView?.getComputedStyle(media);
    const currentFit = mcs?.objectFit || 'fill';
    if (currentFit === 'fill' || currentFit === 'none') {
      applyStyleTo(media, 'object-fit', 'cover');
    }
    // media の aspect-ratio も解除（<video> 等は intrinsic aspect が効くため）
    if (mcs && mcs.aspectRatio && mcs.aspectRatio !== 'auto') {
      applyStyleTo(media, 'aspect-ratio', 'auto', true);
    }
  };

  const width = parseNumericValue(cs.width) ?? 0;
  const height = parseNumericValue(cs.height) ?? 0;
  const paddingTop = parseNumericValue(cs.paddingTop) ?? 0;
  const paddingRight = parseNumericValue(cs.paddingRight) ?? 0;
  const paddingBottom = parseNumericValue(cs.paddingBottom) ?? 0;
  const paddingLeft = parseNumericValue(cs.paddingLeft) ?? 0;
  const marginTop = parseNumericValue(cs.marginTop) ?? 0;
  const marginBottom = parseNumericValue(cs.marginBottom) ?? 0;
  const radius = parseNumericValue(cs.borderTopLeftRadius) ?? 0;
  const borderWidth = parseNumericValue(cs.borderTopWidth) ?? 0;
  const opacity = parseNumericValue(cs.opacity) ?? 1;

  // 親幅を max とする（レスポンシブに無茶な指定を避けるため）
  const parentWidth =
    (liveTarget as HTMLElement | null)?.parentElement?.clientWidth || 1600;
  const parentHeight =
    (liveTarget as HTMLElement | null)?.parentElement?.clientHeight || 1200;

  return (
    <section className="flex flex-col gap-2">
      <SectionHeader title="Box" />
      <SliderInput
        label="width"
        value={Math.round(width)}
        min={0}
        max={Math.max(parentWidth, 1600)}
        unit="px"
        onChange={(v) => {
          setLive('width', `${v}px`, true);
          ensureCoverOnMedia();
        }}
      />
      <SliderInput
        label="height"
        value={Math.round(height)}
        min={0}
        max={Math.max(parentHeight, 1200)}
        unit="px"
        onChange={(v) => {
          setLive('height', `${v}px`, true);
          ensureCoverOnMedia();
        }}
      />
      <SelectInput
        label="aspect-ratio"
        value={cs.aspectRatio || 'auto'}
        options={[
          { value: 'auto', label: 'auto' },
          { value: '16 / 9', label: '16:9' },
          { value: '4 / 3', label: '4:3' },
          { value: '3 / 2', label: '3:2' },
          { value: '1 / 1', label: '1:1' },
          { value: '3 / 4', label: '3:4' },
          { value: '9 / 16', label: '9:16' },
        ]}
        onChange={(v) => {
          setLive('aspect-ratio', v);
          ensureCoverOnMedia();
        }}
      />
      <SliderInput
        label="padding-top"
        value={paddingTop}
        min={0}
        max={120}
        unit="px"
        onChange={(v) => setLive('padding-top', `${v}px`)}
      />
      <SliderInput
        label="padding-right"
        value={paddingRight}
        min={0}
        max={120}
        unit="px"
        onChange={(v) => setLive('padding-right', `${v}px`)}
      />
      <SliderInput
        label="padding-bottom"
        value={paddingBottom}
        min={0}
        max={120}
        unit="px"
        onChange={(v) => setLive('padding-bottom', `${v}px`)}
      />
      <SliderInput
        label="padding-left"
        value={paddingLeft}
        min={0}
        max={120}
        unit="px"
        onChange={(v) => setLive('padding-left', `${v}px`)}
      />
      <SliderInput
        label="margin-top"
        value={marginTop}
        min={0}
        max={120}
        unit="px"
        onChange={(v) => setLive('margin-top', `${v}px`)}
      />
      <SliderInput
        label="margin-bottom"
        value={marginBottom}
        min={0}
        max={120}
        unit="px"
        onChange={(v) => setLive('margin-bottom', `${v}px`)}
      />
      <SliderInput
        label="border-radius"
        value={radius}
        min={0}
        max={60}
        unit="px"
        onChange={(v) => setLive('border-radius', `${v}px`)}
      />
      <SliderInput
        label="border-width"
        value={borderWidth}
        min={0}
        max={12}
        unit="px"
        onChange={(v) => setLive('border-width', `${v}px`)}
      />
      {borderWidth > 0 && (
        <ColorInput
          label="border-color"
          value={cs.borderTopColor}
          onChange={(v) => setLive('border-color', v)}
        />
      )}
      <SliderInput
        label="opacity"
        value={opacity}
        min={0}
        max={1}
        step={0.05}
        onChange={(v) => setLive('opacity', String(v))}
      />
      <ColorInput
        label="background"
        value={cs.backgroundColor}
        onChange={(v) => setLive('background-color', v)}
      />
    </section>
  );
}

export function InspectorPanel() {
  // Hooks は必ず条件分岐より先に全部呼ぶ（React の Rules of Hooks）
  const selectedElement = usePreviewStore((s) => s.selectedElement);
  const liveTarget = usePreviewStore((s) => s.liveTarget);
  const clearSelection = usePreviewStore((s) => s.clearSelection);

  if (!selectedElement) {
    return (
      <div className="flex h-full w-[280px] shrink-0 flex-col border-l border-border bg-background">
        <div className="border-b border-border px-3 py-2 text-sm font-semibold">
          Inspector
        </div>
        <div className="flex flex-1 items-center justify-center p-4 text-center text-xs text-muted-foreground">
          要素をクリックして編集を開始
        </div>
      </div>
    );
  }

  const { isText, isImage, isVideo } = classifyElement(selectedElement);

  return (
    <div className="flex h-full w-[280px] shrink-0 flex-col border-l border-border bg-background">
      <div className="flex items-center gap-1 border-b border-border px-3 py-2">
        <span className="rounded bg-primary/15 px-1.5 py-0.5 font-mono text-xs font-medium text-primary">
          @{selectedElement.refId}
        </span>
        <span className="truncate text-xs text-muted-foreground">
          &lt;{selectedElement.tagName}&gt;
          {selectedElement.text ? ` "${selectedElement.text.slice(0, 18)}"` : ''}
        </span>
        <span className="ml-auto shrink-0 rounded bg-muted px-1 font-mono text-[10px] text-muted-foreground">
          {Math.round(selectedElement.rect.width)}×{Math.round(selectedElement.rect.height)}
        </span>
        <button
          onClick={clearSelection}
          className="rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
          title="選択解除"
        >
          ×
        </button>
      </div>
      <div className="flex-1 space-y-4 overflow-y-auto p-3">
        <ElementPreview target={liveTarget} />
        {isText && <TypographySection />}
        {isImage && <ImageSection />}
        {isVideo && <VideoSection />}
        <BoxSection />
      </div>
      <div className="flex items-center gap-1 border-t border-border px-3 py-1.5 text-[10px] text-muted-foreground">
        <Check className="h-3 w-3 text-green-500" />
        <span>編集は自動保存されます</span>
      </div>
    </div>
  );
}
