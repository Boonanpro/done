'use client';

import { useMemo } from 'react';
import { RefreshCw } from 'lucide-react';

import { usePreviewStore, type SelectedElement } from '@/stores/preview-store';
import {
  SliderInput,
  ColorInput,
  SelectInput,
  ToggleGroup,
  SectionHeader,
  parseNumericValue,
} from './inspector/controls';

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
          { value: cs.fontFamily, label: '（現在）' },
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
  if (!cs) return null;

  const paddingTop = parseNumericValue(cs.paddingTop) ?? 0;
  const paddingRight = parseNumericValue(cs.paddingRight) ?? 0;
  const paddingBottom = parseNumericValue(cs.paddingBottom) ?? 0;
  const paddingLeft = parseNumericValue(cs.paddingLeft) ?? 0;
  const radius = parseNumericValue(cs.borderTopLeftRadius) ?? 0;
  const borderWidth = parseNumericValue(cs.borderTopWidth) ?? 0;
  const opacity = parseNumericValue(cs.opacity) ?? 1;

  return (
    <section className="flex flex-col gap-2">
      <SectionHeader title="Box" />
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

function ImageSectionPlaceholder() {
  return (
    <section className="flex flex-col gap-2 rounded-md border border-dashed border-border p-3 text-xs text-muted-foreground">
      <SectionHeader title="Image" />
      <p>画像の focal point ドラッグ・過去版サイクルは次のアップデートで追加。</p>
    </section>
  );
}

function VideoSectionPlaceholder() {
  return (
    <section className="flex flex-col gap-2 rounded-md border border-dashed border-border p-3 text-xs text-muted-foreground">
      <SectionHeader title="Video" />
      <p>動画の focal point ドラッグ・再生コントロール・過去版サイクルは次のアップデートで追加。</p>
    </section>
  );
}

export function InspectorPanel() {
  const selectedElement = usePreviewStore((s) => s.selectedElement);
  const clearSelection = usePreviewStore((s) => s.clearSelection);
  const resetEdits = usePreviewStore((s) => s.resetElementEdits);
  const edits = usePreviewStore((s) => s.edits);

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
  const hasEdits = !!edits[selectedElement.refId];

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
        <button
          onClick={clearSelection}
          className="ml-auto rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
          title="選択解除"
        >
          ×
        </button>
      </div>
      <div className="flex-1 space-y-4 overflow-y-auto p-3">
        {isText && <TypographySection />}
        {isImage && <ImageSectionPlaceholder />}
        {isVideo && <VideoSectionPlaceholder />}
        <BoxSection />
      </div>
      {hasEdits && (
        <div className="flex items-center gap-2 border-t border-border p-2">
          <button
            onClick={resetEdits}
            className="flex items-center gap-1 rounded border border-border bg-background px-2 py-1 text-xs text-muted-foreground hover:bg-muted"
          >
            <RefreshCw className="h-3 w-3" />
            リセット
          </button>
          <button
            className="ml-auto flex items-center gap-1 rounded bg-primary px-3 py-1 text-xs font-medium text-primary-foreground hover:opacity-90"
            disabled
            title="次の更新で実装"
          >
            Apply to source（準備中）
          </button>
        </div>
      )}
    </div>
  );
}
