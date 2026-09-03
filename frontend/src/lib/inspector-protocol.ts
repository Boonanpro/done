/**
 * Inspector クロスオリジン通信プロトコル（親ダッシュボード ⇄ プレビューiframe）。
 *
 * 設計: docs/proposals/inspector_cross_origin.md
 *
 * 親(ダッシュボード)とiframe(成果物ランタイム)は同一オリジンとは限らないため、
 * 直接DOMアクセスではなく postMessage でやり取りする。本ファイルは両者が共有する
 * メッセージ型と origin 検証ヘルパの「契約」。送受信される値は全て JSON
 * シリアライズ可能（live Element / live Range は決して載せない）。
 *
 * このファイルは成果物ランタイムにも vendor 同期される（done-artifacts）。
 */

/** プロトコルのバージョン。後方互換性チェックに使う。 */
export const INSPECTOR_PROTOCOL_VERSION = 1 as const;

/** 全メッセージ共通のエンベロープ。`__dan_inspector` で他の postMessage と区別する。 */
export interface InspectorEnvelope<T = unknown> {
  /** 識別マーカー。これが無いメッセージは無視する。 */
  __dan_inspector: typeof INSPECTOR_PROTOCOL_VERSION;
  /** メッセージ種別。 */
  type: string;
  /** 種別ごとのペイロード。 */
  payload: T;
}

// ---------------------------------------------------------------------------
// 値オブジェクト（シリアライズ可能なスナップショット）
// ---------------------------------------------------------------------------

/** 要素の矩形（getBoundingClientRect のシリアライズ可能版）。 */
export interface SerializableRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** 祖先要素の軽量情報（パンくず/選択ドリル用）。 */
export interface AncestorInfo {
  tagName: string;
  className: string;
  elementKey: string | null;
}

/** メディア要素(img/video)の情報。 */
export interface MediaInfo {
  kind: 'img' | 'video';
  src: string | null;
  alt?: string | null;
  poster?: string | null;
  objectFit?: string | null;
  objectPosition?: string | null;
}

/**
 * 要素選択時に iframe → 親 へ渡すスナップショット。
 * 現行 preview-store の `selectedElement`（liveTarget を除く）に相当する。
 * パネルUIはこのスナップショットを読んで表示する（live DOM は読まない）。
 */
export interface SelectionSnapshot {
  /** この要素が属する成果物 slug（iframe が実際に表示している中身の slug）。
   *  保存/取得をこの slug に固定し、chat_artifact のラベルズレやハンドシェイク
   *  タイミングに依存しないようにする。 */
  slug: string;
  /** 論理識別子（`@<data-edit-id>` か DOMパスフォールバック）。 */
  elementKey: string;
  tagName: string;
  rect: SerializableRect;
  /** 表示用テキスト（編集対象のプレーンテキスト）。 */
  text: string;
  className: string;
  /** outerHTML の先頭スニペット（デバッグ/判定用）。 */
  outerHtmlSnippet: string;
  ancestors: AncestorInfo[];
  /** UI が必要とする computedStyle の抜粋（font-size, color, ... 必要分のみ）。 */
  computedStyles: Record<string, string>;
  /** Styling that belongs to only part of this sentence. */
  inlineSpans?: Array<{ start: number; end: number; style: Record<string, string> }>;
  /** 背景色（パネルのプレビュー用）。 */
  bgColor: string | null;
  /** インラインテキスト編集が可能な葉要素か。 */
  isTextLeaf: boolean;
  /** img/video の場合の情報。 */
  media?: MediaInfo;
}

/** 保存/適用される編集モデル（v2 EditModel の薄いミラー）。 */
export interface OverridePayload {
  elementKey: string;
  /** v2 EditModel（text/blockStyle/spans/attrs）。inspector-model の EditModel を JSON 化したもの。 */
  model?: unknown;
  /** 単発スタイル適用（スライダー連続操作など、model を組まない軽量経路）。 */
  styles?: Record<string, string>;
  /** 属性適用（src/alt/href 等）。 */
  attrs?: Record<string, string>;
}

/** 既存overrides一括投入用の1行（DB行のミラー）。 */
export interface OverrideRow {
  element_key: string;
  styles?: Record<string, string> | null;
  attrs?: Record<string, unknown> | null;
}

export type InspectorMode = 'off' | 'edit' | 'comment';

// ---------------------------------------------------------------------------
// iframe → 親 のメッセージ
// ---------------------------------------------------------------------------

export type IframeToParentMessage =
  | { type: 'inspector:ready'; payload: { slug: string } }
  | { type: 'inspector:selected'; payload: SelectionSnapshot }
  /** 複数選択（コメントモードで Ctrl/Cmd/Shift+クリック）。選択集合の全量を毎回送る。
   *  空配列 = 全解除。旧親はこの type を知らないので単に無視する（後方互換）。 */
  | { type: 'inspector:multi-selected'; payload: { snapshots: SelectionSnapshot[] } }
  | { type: 'inspector:hover'; payload: { elementKey: string | null; rect: SerializableRect | null } }
  | { type: 'inspector:text-drafted'; payload: { elementKey: string; text: string } }
  | { type: 'inspector:text-committed'; payload: { elementKey: string; text: string } }
  | { type: 'inspector:selection-range'; payload: { elementKey: string; start: number; end: number } | { elementKey: null } }
  | { type: 'inspector:reloaded'; payload: Record<string, never> };

// ---------------------------------------------------------------------------
// 親 → iframe のメッセージ
// ---------------------------------------------------------------------------

export type ParentToIframeMessage =
  | { type: 'inspector:set-mode'; payload: { mode: InspectorMode } }
  | { type: 'inspector:apply'; payload: OverridePayload }
  | { type: 'inspector:apply-overrides'; payload: { overrides: OverrideRow[] } }
  | { type: 'inspector:clear-selection'; payload: Record<string, never> }
  /** 親側UI（チップの×等）で選択集合が変わった時に iframe のハイライトを同期する。
   *  旧 iframe ランタイムはこの type を知らないので単に無視する（後方互換）。 */
  | { type: 'inspector:set-selection'; payload: { elementKeys: string[] } }
  | { type: 'inspector:request-snapshot'; payload: { elementKey: string } };

export type AnyInspectorMessage = IframeToParentMessage | ParentToIframeMessage;

// ---------------------------------------------------------------------------
// 送受信ヘルパ
// ---------------------------------------------------------------------------

/** メッセージを Inspector エンベロープで包む。 */
export function wrapInspectorMessage<M extends AnyInspectorMessage>(msg: M): InspectorEnvelope<M['payload']> {
  return { __dan_inspector: INSPECTOR_PROTOCOL_VERSION, type: msg.type, payload: msg.payload };
}

/** 受信データが Inspector エンベロープか判定する（型ガード）。 */
export function isInspectorEnvelope(data: unknown): data is InspectorEnvelope {
  return (
    typeof data === 'object' &&
    data !== null &&
    (data as InspectorEnvelope).__dan_inspector === INSPECTOR_PROTOCOL_VERSION &&
    typeof (data as InspectorEnvelope).type === 'string'
  );
}

/**
 * origin 許可判定。
 * - 同一オリジン（相対srcのローカル）は常に許可。
 * - localhost / LAN（127.*, 10.*, 192.168.*, 172.16-31.*, 100.*）は開発用に許可。
 * - 明示許可リスト（env や既知の配信オリジン）に一致すれば許可。
 *
 * @param origin 受信メッセージの event.origin
 * @param selfOrigin 自分の origin（typeof window 経由で渡す）
 * @param allowed 追加許可オリジン（NEXT_PUBLIC_SHARE_ORIGIN / ダッシュボードオリジン等）
 */
export function isAllowedInspectorOrigin(
  origin: string,
  selfOrigin: string,
  allowed: readonly string[] = [],
): boolean {
  if (!origin) return false;
  if (origin === selfOrigin) return true;
  for (const a of allowed) {
    if (a && origin === a.replace(/\/+$/, '')) return true;
  }
  try {
    const host = new URL(origin).hostname;
    if (
      host === 'localhost' ||
      host === '127.0.0.1' ||
      host === '0.0.0.0' ||
      /^10\./.test(host) ||
      /^192\.168\./.test(host) ||
      /^100\./.test(host) ||
      /^172\.(1[6-9]|2\d|3[01])\./.test(host)
    ) {
      return true;
    }
  } catch {
    return false;
  }
  return false;
}
