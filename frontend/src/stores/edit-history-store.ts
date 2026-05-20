'use client';

/**
 * 手動編集の Undo/Redo スタック。
 *
 * 設計:
 * - 各エントリは「JSX ファイル単位のスナップショット」。
 *   `direct-write` / `delete-element` API のレスポンスから before/after を受け取って積む。
 * - Undo は スタック top の before_content を `restore-file` API で書き戻す。
 *   Redo は redoStack に push しておいて、再度 restore-file で after_content を当て直す。
 * - 連続編集（同じ slug + 同じ file_path + 同じ element_key + 短時間内）はマージして
 *   1 エントリにまとめる。スライダーをドラッグしても 1 アクションとして扱われる。
 * - 上限は 50 エントリ。それを超えると古いものから捨てる。
 * - 永続化はしない。ページ/タブを閉じたらリセット（プロジェクトを安全にする）。
 */

import { create } from 'zustand';
import { toast } from 'sonner';

export interface HistoryEntry {
  /** スナップショットのタイムスタンプ（マージ判定に使う）。 */
  ts: number;
  /** artifact slug。restore-file API の呼び出し対象を決める。 */
  slug: string;
  /** PROJECT_ROOT からの相対パス。例: "frontend/src/app/artifacts/kittoku/page.tsx" */
  filePath: string;
  /** 編集前のファイル内容。Undo で書き戻すのに使う。 */
  before: string;
  /** 編集後のファイル内容。Redo で再適用するのに使う。 */
  after: string;
  /** どの要素を編集したか。同要素の連続編集をマージする鍵。 */
  elementKey: string | null;
  /** UI表示用のラベル。toast に出す。 */
  summary: string;
}

const MAX_HISTORY = 50;
const MERGE_WINDOW_MS = 2000;

interface EditHistoryState {
  /** Undo 可能なエントリのスタック（新しいものが末尾）。 */
  undoStack: HistoryEntry[];
  /** Redo 可能なエントリのスタック（Undo 実行で積まれる）。 */
  redoStack: HistoryEntry[];
  /** Undo/Redo 進行中フラグ（実行中の Undo を「編集」として記録しないため）。 */
  isReverting: boolean;
}

interface EditHistoryActions {
  /** 編集後にスナップショットを積む。連続編集ならマージ。 */
  push: (entry: Omit<HistoryEntry, 'ts'>) => void;
  /** Undo を 1 段実行。成功時 true。 */
  undo: () => Promise<boolean>;
  /** Redo を 1 段実行。成功時 true。 */
  redo: () => Promise<boolean>;
  /** 全クリア（artifact 切り替え時）。 */
  clear: () => void;
  /** Undo/Redo の可否。 */
  canUndo: () => boolean;
  canRedo: () => boolean;
}

export const useEditHistoryStore = create<EditHistoryState & EditHistoryActions>()((set, get) => ({
  undoStack: [],
  redoStack: [],
  isReverting: false,

  push: (entry) => {
    if (get().isReverting) return; // Undo 実行中の書き戻しは履歴に積まない
    if (entry.before === entry.after) return; // no-op はスキップ

    const now = Date.now();
    set((state) => {
      const last = state.undoStack[state.undoStack.length - 1];
      // 連続編集マージ条件:
      //   1) 同じ slug + 同じ file_path + 同じ elementKey
      //   2) 時間差 MERGE_WINDOW_MS 以内
      //   → before は古い方を残し、after だけ最新で上書き
      if (
        last &&
        last.slug === entry.slug &&
        last.filePath === entry.filePath &&
        last.elementKey === entry.elementKey &&
        entry.elementKey !== null &&
        now - last.ts < MERGE_WINDOW_MS
      ) {
        const merged: HistoryEntry = {
          ...last,
          after: entry.after,
          ts: now,
          summary: entry.summary,
        };
        const newStack = [...state.undoStack.slice(0, -1), merged];
        return { undoStack: newStack, redoStack: [] };
      }

      // 新規エントリ。Redo スタックはクリア（新しい分岐ができた）
      const newStack = [...state.undoStack, { ...entry, ts: now }];
      // 上限超過分は古い方を捨てる
      const trimmed = newStack.length > MAX_HISTORY
        ? newStack.slice(newStack.length - MAX_HISTORY)
        : newStack;
      return { undoStack: trimmed, redoStack: [] };
    });
  },

  undo: async () => {
    const top = get().undoStack[get().undoStack.length - 1];
    if (!top) return false;
    set({ isReverting: true });
    try {
      const ok = await restoreFile(top.slug, top.filePath, top.before);
      if (!ok) return false;
      set((state) => ({
        undoStack: state.undoStack.slice(0, -1),
        redoStack: [...state.redoStack, top],
      }));
      toast.success(`⟲ Undo: ${top.summary}`);
      return true;
    } finally {
      set({ isReverting: false });
    }
  },

  redo: async () => {
    const top = get().redoStack[get().redoStack.length - 1];
    if (!top) return false;
    set({ isReverting: true });
    try {
      const ok = await restoreFile(top.slug, top.filePath, top.after);
      if (!ok) return false;
      set((state) => ({
        redoStack: state.redoStack.slice(0, -1),
        undoStack: [...state.undoStack, top],
      }));
      toast.success(`⟳ Redo: ${top.summary}`);
      return true;
    } finally {
      set({ isReverting: false });
    }
  },

  clear: () => set({ undoStack: [], redoStack: [] }),

  canUndo: () => get().undoStack.length > 0,
  canRedo: () => get().redoStack.length > 0,
}));

async function restoreFile(slug: string, filePath: string, content: string): Promise<boolean> {
  try {
    const res = await fetch('/api/v1/inspector-overrides/restore-file', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        artifact_slug: slug,
        file_path: filePath,
        content,
      }),
    });
    if (!res.ok) {
      const t = await res.text();
      toast.error('Undo/Redo に失敗しました', { description: t.slice(0, 200) });
      return false;
    }
    return true;
  } catch (err) {
    toast.error('Undo/Redo の通信に失敗', { description: String(err).slice(0, 200) });
    return false;
  }
}

/** 編集の summary を作るヘルパ。"font-size 16px → 18px" のような短文。 */
export function makeEditSummary(opts: {
  kind: 'style' | 'text' | 'attr' | 'delete';
  prop?: string;
  value?: string;
  elementHint?: string;
}): string {
  const tag = opts.elementHint ? `<${opts.elementHint}>` : '';
  switch (opts.kind) {
    case 'style':
      return `${tag} ${opts.prop ?? ''}: ${opts.value ?? ''}`.trim();
    case 'text':
      return `${tag} テキスト変更`.trim();
    case 'attr':
      return `${tag} ${opts.prop ?? ''} 変更`.trim();
    case 'delete':
      return `${tag} 要素を削除`.trim();
  }
}
