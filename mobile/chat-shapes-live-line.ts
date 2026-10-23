// スマホのアプリ用の写し: frontend/src/lib/chat-shapes/live-line.ts と同じ中身（同じフォルダの読み込みの名前だけ違う）。
// frontend/scripts/sync-mobile-chat-shapes.mjs が作る。手で直さず、元を直して写し直す
// （tests/chat_shapes_program.test.mjs が同じ中身かを見る）。
/**
 * 作業中の1行と、押すと開く作業の一覧の決まり（2026-10-24）。本人「考えていますとか返事を書いていますってだけだと
 * やっぱ待たされてる感がえぐいわ。本当に進んでる？ってなる」「準備していますはダメ。人間っぽくないから」。
 *
 * - 1行: 一番新しい一歩の言葉。道具なら道具ごとの平易な言葉（サーバーの metadata.activity。app/agent/activity_line.py）、
 *   思考の日本語の要約が届いていればその最後の1文、どちらも無ければ「考えています」。起動中も「考えています」で、
 *   別の言葉は作らない。書き始めた返事（最後の一歩が文）は「返事を書いています」。
 * - 後ろに送ってからの経過（「14秒」「1分05秒」）。1秒ごとに進むので、止まっていないと分かる。
 * - 押すと、そのターンでやったことが時刻とかかった秒数つきで全部並ぶ（liveRows）。同じ言葉が続く一歩は1行にまとめる。
 *
 * PC・スマホ・開発室のチャットが同じ物を使う（スマホの写しは frontend/scripts/sync-mobile-chat-shapes.mjs が作る）。依存なし。
 */

/** 画面ごとの記録を、この形に直して渡す */
export type LiveStep = {
  /** tool=道具、text=ダンが書いた文（途中の説明か書きかけの返事）、thinking=思考の要約、error=失敗 */
  kind: 'tool' | 'text' | 'thinking' | 'error';
  /** 文・思考・失敗の中身 */
  text?: string;
  /** 道具の平易な言葉（空なら1行は前のまま） */
  activity?: string;
  /** 起きた時刻（ミリ秒）。無ければ一覧の時刻と秒数を出さない */
  at?: number;
};

export const LINE_THINKING = '考えています';
export const LINE_WRITING = '返事を書いています';

const JA = /[぀-ヿ㐀-鿿]/;
const LINE_MAX = 48;

function plainText(s: string): string {
  return s
    .replace(/```[\s\S]*?(```|$)/g, ' ')
    .replace(/\[(添付[^\]]*)\]/g, ' ')
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/[*_`#>|]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

function clip(s: string, max: number): string {
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}

/** 日本語の文の最後の1文（思考の要約の最後は「次にすること」が多い）。日本語が無ければ "" */
export function lastSentence(text: string | undefined, max = LINE_MAX): string {
  const t = plainText(text || '');
  if (!t || !JA.test(t)) return '';
  const parts = t.split(/(?<=[。！？!?])\s*/).map((p) => p.trim()).filter(Boolean);
  const last = parts.length ? parts[parts.length - 1] : t;
  return clip(last, max);
}

/** 作業中の1行 */
export function liveLineText(steps: LiveStep[]): string {
  for (let i = steps.length - 1; i >= 0; i--) {
    const st = steps[i];
    if (st.kind === 'text' && i === steps.length - 1 && (st.text || '').trim()) return LINE_WRITING;
    if (st.kind === 'thinking') {
      const line = lastSentence(st.text);
      if (line) return line;
    }
    if (st.kind === 'tool' && st.activity) return st.activity;
  }
  return LINE_THINKING;
}

/** 経過の秒数（「8秒」「1分05秒」「1時間02分」） */
export function elapsedText(fromMs: number | null | undefined, nowMs: number): string {
  if (!fromMs || !Number.isFinite(fromMs)) return '';
  return secondsText(Math.floor((nowMs - fromMs) / 1000));
}

/** 秒数の書き方（「12秒」「1分05秒」） */
export function secondsText(seconds: number | null): string {
  if (seconds == null || !Number.isFinite(seconds)) return '';
  const sec = Math.max(0, Math.floor(seconds));
  if (sec < 60) return `${sec}秒`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}分${String(sec % 60).padStart(2, '0')}秒`;
  return `${Math.floor(min / 60)}時間${String(min % 60).padStart(2, '0')}分`;
}

/** 時刻（「14:08:31」） */
export function clockText(ms: number | null | undefined): string {
  if (!ms || !Number.isFinite(ms)) return '';
  const d = new Date(ms);
  return [d.getHours(), d.getMinutes(), d.getSeconds()].map((n) => String(n).padStart(2, '0')).join(':');
}

/** 押すと開く一覧の1行 */
export type LiveRow = {
  key: string;
  /** 一歩の言葉 */
  label: string;
  /** 同じ言葉が続いた数（2以上で「×3」） */
  count: number;
  /** 始まった時刻（ミリ秒） */
  at: number | null;
  /** かかった秒数。今している一歩は経過中の秒数 */
  seconds: number | null;
  /** 今している一歩か */
  now: boolean;
};

function rowLabel(st: LiveStep, isLast: boolean): string {
  if (st.kind === 'tool') return st.activity || '';
  if (st.kind === 'thinking') return lastSentence(st.text, 120);
  if (st.kind === 'text') {
    // 最後の文は書きかけの返事かもしれないので、中身は出さない（返事は保存されてから出る）
    if (isLast) return LINE_WRITING;
    const t = plainText(st.text || '');
    return t ? clip(t, 120) : '';
  }
  return 'うまくいかなかったので、やり直しています';
}

/** そのターンでやったことの一覧（古い順）。startedAt は送った時刻（最初の行「考えています」の始まり） */
export function liveRows(steps: LiveStep[], nowMs: number, startedAt?: number | null): LiveRow[] {
  const rows: LiveRow[] = [];
  const firstAt = steps.find((s) => s.at)?.at ?? null;
  if (startedAt && (!firstAt || startedAt < firstAt - 999)) {
    rows.push({ key: 'start', label: LINE_THINKING, count: 1, at: startedAt, seconds: null, now: false });
  }
  steps.forEach((st, i) => {
    const label = rowLabel(st, i === steps.length - 1);
    if (!label) return;
    const prev = rows[rows.length - 1];
    if (prev && prev.label === label && prev.key !== 'start') {
      prev.count += 1;
      return;
    }
    rows.push({ key: `s${i}`, label, count: 1, at: st.at ?? null, seconds: null, now: false });
  });
  rows.forEach((r, i) => {
    const next = rows[i + 1];
    if (r.at == null) return;
    if (next && next.at != null) r.seconds = Math.max(0, Math.round((next.at - r.at) / 1000));
    else if (!next) {
      r.seconds = Math.max(0, Math.floor((nowMs - r.at) / 1000));
      r.now = true;
    }
  });
  if (rows.length && !rows.some((r) => r.now)) rows[rows.length - 1].now = true;
  return rows;
}

/**
 * 送ってからの経過の起点: このターンの最初の一歩と、その前に本人が送った時刻のうち早い方。
 * 本人の発言が無い起き方（並行作業の報告で起きた等）は最初の一歩の時刻。lastHumanAt は、画面の一番新しい発言が
 * 本人の物の時だけ渡す。30分より前の発言は起点にしない（前の話の続きで起きたターン）。
 */
export function turnStartedAt(firstStepAt: number | null | undefined, lastHumanAt: number | null | undefined): number | null {
  const a = firstStepAt && Number.isFinite(firstStepAt) ? firstStepAt : null;
  const h = lastHumanAt && Number.isFinite(lastHumanAt) ? lastHumanAt : null;
  if (a && h) return h <= a && a - h < 30 * 60_000 ? h : a;
  return a ?? h;
}
