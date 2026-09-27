// チャット画面のタイムライン構築ロジック（純粋関数）。
//
// 保存済みメッセージと「実行中ターンのライブ表示」を、実際に起きた時刻で
// 1本のタイムラインに混ぜる。ポイントは追い連絡（ダンの作業中に送った
// メッセージ）の扱い:
//   - 追い連絡より前に始まったターンの作業は、追い連絡の上に出る
//   - 追い連絡はダンが読み込むまで一番下（最新位置）に「仮送信」で出る
//   - 読み込まれた後の作業（新しいターン）は追い連絡の下に続く
// バックエンドは各ターンの ai_message を「ターン開始時刻」の created_at で
// 保存するので、この並びは完了後に保存される並びと常に一致する。
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
};

// Row model for the chat FlatList: saved messages and live turn bubbles are
// merged into ONE chronologically sorted timeline.
export type ChatListItem<M extends TimelineMessageLike = TimelineMessageLike> =
  | { kind: 'message'; key: string; sortMs: number; msg: M }
  | { kind: 'live'; key: string; sortMs: number; blocks: TurnBlock[]; showSpinner: boolean };

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
}): LiveTurnGroup[] {
  const { liveRunActive, currentRun, runEvents, savedTurnIds } = args;
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
  return [...groups.entries()].map(([key, events]) => ({
    key,
    blocks: events.map(eventToStep),
    anchorMs: new Date(events[0]?.created_at).getTime() || runStartMs,
  }));
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

// 追い連絡を送った「瞬間」に仮送信表示を出すための基準時刻。サーバーの
// followup_queued を待つと数秒遅れるので、送信時にローカルで先に立てる。
// computeUnreadFollowupIds の消化判定（この時刻より後に始まったターンが
// あるか）が既存のターン/保存済みAIメッセージで即座に成立してしまわない
// よう、いま画面が知っている最新の時刻より必ず後ろに置く（端末とサーバーの
// 時計ズレ対策）。
export function followupQueuedMsAtSend(args: {
  nowMs: number;
  messages: TimelineMessageLike[];
  liveTurnGroups: LiveTurnGroup[];
}): number {
  const { nowMs, messages, liveTurnGroups } = args;
  let ms = nowMs;
  for (const m of messages) {
    if (m.sender_type !== 'ai') continue;
    const t = new Date(m.created_at).getTime() || 0;
    if (t >= ms) ms = t + 1;
  }
  for (const g of liveTurnGroups) {
    if (g.anchorMs >= ms) ms = g.anchorMs + 1;
  }
  return ms;
}

// まだダンに読み込まれていない追い連絡の id。読み込まれた＝そのメッセージより
// 後に AI のターンが始まった（ライブのイベント or 保存済み ai_message。どちらも
// created_at がターン開始時刻）こと。
export function computeUnreadFollowupIds(args: {
  pendingFollowups: Record<string, number>;
  messages: TimelineMessageLike[];
  liveTurnGroups: LiveTurnGroup[];
}): Set<string> {
  const { pendingFollowups, messages, liveTurnGroups } = args;
  const ids = new Set<string>();
  for (const [id, queuedMs] of Object.entries(pendingFollowups)) {
    const consumed =
      messages.some(
        (m) => m.sender_type === 'ai' && new Date(m.created_at).getTime() > queuedMs,
      ) || liveTurnGroups.some((g) => g.anchorMs > queuedMs);
    if (!consumed) ids.add(id);
  }
  return ids;
}

// チャットの行リスト（inverted FlatList 用に降順 = 新しいものが index 0）。
export function buildChatListItems<M extends TimelineMessageLike>(args: {
  messages: M[];
  liveTurnGroups: LiveTurnGroup[];
  showLiveTurn: boolean;
  projectId?: string;
}): ChatListItem<M>[] {
  const { liveTurnGroups, showLiveTurn } = args;
  // 音声の断片は1つの吹き出しにまとめ、ダンの相づちだけの行は出さない（順序は時刻で並べ直すので入力順は問わない）
  const messages = mergeVoiceFragments(
    [...args.messages].sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()),
  ).map((m) => tidyRelayMessage(m, args.projectId));
  const items: ChatListItem<M>[] = messages.map((m) => ({
    kind: 'message',
    key: m.id,
    // 同時刻のときは 人間 → AI の順（AIメッセージのターン開始は必ず人間の
    // メッセージより後なので、msだけ同じになった場合の安定化）。
    sortMs: (new Date(m.created_at).getTime() || 0) * 10 + (m.sender_type === 'human' ? 1 : 2),
    msg: m,
  }));
  const liveItems: ChatListItem<M>[] = liveTurnGroups.map((g, i) => ({
    kind: 'live',
    key: `__live__:${g.key}`,
    sortMs: g.anchorMs * 10 + 2,
    blocks: g.blocks,
    // スピナーは「いま動いている」最新ターンの吹き出しにだけ付ける。
    showSpinner: i === liveTurnGroups.length - 1,
  }));
  // ライブ表示すべきなのにイベントがまだ無い（送信直後、またはターンの境界で
  // 前ターン保存→次ターン開始の谷間）→ 最下部にスピナーだけの吹き出しを出す。
  if (showLiveTurn && liveItems.length === 0) {
    liveItems.push({
      kind: 'live',
      key: '__live__',
      sortMs: Number.MAX_SAFE_INTEGER,
      blocks: [],
      showSpinner: true,
    });
  }
  return [...items, ...liveItems].sort((a, b) => b.sortMs - a.sortMs);
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
