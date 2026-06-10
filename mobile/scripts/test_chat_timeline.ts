// チャットタイムライン並び順のテスト（追い連絡の時系列保持）。
//
// シナリオ: msg1 送信 → ダンのターンX開始 → 途中で追い連絡 msg2 →
// 境界でターンXの部分回答が保存され msg2 が読み込まれる → ターンY開始 →
// 最終回答。各段階で「画面の並びが常に実時刻の時系列」であることを確認する。
//
// 実行: cd mobile && npx tsc chatTimeline.ts scripts/test_chat_timeline.ts \
//         --outDir .testbuild --module commonjs --target es2020 --strict --skipLibCheck
//       node .testbuild/scripts/test_chat_timeline.js
import * as assert from 'assert';
import {
  buildChatListItems,
  collectSavedTurnIds,
  computeUnreadFollowupIds,
  groupLiveTurns,
  type AgentRun,
  type ExecutionEvent,
  type TimelineMessageLike,
} from '../chatTimeline';

const T = 1750000000000;
const iso = (offsetMs: number) => new Date(T + offsetMs).toISOString();

const run: AgentRun = { id: 'r1', project_id: 'p1', state: 'running', created_at: iso(2000) };

const msg1: TimelineMessageLike = { id: 'msg1', sender_type: 'human', created_at: iso(0) };
// 追い連絡（ターンX実行中の t+15s に送信）
const msg2: TimelineMessageLike = { id: 'msg2', sender_type: 'human', created_at: iso(15000) };
// ターンXの部分回答。バックエンドは created_at=ターン開始時刻 で保存する。
const partialX: TimelineMessageLike = {
  id: 'aiX', sender_type: 'ai', created_at: iso(3000), ai_context: { turn_id: 'tx' },
};
// ターンY（追い連絡を読み込んだ後）の最終回答。
const finalY: TimelineMessageLike = {
  id: 'aiY', sender_type: 'ai', created_at: iso(20000), ai_context: { turn_id: 'ty' },
};

const ev = (id: string, turnId: string, offsetMs: number, seq: number): ExecutionEvent => ({
  id, run_id: 'r1', turn_id: turnId, event_type: 'reasoning', content: id, seq, created_at: iso(offsetMs),
});
const turnXEvents = [ev('ex1', 'tx', 3000, 1), ev('ex2', 'tx', 10000, 2)];
const turnYEvents = [ev('ey1', 'ty', 20000, 3)];

// 昇順（画面の上→下）のキー列にして比較する。
function ascendingKeys(args: Parameters<typeof buildChatListItems>[0]): string[] {
  return buildChatListItems(args).map((item) => item.key).reverse();
}

// --- Stage A: msg1 → ターンX実行中（追い連絡なし） --------------------------
{
  const messages = [msg1];
  const groups = groupLiveTurns({
    liveRunActive: true, currentRun: run, runEvents: turnXEvents,
    savedTurnIds: collectSavedTurnIds(messages),
  });
  assert.deepStrictEqual(ascendingKeys({ messages, liveTurnGroups: groups, showLiveTurn: true }),
    ['msg1', '__live__:tx']);
  assert.strictEqual(groups.length, 1);
}

// --- Stage B: 追い連絡 msg2 を送信（まだ読み込まれていない） ----------------
// 期待: msg1 → [ターンXの作業] → msg2（最下部・仮送信）
{
  const messages = [msg1, msg2];
  const pendingFollowups = { msg2: T + 15000 };
  const groups = groupLiveTurns({
    liveRunActive: true, currentRun: run, runEvents: turnXEvents,
    savedTurnIds: collectSavedTurnIds(messages),
  });
  assert.deepStrictEqual(ascendingKeys({ messages, liveTurnGroups: groups, showLiveTurn: true }),
    ['msg1', '__live__:tx', 'msg2']);
  // ターンXのイベントが msg2 の後に増えても（t+16s）、msg2 は最下部のまま
  const moreX = [...turnXEvents, ev('ex3', 'tx', 16000, 4)];
  const groups2 = groupLiveTurns({
    liveRunActive: true, currentRun: run, runEvents: moreX,
    savedTurnIds: collectSavedTurnIds(messages),
  });
  assert.deepStrictEqual(ascendingKeys({ messages, liveTurnGroups: groups2, showLiveTurn: true }),
    ['msg1', '__live__:tx', 'msg2']);
  // 仮送信のまま（ターンXは msg2 より前に始まった作業なので解除しない）
  const unread = computeUnreadFollowupIds({ pendingFollowups, messages, liveTurnGroups: groups2 });
  assert.deepStrictEqual([...unread], ['msg2']);
}

// --- Stage C: 境界でターンXの部分回答が保存され、ターンYが始まる ------------
// 期待: msg1 → 部分回答X（msg2より上に固定） → msg2（通常表示に） → [ターンYの作業]
{
  const messages = [msg1, msg2, partialX];
  const pendingFollowups = { msg2: T + 15000 };
  const savedTurnIds = collectSavedTurnIds(messages);
  const allEvents = [...turnXEvents, ...turnYEvents];
  const groups = groupLiveTurns({
    liveRunActive: true, currentRun: run, runEvents: allEvents, savedTurnIds,
  });
  // 保存済みターンXのライブ吹き出しは消え、ターンYだけがライブ
  assert.deepStrictEqual(groups.map((g) => g.key), ['ty']);
  assert.deepStrictEqual(ascendingKeys({ messages, liveTurnGroups: groups, showLiveTurn: true }),
    ['msg1', 'aiX', 'msg2', '__live__:ty']);
  // ターンY（msg2より後に開始）が始まった＝読み込まれた → 仮送信解除
  const unread = computeUnreadFollowupIds({ pendingFollowups, messages, liveTurnGroups: groups });
  assert.strictEqual(unread.size, 0);
  // 部分回答X（created_at=ターン開始 < msg2）だけでは解除されないことも確認
  const unreadBeforeY = computeUnreadFollowupIds({ pendingFollowups, messages, liveTurnGroups: [] });
  assert.deepStrictEqual([...unreadBeforeY], ['msg2']);
}

// --- Stage C': 境界の谷間（部分回答は保存済み・ターンYのイベント未着） ------
// 期待: 最下部にスピナーだけの吹き出し
{
  const messages = [msg1, msg2, partialX];
  const groups = groupLiveTurns({
    liveRunActive: true, currentRun: run, runEvents: turnXEvents,
    savedTurnIds: collectSavedTurnIds(messages),
  });
  assert.deepStrictEqual(groups, []);
  assert.deepStrictEqual(ascendingKeys({ messages, liveTurnGroups: groups, showLiveTurn: true }),
    ['msg1', 'aiX', 'msg2', '__live__']);
}

// --- Stage D: 完了（runが終わりライブ表示なし） ------------------------------
// 期待: msg1 → 部分回答X → msg2 → 最終回答Y（保存される並び＝表示の並び）
{
  const messages = [msg1, msg2, partialX, finalY];
  const groups = groupLiveTurns({
    liveRunActive: false, currentRun: { ...run, state: 'completed' }, runEvents: [],
    savedTurnIds: collectSavedTurnIds(messages),
  });
  assert.deepStrictEqual(ascendingKeys({ messages, liveTurnGroups: groups, showLiveTurn: false }),
    ['msg1', 'aiX', 'msg2', 'aiY']);
}

// --- 回帰: turn_id が無い旧イベントは run 単位で1吹き出しにまとまる ----------
{
  const legacy = [
    { ...ev('el1', '', 3000, 1), turn_id: null },
    { ...ev('el2', '', 4000, 2), turn_id: null },
  ];
  const groups = groupLiveTurns({
    liveRunActive: true, currentRun: run, runEvents: legacy, savedTurnIds: new Set(),
  });
  assert.deepStrictEqual(groups.map((g) => g.key), ['run:r1']);
  assert.deepStrictEqual(ascendingKeys({ messages: [msg1], liveTurnGroups: groups, showLiveTurn: true }),
    ['msg1', '__live__:run:r1']);
}

console.log('test_chat_timeline: all assertions passed');
