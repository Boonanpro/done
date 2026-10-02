// チャット画面のタイムライン構築ロジック（純粋関数）。
//
// 定義: docs/current/chat-timeline-definition.md（2026-10-02）
//   - 部屋の中のものは、サーバーが受け取った／起きた時刻の順に並ぶ。端末の時計は使わない。
//     本人のメッセージ＝受け取った時刻、ダンの作業の一歩＝起きた時刻、ダンの返事＝書き終えた時刻。
//   - まだサーバーに届いていない送信（pending）は、届くまで一番下（送った順）。
//   - 「考え中・作業中」は出来事ではなく状態: 3つの点が常に一番下。ライブの作業ログは時刻の位置に出る。
//   - 作業ログの途中に本人のメッセージが入ったら、ログはそこで分かれる（後の一歩がメッセージより上に出ない）。
//
// App.tsx から切り出してあるのは、UI 抜きでこの並び順をテストするため
// （scripts/test_chat_timeline.ts）。

// One step in an AI turn's inline timeline (mirrors the web chat's ai_context.blocks).
export type TurnBlock =
  | { type: 'text'; text?: string }
  | { type: 'tool'; name?: string; label?: string; detail?: string }
  | { type: 'reasoning'; text?: string }
  | { type: 'error'; text?: string };

// Server-side live-run reconstruction (mirrors the web chat). The live timeline
// is rebuilt from /current-run + /execution-events rather than only from the
// SSE stream, so it SURVIVES navigating away and back (and SSE drops) — the
// in-memory-only approach loses the timeline the moment the stream is torn down.
export type ExecutionEvent = {
  id: string;
  run_id?: string | null;
  turn_id?: string | null;
  event_type: 'tool_use' | 'reasoning' | 'phase' | 'error' | 'text' | 'done' | string;
  tool_name?: string | null;
  tool_label?: string | null;
  content?: string | null;
  metadata?: Record<string, unknown> | null;
  seq?: number | null;
  created_at: string;
};

export type AgentRun = {
  id: string;
  project_id: string;
  state: 'running' | 'paused' | 'completed' | 'failed' | 'interrupted' | string;
  created_at: string;
};

export function eventToStep(event: ExecutionEvent): TurnBlock {
  if (event.event_type === 'tool_use') {
    return { type: 'tool', label: event.tool_label || event.tool_name || 'ツール実行' };
  }
  if (event.event_type === 'error') {
    return { type: 'error', text: event.content || 'エラー' };
  }
  return { type: 'text', text: event.content || event.event_type };
}

// One in-progress turn of the live run, anchored into the transcript at the
// time its first event happened. A run can hold SEVERAL turns when the user
// sends a follow-up mid-run.
export type LiveTurnGroup = {
  key: string;
  blocks: TurnBlock[];
  anchorMs: number;
};

// タイムライン構築に必要な最小限のメッセージ形（App.tsx の MessageResponse が満たす）。
export type TimelineMessageLike = {
  id: string;
  sender_type: string;
  created_at: string;
  content?: string | null;
  ai_context?: { turn_id?: string } | null;
  // 送った瞬間の、まだサーバーに届いていない自分のメッセージ（届けば同じ id の保存行に置き換わる）。
  pending?: boolean;
};

// Row model for the chat FlatList: saved messages and live turn bubbles are
// merged into ONE chronologically sorted timeline.
export type ChatListItem<M extends TimelineMessageLike = TimelineMessageLike> =
  | { kind: 'message'; key: string; sortMs: number; msg: M }
  | { kind: 'live'; key: string; sortMs: number; blocks: TurnBlock[]; typing?: boolean }
  | { kind: 'typing'; key: string; sortMs: number };

// すでに保存済み ai_message として届いたターン。ライブ側で二重表示しないために使う。
export function collectSavedTurnIds(messages: TimelineMessageLike[]): Set<string> {
  const ids = new Set<string>();
  for (const m of messages) {
    const turnId = m.sender_type === 'ai' ? m.ai_context?.turn_id : undefined;
    if (turnId) ids.add(turnId);
  }
  return ids;
}

// 実行中 run のイベントをターンごとの吹き出しにまとめる。
export function groupLiveTurns(args: {
  liveRunActive: boolean;
  currentRun: AgentRun | null;
  runEvents: ExecutionEvent[];
  savedTurnIds: Set<string>;
  // 本人のメッセージ（保存済み）の時刻。作業ログはこの時刻をまたいで1つの吹き出しにしない。
  humanTimes?: number[];
}): LiveTurnGroup[] {
  const { liveRunActive, currentRun, runEvents, savedTurnIds } = args;
  const humanTimes = [...(args.humanTimes ?? [])].sort((a, b) => a - b);
  if (!liveRunActive || !currentRun) return [];
  const sorted = runEvents
    .filter(
      (e) => e.run_id === currentRun.id && e.event_type !== 'done' && e.event_type !== 'phase',
    )
    .sort(
      (a, b) =>
        (a.seq ?? 0) - (b.seq ?? 0) ||
        new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
    );
  // ターンごとに分ける。追い連絡があると1つの run の中に複数ターンができ、
  // 「追い連絡より前の作業」と「読み込んだ後の作業」を別の吹き出しとして
  // それぞれの開始時刻の位置に並べられる。
  const groups = new Map<string, ExecutionEvent[]>();
  for (const event of sorted) {
    if (event.turn_id && savedTurnIds.has(event.turn_id)) continue;
    const key = event.turn_id || `run:${event.run_id || 'unknown'}`;
    const list = groups.get(key);
    if (list) list.push(event);
    else groups.set(key, [event]);
  }
  const runStartMs = new Date(currentRun.created_at).getTime() || 0;
  const out: LiveTurnGroup[] = [];
  for (const [key, events] of groups.entries()) {
    // 本人のメッセージをまたぐところで分ける: その後の一歩はメッセージより下に出る。
    let segment: ExecutionEvent[] = [];
    let part = 0;
    const flush = () => {
      if (segment.length === 0) return;
      out.push({
        key: part === 0 ? key : `${key}#${part}`,
        blocks: segment.map(eventToStep),
        anchorMs: new Date(segment[0].created_at).getTime() || runStartMs,
      });
      part += 1;
      segment = [];
    };
    let prevMs = -Infinity;
    for (const event of events) {
      const ms = new Date(event.created_at).getTime() || prevMs;
      if (segment.length > 0 && humanTimes.some((h) => h > prevMs && h <= ms)) flush();
      segment.push(event);
      prevMs = ms;
    }
    flush();
  }
  return out;
}

// pollRun のレスポンスを runEvents へ反映するときのマージ。レスポンスは並行・
// 順不同で届く（2.5sの定期実行＋processイベント駆動）ので、丸ごと置き換えると
// 古いスナップショットが新しい状態を巻き戻し、ライブ表示の吹き出しが消えたり
// 縮んだりしてちらつく。イベントは追記専用ログなので「増える方向にだけ」足す。
// run が変わったら前の run のイベントは捨てる。変化が無ければ prev をそのまま
// 返し、無駄な再レンダリングを起こさない。
export function mergeRunEvents(
  prev: ExecutionEvent[],
  incoming: ExecutionEvent[],
  runId: string,
): ExecutionEvent[] {
  const next = prev.filter((e) => e.run_id === runId);
  const ids = new Set(next.map((e) => e.id));
  let changed = next.length !== prev.length;
  for (const e of incoming) {
    if (e.run_id !== runId || ids.has(e.id)) continue;
    next.push(e);
    ids.add(e.id);
    changed = true;
  }
  return changed ? next : prev;
}

// チャットの行リスト（inverted FlatList 用に降順 = 新しいものが index 0）。
export function buildChatListItems<M extends TimelineMessageLike>(args: {
  messages: M[];
  liveTurnGroups: LiveTurnGroup[];
  showLiveTurn: boolean;
  projectId?: string;
}): ChatListItem<M>[] {
  const { liveTurnGroups, showLiveTurn } = args;
  // 通話の中身（🎙 行）は出さず、通話ごとに「📞 ダンと通話」の1行にする（順序は時刻で並べ直すので入力順は問わない）
  const messages = collapseCalls(
    [...args.messages].sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()),
  ).map((m) => tidyRelayMessage(m, args.projectId));
  // 並びはサーバーの時刻だけ。届いていない送信は時刻を持たないので一番下（送った順）、
  // 3つの点はさらにその下。同時刻なら 本人 → 作業ログ → ダン・その他 の順。
  const BOTTOM = Number.MAX_SAFE_INTEGER;
  let pendingIndex = 0;
  const items: ChatListItem<M>[] = messages.map((m) => ({
    kind: 'message',
    key: m.id,
    sortMs: m.pending
      ? BOTTOM - 1000 + pendingIndex++
      : (new Date(m.created_at).getTime() || 0) * 10 + (m.sender_type === 'human' ? 1 : 3),
    msg: m,
  }));
  const liveItems: ChatListItem<M>[] = liveTurnGroups.map((g) => ({
    kind: 'live',
    key: `__live__:${g.key}`,
    sortMs: g.anchorMs * 10 + 2,
    blocks: g.blocks,
  }));
  const sorted = [...items, ...liveItems].sort((a, b) => b.sortMs - a.sortMs);
  if (!showLiveTurn) return sorted;
  // 3つの点は一番下。一番下が作業ログの吹き出しなら、その吹き出しの中の一番下に入れる（吹き出しを2つにしない）。
  const bottom = sorted[0];
  if (bottom && bottom.kind === 'live') return [{ ...bottom, typing: true }, ...sorted.slice(1)];
  return [{ kind: 'typing', key: '__typing__', sortMs: BOTTOM }, ...sorted];
}

// 音声会話の断片を1つの吹き出しにまとめる（表示だけ。保存行はそのまま）。
//
// 音声認識は1回の発言を息継ぎごとに区切って保存するので、「、あなたのスマホから」
// 「、スマホでポルノを…」のような断片が別々の吹き出しになり、間にダンの一言が
// 挟まって会話が読めなくなっていた（2026-09-27）。同じ話し手の 🎙 行が続いている
// 間（間隔 GAP_MS 以内・間に別の行が無い）を1つにまとめる。
// frontend/src/lib/voice-fragments.ts に同じ関数がある（両方を同じに保つ）。

const GAP_MS = 45_000;
const VOICE = '🎙';
// ダンの相づちだけの行（「はい。」「ん。」）。新しい通話では保存されないが、それ以前の行は表示で落とす。
const BACKCHANNEL = /^(?:(?:はい|ええ|うん|ん|え|ああ|あー|あ|うんうん|はいはい|なるほど|そうですね|ほう)[。、．,.!！?？…ー〜\s]*)+$/;

type VoiceLike = { id: string; sender_type: string; content?: string | null; created_at: string };

function body(content: string): string {
  return content.slice(VOICE.length).trim().replace(/^[、。，．,.?？!！\s]+/, '');
}

/** messages are chronological (oldest first). Returns the same order with runs of one speaker's 🎙 lines merged into
 * the first line of the run (its id and time), the text joined. */
export function mergeVoiceFragments<M extends VoiceLike>(messages: M[]): M[] {
  const out: M[] = [];
  let lastTime = 0;
  for (const msg of messages) {
    const content = msg.content || '';
    const time = new Date(msg.created_at).getTime() || 0;
    if (content.startsWith(VOICE) && msg.sender_type !== 'human' && BACKCHANNEL.test(body(content))) continue;
    const prev = out[out.length - 1];
    if (
      content.startsWith(VOICE) &&
      prev &&
      (prev.content || '').startsWith(VOICE) &&
      prev.sender_type === msg.sender_type &&
      time - lastTime <= GAP_MS
    ) {
      const joined = body(prev.content || '') + body(content);
      out[out.length - 1] = { ...prev, content: `${VOICE} ${joined}` };
      lastTime = time;
      continue;
    }
    out.push(content.startsWith(VOICE) ? { ...msg, content: `${VOICE} ${body(content)}` } : msg);
    lastTime = time;
  }
  return out;
}

// 通話の中身は画面に出さず、通話ごとに「📞 ダンと通話 …」の1行にする（表示だけ。発話の 🎙 行は保存したままで、
// ダンは読める）。本人の方針（2026-09-30）: 電話の履歴のように「いつ・何分話したか」だけが残ればよい。
// 2026-09-30 以降の通話はサーバーがその1行を書く（開始時刻と長さ入り）。それより前の通話は 🎙 行の連なりから1行を作る。
// 作業の報告や通話中に「出して」で出した物は通話の中身ではないので、そのまま残る。
// mobile/chatTimeline.ts と frontend/src/lib/voice-fragments.ts に同じ関数がある（両方を同じに保つ）。
const CALL = '📞';
const CALL_GAP_MS = 5 * 60_000;

/** 本人とダンの通話の記録の行なら、かけた側（本人＝右、ダン＝左。電話の発着信の履歴と同じ置き方）。それ以外は null。
 * 「📞 ダンからの通話」はダンがかけた通話、「📞 ダンと通話」は本人がかけた通話（それより前の記録はすべて本人から）。 */
export function callSide(m: VoiceLike): 'owner' | 'dan' | null {
  const content = m.content || '';
  if (m.sender_type !== 'system' || !content.startsWith(`${CALL} ダン`)) return null;
  return content.startsWith(`${CALL} ダンから`) ? 'dan' : 'owner';
}

/** 通話の記録の長さを LINE と同じ「分:秒」で（例 3:05）。長さが書かれていない昔の行は開始〜終了の時刻から分だけ出す。 */
export function callDuration(content: string): string {
  const m = content.match(/（(?:(\d+)分)?(\d+)秒）/);
  if (m) return `${Number(m[1] || 0)}:${String(Number(m[2])).padStart(2, '0')}`;
  const r = content.match(/(\d{1,2}):(\d{2})〜(\d{1,2}):(\d{2})/);
  if (!r) return '';
  const minutes = (Number(r[3]) * 60 + Number(r[4]) - Number(r[1]) * 60 - Number(r[2]) + 1440) % 1440;
  return `${minutes}:00`;
}

function callLengthMs(content: string): number {
  const m = content.match(/（(?:(\d+)分)?(\d+)秒）/);
  return m ? (Number(m[1] || 0) * 60 + Number(m[2])) * 1000 : 0;
}

function clock(ms: number): string {
  const d = new Date(ms);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

/** messages are chronological (oldest first). 🎙 lines are left out; each earlier call without the server's 📞 line
 * becomes one system row at the call's first line. */
export function collapseCalls<M extends VoiceLike>(messages: M[]): M[] {
  const logged: Array<[number, number]> = [];
  for (const m of messages) {
    const content = m.content || '';
    if (m.sender_type === 'system' && content.startsWith(CALL)) {
      const t = new Date(m.created_at).getTime() || 0;
      logged.push([t - 60_000, t + callLengthMs(content) + 60_000]);
    }
  }
  const out: M[] = [];
  let run: { row: M; index: number; first: number; last: number } | null = null;
  const close = (open: { row: M; index: number; first: number; last: number } | null) => {
    if (open) out[open.index] = { ...open.row, sender_type: 'system', content: `${CALL} ダンと通話 ${clock(open.first)}〜${clock(open.last)}` };
  };
  for (const m of messages) {
    const content = m.content || '';
    if (!content.startsWith(VOICE)) {
      out.push(m);
      continue;
    }
    const t = new Date(m.created_at).getTime() || 0;
    if (logged.some(([from, to]) => t >= from && t <= to)) continue;
    if (run && t - run.last <= CALL_GAP_MS) {
      run.last = t;
      continue;
    }
    close(run);
    out.push(m);
    run = { row: m, index: out.length - 1, first: t, last: t };
  }
  close(run);
  return out;
}

// 作業の依頼の写し（【あなたの依頼・Done経由】）と、作業の報告の見出し・「作業の部屋」リンクを、
// 読める形にする（表示だけ）。2026-09-27 以前の行には、作業担当への内部の指示と直前の会話の JSON が
// そのまま入っていて、同じ部屋の音声から頼んだ作業にも見出しとこの部屋へのリンクが付いていた。
const REQUEST_HEAD = '【あなたの依頼・Done経由】';

export function tidyRelayMessage<M extends VoiceLike>(msg: M, projectId?: string): M {
  const content = msg.content || '';
  if (content.startsWith(REQUEST_HEAD)) {
    const asked = content
      .slice(REQUEST_HEAD.length)
      .split('\n参考の直前会話（')[0]
      .split('\n音声通話からの依頼です。')[0]
      .replace(/^\s*今回のユーザー発言（原文）:\s*/, '')
      .trim();
    return { ...msg, content: `${REQUEST_HEAD}\n${asked}` };
  }
  if (projectId && content.startsWith('【') && content.includes(`[作業の部屋](/chat/${projectId})`)) {
    const text = content
      .replace(`[作業の部屋](/chat/${projectId})`, '')
      .replace(/^【[^】\n]*からの報告】\n?/, '')
      .trim();
    return { ...msg, content: text };
  }
  return msg;
}
