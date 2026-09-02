/**
 * 公開リビジョン（artifact_edit_releases.overrides）→ Editable コンポーネント入力。
 *
 * 配信ページは実行時に DB もネットワークも読まない。公開時にバックエンドが
 * `release.gen.json` として成果物ディレクトリに焼き込んだスナップショットを、
 * サーバーレンダリング時にこのモジュールでパースして React に渡す。
 * 初回 HTML の時点で最終状態が出るので、「古い表示 → 差し替え」は構造的に起きない。
 *
 * 対応する識別子は `@<editId>`（EditableText / data-edit-id）だけ。
 * `@auto:` や DOM パス形式は DOM が無いと解決できないため、公開 API 側が
 * 「公開ページに反映されないキー」として警告を返す（サイレントに捨てない）。
 */

import type { CSSStyle, EditModel, InlineSpan } from './inspector-model';

export type ReleaseOverrideRow = {
  styles?: CSSStyle | null;
  attrs?: Record<string, unknown> | null;
};

/** release.gen.json の中身。DB の overrides JSONB と同じ形。 */
export type ReleaseOverrides = Record<string, ReleaseOverrideRow>;

export interface EditableOverride {
  /** null なら本文は元のまま（スタイル・属性だけの編集）。 */
  text: string | null;
  spans: InlineSpan[];
  blockStyle: CSSStyle;
  extraAttrs: Record<string, string>;
}

/** テキストを span 装飾ごとの区間に分けた 1 区間。inspector-render.ts と同じ規則。 */
export interface TextSegment {
  text: string;
  style: CSSStyle;
}

/** `@<editId>` 形式で、かつ DOM 探索なしに解決できるキーだけを editId に写像する。 */
export function isRenderableKey(elementKey: string): boolean {
  return elementKey.startsWith('@') && !elementKey.startsWith('@auto:');
}

export function toEditableOverrides(
  release: ReleaseOverrides | null | undefined,
): Record<string, EditableOverride> {
  const out: Record<string, EditableOverride> = {};
  if (!release) return out;
  for (const [key, row] of Object.entries(release)) {
    if (!isRenderableKey(key) || !row || typeof row !== 'object') continue;
    const attrs = row.attrs || {};
    let model: EditModel | null = null;
    if (typeof attrs['model_v2'] === 'string') {
      try {
        model = JSON.parse(attrs['model_v2']) as EditModel;
      } catch {
        model = null;
      }
    }
    const blockStyle: CSSStyle = { ...(model?.blockStyle || {}) };
    // 旧 row では styles カラム側に全体装飾が入っている。blockStyle と同義。
    for (const [k, v] of Object.entries(row.styles || {})) {
      if (typeof v === 'string') blockStyle[k] = v;
    }
    const extraAttrs: Record<string, string> = {};
    for (const [k, v] of Object.entries(model?.attrs || {})) {
      if (typeof v === 'string') extraAttrs[k] = v;
    }
    out[key.slice(1)] = {
      text: typeof model?.text === 'string' ? model.text : null,
      spans: Array.isArray(model?.spans) ? model.spans : [],
      blockStyle,
      extraAttrs,
    };
  }
  return out;
}

/**
 * text + spans を「同一装飾の連続区間」列に変換する。
 * inspector-render.ts renderToHtml と同じセグメント規則（重なりはマージ、
 * 空 style の隣接区間は結合）。こちらは HTML 文字列ではなく React で
 * 描画するための構造を返す。
 */
export function computeTextSegments(text: string, spans: InlineSpan[]): TextSegment[] {
  if (!text) return [];
  if (!spans.length) return [{ text, style: {} }];

  const boundarySet = new Set<number>([0, text.length]);
  for (const s of spans) {
    boundarySet.add(Math.max(0, Math.min(text.length, s.start)));
    boundarySet.add(Math.max(0, Math.min(text.length, s.end)));
  }
  const boundaries = Array.from(boundarySet).sort((a, b) => a - b);

  const segments: { start: number; end: number; style: CSSStyle }[] = [];
  for (let i = 0; i < boundaries.length - 1; i++) {
    const start = boundaries[i];
    const end = boundaries[i + 1];
    if (start === end) continue;
    const style: CSSStyle = {};
    for (const s of spans) {
      if (s.start <= start && s.end >= end) {
        for (const [k, v] of Object.entries(s.style || {})) {
          if (typeof v === 'string' && v.length > 0) style[k] = v;
        }
      }
    }
    const last = segments[segments.length - 1];
    if (last && last.end === start && stylesEqual(last.style, style)) {
      last.end = end;
    } else {
      segments.push({ start, end, style });
    }
  }
  return segments.map((s) => ({ text: text.slice(s.start, s.end), style: s.style }));
}

function stylesEqual(a: CSSStyle, b: CSSStyle): boolean {
  const ak = Object.keys(a);
  if (ak.length !== Object.keys(b).length) return false;
  return ak.every((k) => a[k] === b[k]);
}

/** kebab-case の CSS プロパティ名を React の style オブジェクト用に変換する。 */
export function cssToReactStyle(style: CSSStyle): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(style)) {
    if (k.startsWith('--')) {
      out[k] = v;
    } else {
      out[k.replace(/-([a-z])/g, (_, c: string) => c.toUpperCase())] = v;
    }
  }
  return out;
}
