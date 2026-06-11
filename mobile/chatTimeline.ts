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
}): ChatListItem<M>[] {
  const { messages, liveTurnGroups, showLiveTurn } = args;
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
