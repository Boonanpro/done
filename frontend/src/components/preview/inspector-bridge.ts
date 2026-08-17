/**
 * Inspector parent-side bridge（ダッシュボード側）。
 *
 * 設計: docs/proposals/inspector_cross_origin.md
 *
 * 旧 `iframe-inspector.ts` は親が iframe.contentDocument を直いじりしていた（同一オリジン
 * 限定）。本ブリッジは postMessage でプレビューiframe(別オリジン可)と通信する。
 * - 親 → iframe: set-mode / apply / apply-overrides / clear-selection / request-snapshot
 * - iframe → 親: ready / selected / text-committed / selection-range / hover / reloaded
 *
 * DOM を触らないので、iframe がどのオリジンでも動く。
 */
'use client';

import {
  wrapInspectorMessage,
  isInspectorEnvelope,
  isAllowedInspectorOrigin,
  type ParentToIframeMessage,
  type IframeToParentMessage,
  type SelectionSnapshot,
} from '@/lib/inspector-protocol';

type BridgeHandlers = {
  onReady?: (slug: string) => void;
  onSelected?: (snap: SelectionSnapshot) => void;
  /** 複数選択の全量更新（空配列=解除）。 */
  onMultiSelected?: (snapshots: SelectionSnapshot[]) => void;
  onTextDrafted?: (elementKey: string, text: string) => void;
  onTextCommitted?: (elementKey: string, text: string) => void;
  onSelectionRange?: (payload: { elementKey: string; start: number; end: number } | { elementKey: null }) => void;
  onReloaded?: () => void;
};

let currentIframe: HTMLIFrameElement | null = null;
let messageListener: ((e: MessageEvent) => void) | null = null;

/** iframe へコマンドを送る（現在アタッチ中の iframe が対象）。 */
export function sendToIframe(msg: ParentToIframeMessage): void {
  const win = currentIframe?.contentWindow;
  if (!win) return;
  try {
    // contentWindow は別オリジンでも postMessage 自体は可能（targetOrigin '*'）。
    // 送る内容はコマンドのみで機密を含まないため '*' で許容する。
    win.postMessage(wrapInspectorMessage(msg), '*');
  } catch {
    /* ignore */
  }
}

/**
 * ブリッジをアタッチする。iframe→親メッセージを受けて handlers に流す。
 * 返り値の detach で解除。
 */
export function attachInspectorBridge(
  iframe: HTMLIFrameElement,
  handlers: BridgeHandlers,
  allowedOrigins: readonly string[] = [],
): () => void {
  detachInspectorBridge();
  currentIframe = iframe;

  const selfOrigin = typeof window !== 'undefined' ? window.location.origin : '';
  const listener = (e: MessageEvent) => {
    // 送信元がこの iframe であることを確認（他フレームのメッセージを拾わない）。
    if (e.source && currentIframe && e.source !== currentIframe.contentWindow) return;
    if (!isInspectorEnvelope(e.data)) return;
    if (!isAllowedInspectorOrigin(e.origin, selfOrigin, allowedOrigins)) return;
    const msg = e.data as IframeToParentMessage;
    switch (msg.type) {
      case 'inspector:ready':
        handlers.onReady?.(msg.payload.slug);
        break;
      case 'inspector:selected':
        handlers.onSelected?.(msg.payload);
        break;
      case 'inspector:multi-selected':
        handlers.onMultiSelected?.(msg.payload.snapshots);
        break;
      case 'inspector:text-committed':
        handlers.onTextCommitted?.(msg.payload.elementKey, msg.payload.text);
        break;
      case 'inspector:text-drafted':
        handlers.onTextDrafted?.(msg.payload.elementKey, msg.payload.text);
        break;
      case 'inspector:selection-range':
        handlers.onSelectionRange?.(msg.payload);
        break;
      case 'inspector:reloaded':
        handlers.onReloaded?.();
        break;
      case 'inspector:hover':
        break; // ホバーはiframe内で描画するので親は無視
    }
  };
  window.addEventListener('message', listener);
  messageListener = listener;

  return detachInspectorBridge;
}

/** ブリッジを解除する。 */
export function detachInspectorBridge(): void {
  if (messageListener) {
    window.removeEventListener('message', messageListener);
    messageListener = null;
  }
  currentIframe = null;
}

/** 現在ブリッジが iframe にアタッチされているか。 */
export function isBridgeAttached(): boolean {
  return currentIframe !== null;
}
