// チャットタイムライン並び順のテスト（docs/current/chat-timeline-definition.md）。
//
// シナリオ: msg1 送信 → ダンのターンX開始 → 途中で追い連絡 msg2 → X の作業が続く →
// X の返事が書き終わって保存 → 最後に送った msg3 はまだ届いていない。どの段階でも
// 「サーバーの時刻の順・届いていない送信は一番下・3つの点はさらにその下」であることを確かめる。
//
// 実行: cd mobile && npx tsc chatTimeline.ts scripts/test_chat_timeline.ts \
//         --outDir .testbuild --module commonjs --target es2020 --strict --skipLibCheck
//       node .testbuild/scripts/test_chat_timeline.js
import * as assert from 'assert';
import {
  buildChatListItems,
  collectSavedTurnIds,
  groupLiveTurns,
  mergeRunEvents,
  type AgentRun,
  type ExecutionEvent,
  type TimelineMessageLike,
} from '../chatTimeline';

const T = 1750000000000;
const iso = (offsetMs: number) => new Date(T + offsetMs).toISOString();
const run: AgentRun = { id: 'r1', project_id: 'p1', state: 'running', created_at: iso(2000) };
const msg1: TimelineMessageLike = { id: 'msg1', sender_type: 'human', created_at: iso(0) };
const msg2: TimelineMessageLike = { id: 'msg2', sender_type: 'human', created_at: iso(15000) };   // 追い連絡
const ev = (id: string, at: number, turn: string | null = 'tx'): ExecutionEvent =>
  ({ id, run_id: 'r1', turn_id: turn, event_type: 'tool_use', tool_label: id, created_at: iso(at), seq: at });

// 古い順（上から下）のキー
function topToBottom(args: Parameters<typeof buildChatListItems>[0]): string[] {
  return buildChatListItems(args).map((i) => i.key).reverse();
}
const live = (messages: TimelineMessageLike[], events: ExecutionEvent[]) =>
  groupLiveTurns({
    liveRunActive: true, currentRun: run, runEvents: events, savedTurnIds: collectSavedTurnIds(messages),
    humanTimes: messages.filter((m) => m.sender_type === 'human' && !m.pending).map((m) => new Date(m.created_at).getTime()),
  });

// --- 送った瞬間: まだ届いていない送信は一番下、3つの点はその下 -----------------------------
{
  const pending: TimelineMessageLike = { id: 'msg1', sender_type: 'human', created_at: iso(999999), pending: true };
  assert.deepStrictEqual(topToBottom({ messages: [pending], liveTurnGroups: [], showLiveTurn: true }), ['msg1', '__typing__']);
  // 端末の時計が大きくずれていても、届いていない送信は既存の行より下
  const old: TimelineMessageLike = { id: 'a0', sender_type: 'ai', created_at: iso(5000) };
  const skewed: TimelineMessageLike = { id: 'mine', sender_type: 'human', created_at: iso(-999999), pending: true };
  assert.deepStrictEqual(topToBottom({ messages: [old, skewed], liveTurnGroups: [], showLiveTurn: false }), ['a0', 'mine']);
}

// --- 作業中の追い連絡: その前の作業は上、その後の作業は下（同じターンでも分かれる） ---------
{
  const messages = [msg1, msg2];
  const groups = live(messages, [ev('e1', 3000), ev('e2', 10000), ev('e3', 20000), ev('e4', 25000)]);
  assert.deepStrictEqual(groups.map((g) => g.blocks.length), [2, 2]);
  assert.deepStrictEqual(topToBottom({ messages, liveTurnGroups: groups, showLiveTurn: true }),
    ['msg1', '__live__:tx', 'msg2', '__live__:tx#1']);
  // 3つの点は一番下の作業ログの吹き出しの中（吹き出しを2つにしない）
  const items = buildChatListItems({ messages, liveTurnGroups: groups, showLiveTurn: true });
  assert.deepStrictEqual(items.filter((i) => i.kind === 'live' && i.typing).map((i) => i.key), ['__live__:tx#1']);
}

// --- ターンの区別が無いイベントも、追い連絡をまたがない --------------------------------------
{
  const messages = [msg1, msg2];
  const groups = live(messages, [ev('e1', 3000, null), ev('e2', 20000, null)]);
  assert.deepStrictEqual(topToBottom({ messages, liveTurnGroups: groups, showLiveTurn: true }),
    ['msg1', '__live__:run:r1', 'msg2', '__live__:run:r1#1']);
}

// --- 返事は書き終えた時刻に置かれ、ライブ表示と入れ替わる（追い連絡より下） ---------------------
{
  const reply: TimelineMessageLike = { id: 'a1', sender_type: 'ai', created_at: iso(30000), ai_context: { turn_id: 'tx' } };
  const messages = [msg1, msg2, reply];
  const groups = live(messages, [ev('e1', 3000), ev('e3', 20000)]);
  assert.deepStrictEqual(groups, []);
  const msg3: TimelineMessageLike = { id: 'msg3', sender_type: 'human', created_at: iso(1), pending: true };
  assert.deepStrictEqual(topToBottom({ messages: [...messages, msg3], liveTurnGroups: groups, showLiveTurn: false }),
    ['msg1', 'msg2', 'a1', 'msg3']);
}

// --- 同じ時刻なら 本人 → 作業ログ → ダン ------------------------------------------------------
{
  const human: TimelineMessageLike = { id: 'h', sender_type: 'human', created_at: iso(40000) };
  const ai: TimelineMessageLike = { id: 'x', sender_type: 'system', created_at: iso(40000) };
  const groups = live([msg1], [ev('e9', 40000, 'ty')]);
  assert.deepStrictEqual(topToBottom({ messages: [ai, human], liveTurnGroups: groups, showLiveTurn: false }),
    ['h', '__live__:ty', 'x']);
}

// --- mergeRunEvents: 増える方向にだけ足す ---------------------------------------------------------
{
  const base = [ev('e1', 1), ev('e2', 2)];
  const grown = mergeRunEvents(base, [ev('e2', 2), ev('e3', 3)], 'r1');
  assert.deepStrictEqual(grown.map((e) => e.id), ['e1', 'e2', 'e3']);
  assert.strictEqual(mergeRunEvents(grown, [ev('e1', 1)], 'r1'), grown);
  const other = mergeRunEvents(grown, [{ ...ev('f1', 4), run_id: 'r2' }], 'r2');
  assert.deepStrictEqual(other.map((e) => e.id), ['f1']);
}

// --- 作業中の1行と一覧: 追い連絡で吹き出しが分かれても、それまでの一歩を消さず、秒数は最初に送った時から ----
// （2026-10-24 見直し: 一番下の吹き出しの一歩だけになり、秒数も追い連絡の時刻から数え直していた。PC と同じ決まり）
{
  const act = (id: string, at: number, activity: string, turn = 'tx'): ExecutionEvent =>
    ({ ...ev(id, at, turn), metadata: { activity } });
  const events = [act('e1', 3000, 'お店のページを見ています'), act('e2', 10000, '営業時間を調べています'),
    act('e3', 20000, '注文の画面を開いています'), act('e4', 25000, 'カートを確かめています', 'ty')];
  const messages = [msg1, msg2];
  const items = buildChatListItems({ messages, liveTurnGroups: live(messages, events), showLiveTurn: true });
  const bottom = items[0];
  assert.ok(bottom.kind === 'live' && bottom.typing);
  if (bottom.kind !== 'live') throw new Error('no live');
  assert.deepStrictEqual((bottom.live || []).map((st) => st.activity),
    ['お店のページを見ています', '営業時間を調べています', '注文の画面を開いています', 'カートを確かめています']);
  assert.strictEqual(bottom.startedAt, T);   // msg1 を送った時（msg2 の 15秒後からではない）
  // 追い連絡の直後でまだ次の一歩が無い時（一番下は本人の発言）も、それまでの一歩と最初の時刻を持つ
  const msg3: TimelineMessageLike = { id: 'msg3', sender_type: 'human', created_at: iso(30000) };
  const later = buildChatListItems({ messages: [msg1, msg2, msg3], liveTurnGroups: live([msg1, msg2, msg3], events), showLiveTurn: true })[0];
  assert.ok(later.kind === 'typing');
  if (later.kind !== 'typing') throw new Error('no typing');
  assert.strictEqual((later.live || []).length, 4);
  assert.strictEqual(later.startedAt, T);
  // 返事が保存された後の新しい頼みは、その発言の時刻から
  const reply: TimelineMessageLike = { id: 'a1', sender_type: 'ai', created_at: iso(40000) };
  const msg4: TimelineMessageLike = { id: 'msg4', sender_type: 'human', created_at: iso(50000) };
  const next = buildChatListItems({ messages: [msg1, msg2, reply, msg4], liveTurnGroups: [], showLiveTurn: true })[0];
  assert.ok(next.kind === 'typing' && next.startedAt === T + 50000);
}

console.log('chat timeline: all scenarios passed');
