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
 * - 出す文は1文ずつ確かめる。英語が主の文は出さない（思考は英語で流れることがある）。「準備しています」のような
 *   起動の言葉は「考えています」に置き換える（本人にとって準備中か考え中かの区別は要らない）。
 * - 追い連絡でターンや吹き出しが分かれても、返事が保存されるまでの作業は1つの一覧にまとめ、秒数は最初に送った時から。
 *
 * 画面ごとの記録（作業の出来事 execution_events）は liveStepFromEvent で LiveStep にする。PC・スマホ・開発室の
 * チャットが同じ物を使う（スマホの写しは frontend/scripts/sync-mobile-chat-shapes.mjs が作る）。依存なし。
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

const JA_CHAR = /[\u3040-\u30ff\u3400-\u9fff]/g;
const LATIN_CHAR = /[A-Za-z]/g;
const LINE_MAX = 48;
/** 起動・準備の言葉（本人には「考えています」と同じ）。短い文で「準備・起動」が中心の物だけ（長い説明の文は残す） */
const PREPARING = /(?:準備|起動)(?:中|して|を|が|に)/;
const isPreparing = (sentence: string) => sentence.length <= 24 && PREPARING.test(sentence);

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

/** 日本語が主の文か（日本語の字が2つ以上で、英字が日本語の字の3倍を超えない。「GitHub の PR を作ります。」は出す） */
export function isJapaneseSentence(sentence: string): boolean {
  const ja = (sentence.match(JA_CHAR) || []).length;
  const latin = (sentence.match(LATIN_CHAR) || []).length;
  return ja >= 2 && latin <= ja * 3;
}

/** 出してよい文だけ（古い順）。英語が主の文は落とし、起動・準備の言葉は「考えています」にする */
export function shownSentences(text: string | undefined): string[] {
  const t = plainText(text || '');
  if (!t) return [];
  return t
    .split(/(?<=[。！？!?])\s*|(?<=\.)\s+/)
    .map((p) => p.trim())
    .filter(Boolean)
    .filter(isJapaneseSentence)
    .map((p) => (isPreparing(p) ? LINE_THINKING : p));
}

/** 1行に出す言葉（道具の言葉にも同じ決まり）。出せなければ "" */
export function shownLine(text: string | undefined, max = LINE_MAX): string {
  const parts = shownSentences(text);
  return parts.length ? clip(parts[parts.length - 1], max) : '';
}

/** 日本語の文の最後の1文（思考の要約の最後は「次にすること」が多い）。出せる文が無ければ "" */
export function lastSentence(text: string | undefined, max = LINE_MAX): string {
  return shownLine(text, max);
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
    if (st.kind === 'tool' && st.activity) {
      const line = shownLine(st.activity);
      if (line) return line;
    }
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
  if (st.kind === 'tool') return shownLine(st.activity, 120);
  if (st.kind === 'thinking') return lastSentence(st.text, 120);
  if (st.kind === 'text') {
    // 最後の文は書きかけの返事かもしれないので、中身は出さない（返事は保存されてから出る）
    if (isLast) return LINE_WRITING;
    const parts = shownSentences(st.text);
    return parts.length ? clip(parts.join(''), 120) : '';
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
    // 同じ言葉が続く一歩は1行に（「考えています」が続く時は数を付けない）
    if (prev && prev.label === label && (prev.key !== 'start' || label === LINE_THINKING)) {
      if (label !== LINE_THINKING) prev.count += 1;
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

/** 作業の出来事（execution_events の1行。PC・スマホ・開発室とも同じ形で受け取る） */
export type LiveEventLike = {
  event_type: string;
  content?: string | null;
  metadata?: Record<string, unknown> | null;
  created_at?: string | null;
};

/** 作業の出来事1つを、作業中の1行と一覧の一歩にする（どの画面もこれを通る）。出さない出来事は null */
export function liveStepFromEvent(e: LiveEventLike): LiveStep | null {
  const at = (e.created_at && Date.parse(e.created_at)) || undefined;
  if (e.event_type === 'tool_use') {
    const act = e.metadata?.activity;
    return { kind: 'tool', activity: typeof act === 'string' ? act : undefined, at };
  }
  if (e.event_type === 'error') return { kind: 'error', text: e.content || '', at };
  if (e.event_type === 'reasoning' || e.event_type === 'text') {
    const text = (e.content || '').trim();
    if (!text || text === 'Thinking...') return null;
    return { kind: e.metadata?.kind === 'thinking' ? 'thinking' : 'text', text, at };
  }
  return null;
}

/** 作業の出来事の並び → 一歩の並び（時刻順） */
export function liveStepsFromEvents(events: LiveEventLike[]): LiveStep[] {
  return events
    .map(liveStepFromEvent)
    .filter((st): st is LiveStep => !!st)
    .sort((a, b) => (a.at ?? 0) - (b.at ?? 0));
}

/**
 * 作業中の秒数の起点（2026-10-24 見直し: 追い連絡のたびに0から数え直していた）。sentTimes は、最後に保存された
 * ダンの返事より後に本人が送った発言の時刻。その一番早い物（最初に送った時）から数える。最初の一歩より30分以上
 * 前の発言は起点にしない。本人の発言が無い起き方（並行作業の報告で起きた等）は最初の一歩の時刻。
 */
export function liveStartedAt(firstStepAt: number | null | undefined, sentTimes: number[]): number | null {
  const a = firstStepAt && Number.isFinite(firstStepAt) ? firstStepAt : null;
  const sent = sentTimes.filter((t) => Number.isFinite(t) && t > 0 && (!a || a - t < 30 * 60_000)).sort((x, y) => x - y);
  const h = sent.length ? sent[0] : null;
  if (a && h) return Math.min(a, h);
  return a ?? h;
}

/** 最後に保存されたダンの返事より後に、本人が送った発言の時刻（古い順）。messages は古い順 */
export function sentSinceReply(messages: { sender_type: string; created_at: string }[]): number[] {
  const out: number[] = [];
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    if (m.sender_type !== 'human') break;
    const t = Date.parse(m.created_at);
    if (Number.isFinite(t)) out.unshift(t);
  }
  return out;
}
