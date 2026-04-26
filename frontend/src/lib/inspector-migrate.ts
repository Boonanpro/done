/**
 * 旧形式 (v1) → 新形式 (v2) 移行
 *
 * v1: inspector_overrides.attrs に { html, text } のフリーフォーム
 *     - 部分テキスト装飾は <span data-dan-edit="1" style="..."> として html に埋め込まれていた
 *     - text と html の両方が併存する場合があった（最近のパッチで衝突）
 * v2: { v:2, text, blockStyle, spans, extraAttrs }
 *
 * 既存の override を読み込むときに on-the-fly で v2 化する。
 * 失敗時は null を返す → 呼び出し側は古い形式のまま扱う or 編集無効化を選ぶ。
 */

import type { EditModel, InlineSpan, CSSStyle } from './inspector-model';
import { emptyModel } from './inspector-model';

interface RawOverride {
  styles?: Record<string, string> | null;
  attrs?: Record<string, unknown> | null;
}

/**
 * inspector_overrides 1 行分を EditModel に正規化する。
 * - styles → blockStyle
 * - attrs.v == 2 → そのまま v2 として読む
 * - attrs.html → パースして spans に分解
 * - attrs.text → text フィールドへ
 * - attrs.href / src 等 → extraAttrs
 */
export function normalizeToModel(raw: RawOverride): EditModel | null {
  const model = emptyModel();
  const styles = raw.styles || {};
  const attrs = raw.attrs || {};

  // blockStyle（要素全体の装飾）
  for (const [k, v] of Object.entries(styles)) {
    if (typeof v === 'string') model.blockStyle[k] = v;
  }

  // v2 で既に保存されている場合
  if (attrs['v'] === 2) {
    model.text = typeof attrs['text'] === 'string' ? (attrs['text'] as string) : null;
    model.spans = Array.isArray(attrs['spans']) ? (attrs['spans'] as InlineSpan[]) : [];
    if (attrs['blockStyle'] && typeof attrs['blockStyle'] === 'object') {
      Object.assign(model.blockStyle, attrs['blockStyle'] as CSSStyle);
    }
    if (attrs['extraAttrs'] && typeof attrs['extraAttrs'] === 'object') {
      Object.assign(model.attrs, attrs['extraAttrs'] as CSSStyle);
    }
    return model;
  }

  // v1: html があれば優先（spans 抽出が必要）、なければ text のみ
  const htmlField = typeof attrs['html'] === 'string' ? (attrs['html'] as string) : null;
  const textField = typeof attrs['text'] === 'string' ? (attrs['text'] as string) : null;

  if (htmlField) {
    const parsed = parseHtmlToSpans(htmlField);
    if (parsed) {
      model.text = parsed.text;
      model.spans = parsed.spans;
    } else {
      // パース失敗: text のみフォールバック
      model.text = textField;
    }
  } else if (textField !== null) {
    model.text = textField;
  }

  // その他の属性（href, src, alt など）
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'html' || k === 'text' || k === 'v' || k === 'spans' || k === 'blockStyle' || k === 'extraAttrs') {
      continue;
    }
    if (typeof v === 'string') {
      model.attrs[k] = v;
    }
  }

  return model;
}

/**
 * 旧形式の html 文字列をパースして text + spans に分解する。
 * - data-dan-edit="1" の span は装飾範囲として spans に変換
 * - data-dan-edit ではないネスト要素（br など）は text 側にプレーン化
 */
export function parseHtmlToSpans(html: string): { text: string; spans: InlineSpan[] } | null {
  if (typeof DOMParser === 'undefined') return null;
  try {
    const parser = new DOMParser();
    const doc = parser.parseFromString(`<div id="root">${html}</div>`, 'text/html');
    const root = doc.getElementById('root');
    if (!root) return null;

    const spans: InlineSpan[] = [];
    let textBuf = '';

    const walk = (node: Node, activeSpanIdx: number | null) => {
      if (node.nodeType === Node.TEXT_NODE) {
        textBuf += node.textContent ?? '';
        return;
      }
      if (node.nodeType !== Node.ELEMENT_NODE) return;

      const el = node as HTMLElement;
      const tag = el.tagName.toLowerCase();

      // <br> は改行に変換
      if (tag === 'br') {
        textBuf += '\n';
        return;
      }

      // dan-edit span は装飾として記録
      const isDanSpan = el.hasAttribute('data-dan-edit') && tag === 'span';
      if (isDanSpan) {
        const start = textBuf.length;
        const styleObj = parseInlineStyle(el.getAttribute('style') || '');
        const idx = spans.length;
        spans.push({ start, end: start, style: styleObj });
        for (const child of Array.from(el.childNodes)) {
          walk(child, idx);
        }
        spans[idx].end = textBuf.length;
        return;
      }

      // それ以外の要素: 子を再帰
      for (const child of Array.from(el.childNodes)) {
        walk(child, activeSpanIdx);
      }
    };

    for (const child of Array.from(root.childNodes)) {
      walk(child, null);
    }

    // 範囲が潰れた span は除外
    const valid = spans.filter((s) => s.end > s.start);
    return { text: textBuf, spans: valid };
  } catch {
    return null;
  }
}

function parseInlineStyle(s: string): CSSStyle {
  const out: CSSStyle = {};
  for (const part of s.split(';')) {
    const idx = part.indexOf(':');
    if (idx < 0) continue;
    const k = part.slice(0, idx).trim();
    const v = part.slice(idx + 1).trim().replace(/!important$/i, '').trim();
    if (k && v) out[k] = v;
  }
  return out;
}

/**
 * 「子の span に対する独立 override」を親に統合する。
 *
 * 実例:
 *   親 element_key: '.../h2[0]'             → text + spans
 *   子 element_key: '.../h2[0]>span[0]'    → 独立した装飾
 * のように 2 行に分裂しているケースを、親 1 行に集約する。
 *
 * @param rows 同じ slug の全 override 行
 * @returns 統合後の EditModel マップ（key = 親 element_key）と、削除すべき子 key リスト
 */
export interface RawRow {
  element_key: string;
  styles: Record<string, string> | null;
  attrs: Record<string, unknown> | null;
}

export function consolidateChildSpans(rows: RawRow[]): {
  models: Record<string, EditModel>;
  obsoleteKeys: string[];
} {
  const models: Record<string, EditModel> = {};
  const obsoleteKeys: string[] = [];

  // まず全行をモデル化
  const keyToRow: Record<string, RawRow> = {};
  for (const r of rows) {
    keyToRow[r.element_key] = r;
    const m = normalizeToModel(r);
    if (m) models[r.element_key] = m;
  }

  // span[N] 末尾の子 key を見つけ、親に span が存在するなら obsolete マーク
  for (const key of Object.keys(keyToRow)) {
    const m = key.match(/^(.+)>span\[\d+\]$/);
    if (!m) continue;
    const parentKey = m[1];
    if (!models[parentKey]) continue;
    if (models[parentKey].spans.length > 0) {
      // 親が既に spans を持っている → 子行は重複情報なので削除候補
      obsoleteKeys.push(key);
      delete models[key];
    }
  }

  return { models, obsoleteKeys };
}
