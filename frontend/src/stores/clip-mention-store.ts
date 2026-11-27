// エディターの会話で、タイムラインのクリップを「@」で指す（2026-11-27 本人「クリップをこのチャット内にメンションできるように
// したい。ただ選択しただけでメンション入っちゃうとうっとおしいので、電話マークの横の@を押して選択した時だけ」）。
// 会話の入力欄（ProjectChatPanel の ChatInput）が @ で start(projectId) し、エディター（video-review-editor）が
// クリップを押された時に picking を見て、そのクリップを会話の「画面から添えた物」（chat-attach-store）に入れて stop する。
import { create } from 'zustand';

type State = {
  /** @ を押した会話の部屋（projectId）。null なら選んでもメンションしない */
  picking: string | null;
  start: (projectId: string) => void;
  stop: () => void;
};

export const useClipMentionStore = create<State>((set) => ({
  picking: null,
  start: (projectId) => set({ picking: projectId }),
  stop: () => set({ picking: null }),
}));

/** エディターがこの窓にあるか（会話欄に @ を出すかどうか）。エディターが開いている間だけ数える。 */
type EditorPresence = { editors: number; enter: () => void; leave: () => void };
export const useEditorPresence = create<EditorPresence>((set) => ({
  editors: 0,
  enter: () => set((s) => ({ editors: s.editors + 1 })),
  leave: () => set((s) => ({ editors: Math.max(0, s.editors - 1) })),
}));

const fmt = (t: number) => {
  const s = Math.max(0, t);
  const m = Math.floor(s / 60);
  return `${m}:${(s - m * 60).toFixed(1).padStart(4, '0')}`;
};

export type MentionableClip = {
  id: string;
  timeline_start: number;
  timeline_end: number;
  text?: string | null;
  label?: string | null;
  asset_id?: string | null;
  track?: string | null;
  type?: string | null;
  role?: string | null;
  ae_text?: { values?: string[] } | null;
};

/** 札に出す短い名前と、ダンに渡す中身。kind はエディターの段の種類（video/audio/caption/effect…）。 */
export function describeClipMention(clip: MentionableClip, kind: string, lane?: number | null): { label: string; detail: string } {
  const words = (clip.ae_text?.values || []).join(' / ') || clip.text || '';
  const name = words || clip.label || clip.asset_id || clip.id;
  const kindJa: Record<string, string> = { video: '映像', image: '画像', audio: '音', caption: '字幕', effect: '効果' };
  const k = kindJa[clip.type === 'image' ? 'image' : kind] || kind;
  const short = String(name).replace(/\s+/g, ' ').slice(0, 18);
  const label = `@${k}「${short}」${fmt(clip.timeline_start)}`;
  const detail = [
    `- メンションしたクリップ: clip_id=${clip.id}`,
    `  種類=${k}${lane != null ? ` 段=${lane}` : ''} 時刻=${clip.timeline_start.toFixed(2)}〜${clip.timeline_end.toFixed(2)}秒`,
    words ? `  文字=${String(words).slice(0, 200)}` : '',
    clip.asset_id ? `  素材=${clip.asset_id}` : '',
    clip.role ? `  役割=${clip.role}` : '',
  ].filter(Boolean).join('\n');
  return { label, detail };
}
