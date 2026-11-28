// 字幕の出る単位（タイプ＝前半→後半、カラオケ＝語ごと）。node --experimental-strip-types で試験できるよう React を持たない。
export type RevealWord = { text: string; start: number; end?: number | null };
export type RevealCaption = { text: string; start: number; end: number; words?: RevealWord[] | null };

const bare = (s: string) => s.replace(/\s/g, '');
const spells = (cap: RevealCaption) =>
  !!cap.words?.length && bare(cap.words.map((w) => w.text).join('')) === bare(cap.text);

// karaoke は語ごとに光らせるので、語の時刻が無ければ ASCII の語・漢字かなは1字ずつ均等に割る。
// typewriter は「まとめて全部」か「書いた区切りで一部ずつ」だけ。1文字ずつ出すことはしない
// （2026-11-28 本人「1文字ずつ出す字幕はやめてください」）。区切りが本文と合わない時は全部まとめて出す。
export function revealTokens(cap: RevealCaption, anim: 'typewriter' | 'karaoke'): { text: string; start: number; end: number }[] {
  if (spells(cap)) {
    // 語の時刻はタイムライン上の秒。字幕だけ動いて語が元の時刻のまま残った時（詰める・ずらす。
    // 2026-11-28 本人が隙間を詰めた後ろの字幕で後半が出なくなった）は、語ごと字幕の頭へ寄せる。
    const raw = cap.words as RevealWord[];
    const d = raw[0].start < cap.start - 0.05 || raw[0].start >= cap.end ? cap.start - raw[0].start : 0;
    const ws = d ? raw.map((w) => ({ ...w, start: w.start + d, end: w.end != null && Number.isFinite(Number(w.end)) ? Number(w.end) + d : w.end })) : raw;
    return ws.map((w, i) => ({ text: w.text, start: w.start, end: Number.isFinite(Number(w.end)) && w.end != null ? Number(w.end) : (ws[i + 1]?.start ?? cap.end) }));
  }
  if (anim === 'typewriter') return [{ text: cap.text, start: cap.start, end: cap.end }];
  const units: string[] = [];
  const text = cap.text;
  let i = 0;
  while (i < text.length) {
    const ch = text[i];
    if (ch.charCodeAt(0) < 128 && ch.trim()) {
      let word = '';
      while (i < text.length && text[i].charCodeAt(0) < 128 && text[i].trim()) word += text[i++];
      units.push(word);
    } else {
      units.push(ch);
      i++;
    }
  }
  const dur = Math.max(0.01, cap.end - cap.start);
  return units.map((u, idx) => ({
    text: u,
    start: cap.start + (dur * idx) / units.length,
    end: cap.start + (dur * (idx + 1)) / units.length,
  }));
}
