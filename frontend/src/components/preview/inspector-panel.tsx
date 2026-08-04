'use client';

import { useEffect, useMemo, useState } from 'react';
import { Check, Trash2 } from 'lucide-react';

import { usePreviewStore, type SelectedElement } from '@/stores/preview-store';
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

/** computedStyle の読み取り（live DOM ではなく選択 snapshot から）。 */
type Computed = Record<string, string>;

/** 選択中要素のミニプレビュー（snapshot から描画）。 */
function ElementPreview({ el }: { el: SelectedElement | null }) {
  void usePreviewStore((s) => s.styleVersion);
  if (!el) return null;

  if (el.media?.kind === 'img') {
    return (
      <div className="overflow-hidden rounded border border-border bg-muted/40">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={el.media.src || ''} alt="" className="h-32 w-full object-cover" />
      </div>
    );
  }
  if (el.media?.kind === 'video') {
    return (
      <div className="overflow-hidden rounded border border-border bg-muted/40">
        <video src={el.media.src || ''} className="h-32 w-full object-cover" muted autoPlay loop playsInline />
      </div>
    );
  }
  const cs = el.computedStyles || {};
  const bgColor = cs.backgroundColor || 'rgba(0,0,0,0)';
  const color = cs.color || 'inherit';
  const text = (el.text || '').trim().replace(/\s+/g, ' ').slice(0, 80);
  const tag = el.tagName.toLowerCase();
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

/** 選択中要素の computedStyle スナップショットを返す。 */
function useComputed(): Computed | null {
  const selectedElement = usePreviewStore((s) => s.selectedElement);
  void usePreviewStore((s) => s.styleVersion);
  return useMemo(() => selectedElement?.computedStyles ?? null, [selectedElement]);
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
  const bg = el.computedStyles?.backgroundImage || '';
  const hasBgImage = !!bg && bg !== 'none' && bg.includes('url(');
  return {
    isText: TEXT_TAGS.has(t),
    isImage: t === 'img' || hasBgImage,
    isVideo: t === 'video',
    isContainer: !TEXT_TAGS.has(t) && t !== 'img' && t !== 'video' && !hasBgImage,
  };
}

function TypographySection() {
  const cs = useComputed();
  const setLive = usePreviewStore((s) => s.setLiveStyle);
  if (!cs) return null;

  const fontSize = parseNumericValue(cs.fontSize) ?? 16;
  const lineHeight = cs.lineHeight === 'normal' ? 1.4 : parseNumericValue(cs.lineHeight) ?? 1.4;
  const letterSpacing = parseNumericValue(cs.letterSpacing) ?? 0;
  const fontWeight = parseNumericValue(cs.fontWeight) ?? 400;

  return (
    <section className="flex flex-col gap-2">
      <SectionHeader title="Typography" />
      <SliderInput label="font-size" value={fontSize} min={10} max={96} unit="px" onChange={(v) => setLive('font-size', `${v}px`)} />
      <SliderInput label="font-weight" value={fontWeight} min={100} max={900} step={100} onChange={(v) => setLive('font-weight', String(v))} />
      <SliderInput label="line-height" value={typeof lineHeight === 'number' ? lineHeight : 1.4} min={1} max={3} step={0.05} onChange={(v) => setLive('line-height', String(v))} />
      <SliderInput label="letter-spacing" value={letterSpacing} min={-5} max={20} step={0.5} unit="px" onChange={(v) => setLive('letter-spacing', `${v}px`)} />
      <ColorInput label="color" value={cs.color || ''} onChange={(v) => setLive('color', v)} />
      <ToggleGroup
        label="text-align"
        value={cs.textAlign || 'left'}
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
        value={cs.fontFamily || ''}
        options={[
          { value: '"Noto Sans JP", "Hiragino Kaku Gothic ProN", "Yu Gothic", "Meiryo", sans-serif', label: '吉川 本文' },
          { value: '"Zen Kaku Gothic New", "Noto Sans JP", sans-serif', label: '吉川 見出し' },
          { value: '"Space Grotesk", sans-serif', label: '吉川 英字' },
          { value: 'system-ui, sans-serif', label: 'System Sans' },
          { value: 'ui-serif, Georgia, serif', label: 'Serif' },
          { value: 'ui-monospace, Menlo, monospace', label: 'Mono' },
        ]}
        onChange={(v) => setLive('font-family', v)}
      />
    </section>
  );
}

/**
 * Text is edited in the parent panel, not by requiring a precise double-click
 * inside a cross-origin iframe. This also works for headings containing <br>
 * and other text elements which are not DOM leaves.
 */
function TextContentSection() {
  const selectedElement = usePreviewStore((s) => s.selectedElement);
  if (!selectedElement?.elementKey) return null;
  return (
    <TextContentEditor
      key={selectedElement.refId}
      elementKey={selectedElement.elementKey}
      initialText={selectedElement.text || ''}
    />
  );
}

function TextContentEditor({ elementKey, initialText }: { elementKey: string; initialText: string }) {
  const commitText = usePreviewStore((s) => s.commitText);
  const [value, setValue] = useState(initialText);
  const save = () => commitText(elementKey, value);

  return (
    <section className="flex flex-col gap-2">
      <SectionHeader title="Text" />
      <textarea
        value={value}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
            event.preventDefault();
            save();
          }
        }}
        rows={Math.min(10, Math.max(3, value.split('\n').length + 1))}
        className="w-full resize-y rounded-md border border-input bg-background px-2 py-1.5 text-sm leading-5 outline-none focus:ring-2 focus:ring-ring"
        aria-label="テキストを編集"
      />
      <button
        type="button"
        onClick={save}
        className="rounded-md bg-primary px-2.5 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
      >
        テキストを反映
      </button>
    </section>
  );
}

function BoxSection() {
  const cs = useComputed();
  const setLive = usePreviewStore((s) => s.setLiveStyle);
  if (!cs) return null;

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

  return (
    <section className="flex flex-col gap-2">
      <SectionHeader title="Box" />
      <SliderInput label="width" value={Math.round(width)} min={0} max={1600} unit="px" onChange={(v) => setLive('width', `${v}px`, true)} />
      <SliderInput label="height" value={Math.round(height)} min={0} max={1200} unit="px" onChange={(v) => setLive('height', `${v}px`, true)} />
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
        onChange={(v) => setLive('aspect-ratio', v)}
      />
      <SliderInput label="padding-top" value={paddingTop} min={0} max={120} unit="px" onChange={(v) => setLive('padding-top', `${v}px`)} />
      <SliderInput label="padding-right" value={paddingRight} min={0} max={120} unit="px" onChange={(v) => setLive('padding-right', `${v}px`)} />
      <SliderInput label="padding-bottom" value={paddingBottom} min={0} max={120} unit="px" onChange={(v) => setLive('padding-bottom', `${v}px`)} />
      <SliderInput label="padding-left" value={paddingLeft} min={0} max={120} unit="px" onChange={(v) => setLive('padding-left', `${v}px`)} />
      <SliderInput label="margin-top" value={marginTop} min={0} max={120} unit="px" onChange={(v) => setLive('margin-top', `${v}px`)} />
      <SliderInput label="margin-bottom" value={marginBottom} min={0} max={120} unit="px" onChange={(v) => setLive('margin-bottom', `${v}px`)} />
      <SliderInput label="border-radius" value={radius} min={0} max={60} unit="px" onChange={(v) => setLive('border-radius', `${v}px`)} />
      <SliderInput label="border-width" value={borderWidth} min={0} max={12} unit="px" onChange={(v) => setLive('border-width', `${v}px`)} />
      {borderWidth > 0 && (
        <ColorInput label="border-color" value={cs.borderTopColor || ''} onChange={(v) => setLive('border-color', v)} />
      )}
      <SliderInput label="opacity" value={opacity} min={0} max={1} step={0.05} onChange={(v) => setLive('opacity', String(v))} />
      <ColorInput label="background" value={cs.backgroundColor || ''} onChange={(v) => setLive('background-color', v)} />
    </section>
  );
}

export function InspectorPanel() {
  const selectedElement = usePreviewStore((s) => s.selectedElement);
  const clearSelection = usePreviewStore((s) => s.clearSelection);
  const resetElementEdits = usePreviewStore((s) => s.resetElementEdits);
  const deleteSelectedElement = usePreviewStore((s) => s.deleteSelectedElement);

  const [confirmDelete, setConfirmDelete] = useState(false);
  useEffect(() => {
    if (!confirmDelete) return;
    const t = window.setTimeout(() => setConfirmDelete(false), 4000);
    return () => window.clearTimeout(t);
  }, [confirmDelete]);
  useEffect(() => {
    setConfirmDelete(false);
  }, [selectedElement?.refId]);

  // 削除候補（cross-origin: snapshot のキー/祖先から判定）:
  //   1) 選択要素自身に @data-edit-id があればそれ
  //   2) 祖先(snapshot.ancestors)に @data-edit-id があれば最近接のそれ
  const deleteCandidate = useMemo<{ key: string; tagName: string; mode: 'self' | 'ancestor' } | null>(() => {
    if (selectedElement?.elementKey?.startsWith('@')) {
      return { key: selectedElement.elementKey, tagName: selectedElement.tagName, mode: 'self' };
    }
    const anc = selectedElement?.ancestors?.find((a) => a.elementKey?.startsWith('@'));
    if (anc?.elementKey) return { key: anc.elementKey, tagName: anc.tagName, mode: 'ancestor' };
    return null;
  }, [selectedElement?.refId, selectedElement?.elementKey, selectedElement?.tagName, selectedElement?.ancestors]);

  const canDelete = !!deleteCandidate;

  const handleDelete = async () => {
    if (!canDelete || !deleteCandidate) return;
    if (!confirmDelete) {
      setConfirmDelete(true);
      return;
    }
    setConfirmDelete(false);
    await deleteSelectedElement(
      deleteCandidate.mode === 'self' ? undefined : { elementKey: deleteCandidate.key, tagName: deleteCandidate.tagName }
    );
  };

  const deleteTooltip = !canDelete
    ? 'この要素にも祖先にも data-edit-id を持つ要素がないため削除できません'
    : deleteCandidate?.mode === 'ancestor'
      ? `祖先 <${deleteCandidate.tagName}> を削除します`
      : confirmDelete
        ? 'もう一度クリックで完全削除（Cmd+Z で復元可能）'
        : '要素を削除（Cmd+Z で復元可能）';

  if (!selectedElement) {
    return (
      <div className="flex h-full w-[280px] shrink-0 flex-col border-l border-border bg-background">
        <div className="border-b border-border px-3 py-2 text-sm font-semibold">Inspector</div>
        <div className="flex flex-1 items-center justify-center p-4 text-center text-xs text-muted-foreground">
          要素をクリックして編集を開始
        </div>
      </div>
    );
  }

  const { isText, isImage, isVideo } = classifyElement(selectedElement);

  return (
    <div className="flex h-full w-[280px] shrink-0 flex-col border-l border-border bg-background">
      <div className="flex flex-col gap-1.5 border-b border-border px-3 py-2">
        <div className="flex items-center gap-1">
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
          <button onClick={clearSelection} className="rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground" title="選択解除">
            ×
          </button>
        </div>
        <button
          type="button"
          onClick={handleDelete}
          disabled={!canDelete}
          title={deleteTooltip}
          className={`flex w-full items-center justify-center gap-1.5 rounded-md border px-2 py-1.5 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
            confirmDelete
              ? 'border-red-600 bg-red-600 text-white hover:bg-red-700'
              : !canDelete
                ? 'border-border text-muted-foreground'
                : 'border-red-500/30 text-red-600 hover:border-red-500 hover:bg-red-500/10'
          }`}
        >
          <Trash2 className="h-3.5 w-3.5" />
          {confirmDelete
            ? '本当に削除？ もう一度クリック'
            : !canDelete
              ? '削除不可（編集IDが無い）'
              : deleteCandidate?.mode === 'ancestor'
                ? `親 <${deleteCandidate.tagName}> を削除`
                : 'この要素を削除（Cmd+Zで復元）'}
        </button>
      </div>
      <div className="flex-1 space-y-4 overflow-y-auto p-3">
        <ElementPreview el={selectedElement} />
        {isText && <TextContentSection />}
        {isText && <TypographySection />}
        {isImage && <ImageSection />}
        {isVideo && <VideoSection />}
        <BoxSection />
      </div>
      <div className="flex items-center gap-1 border-t border-border px-3 py-1.5 text-[10px] text-muted-foreground">
        <Check className="h-3 w-3 text-green-500" />
        <span>編集は自動保存されます（Cmd+Z で巻き戻し）</span>
        <button
          type="button"
          onClick={resetElementEdits}
          className="ml-auto rounded border border-border px-1.5 py-0.5 text-[10px] text-muted-foreground hover:bg-muted hover:text-foreground"
          title="この要素の編集を全てリセット"
        >
          Reset
        </button>
      </div>
    </div>
  );
}
