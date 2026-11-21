// 会話の入力欄の上に付く「画面から添えた物」（2026-11-21 本人「要素クリックしてもそれがチャットに添付されない」）。
// 台本を聞く画面のサムネの編集で、選んだ部品・ペンの書き込みを、右の会話（ProjectChatPanel の ChatInput）へ渡す。
// 部屋（projectId）ごとに持つ。送った時に、ChatInput が detail を本文の後ろに足し、upload() の絵を添付にして、onSent() を呼ぶ。
import { create } from 'zustand';

export type ChatAttachItem = {
  /** 同じ種類は1つ（'thumb-part' 選んだ部品・'thumb-marks' ペンの書き込み） */
  key: string;
  /** 札の言葉（「選んだ部品：文字「今までありがとう」」） */
  label: string;
  /** 札の小さい絵（無ければ文字だけ） */
  preview?: string;
  /** ダンに渡す中身（本文の後ろに足す） */
  detail: string;
  /** 送る時に、ダンが Read で見られる絵を作ってその URL を返す（作れなければ null。本文だけ送る） */
  upload?: () => Promise<string | null>;
  /** 送った後に、添えた側を片付ける（ペンの線を消すなど） */
  onSent?: () => void;
  /** ×で外した時 */
  onRemove?: () => void;
};

type State = {
  items: Record<string, ChatAttachItem[]>;
  put: (projectId: string, item: ChatAttachItem) => void;
  drop: (projectId: string, key: string) => void;
  take: (projectId: string) => ChatAttachItem[];
};

export const useChatAttachStore = create<State>((set, get) => ({
  items: {},
  put: (projectId, item) => set((s) => ({
    items: { ...s.items, [projectId]: [...(s.items[projectId] || []).filter((x) => x.key !== item.key), item] },
  })),
  drop: (projectId, key) => set((s) => {
    const cur = s.items[projectId] || [];
    if (!cur.some((x) => x.key === key)) return s;
    return { items: { ...s.items, [projectId]: cur.filter((x) => x.key !== key) } };
  }),
  take: (projectId) => {
    const list = get().items[projectId] || [];
    if (list.length) set((s) => ({ items: { ...s.items, [projectId]: [] } }));
    return list;
  },
}));

const EMPTY: ChatAttachItem[] = [];
export const useChatAttachments = (projectId: string) => useChatAttachStore((s) => s.items[projectId] || EMPTY);

/** 送る本文: みきさんの言葉と、添えた物の札（画面に出る短い1行）。中身はダンにだけ渡す（<dan-context> は画面に出ない）。 */
export function composeAttached(text: string, items: ChatAttachItem[]): string {
  if (!items.length) return text;
  const shown = `（${items.map((x) => x.label).join('・')}）`;
  const body = items.map((x) => x.detail).join('\n');
  return `${text ? `${text}\n` : ''}${shown}\n\n<dan-context>\nkind: screen-attachment\nnote: みきさんが画面から添えた物。言葉が無ければ添えた物を見て判断する。\n${body}\n</dan-context>`;
}
