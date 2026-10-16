// 部品の答えの、決着していない送信の置き場（frontend/src/lib/chat-shapes/answer-sends.ts）の試験。
// 部屋を離れて戻る・ページを読み直す、をまたいで同じ送信 ID を持ち続けること（VERIFY4 P1-1）と、その寿命。
// 実行: node --experimental-strip-types --test tests/chat_shapes_answer_sends.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  ANSWER_SENDS_STORAGE_KEY, KEEP_MS, MAX_ENTRIES, PAGE, answerSendKey, getAnswerSend, needsCheck, resetAnswerSendsForTest,
  setAnswerSend, subscribeAnswerSends,
} from '../frontend/src/lib/chat-shapes/answer-sends.ts';

function memoryStorage(init = {}) {
  const data = { ...init };
  return { data, getItem: (k) => (k in data ? data[k] : null), setItem: (k, v) => { data[k] = String(v); } };
}

const LINK = { message_id: 'aaaaaaaa-0000-4000-8000-000000000001', part: 'pe13cc096', kind: 'choice', value: 'A', question: '進め方' };
const KEY = answerSendKey('owner-1', 'room-1', LINK.message_id, LINK.part);
const entry = (over = {}) => ({ id: '33333333-0000-4000-8000-000000000003', status: 'unknown', value: 'A', text: '進め方 → A', answerTo: LINK, page: PAGE, at: 0, ...over });

test('鍵は本人・部屋・AI の発言・部品の4つ（どれかが違えば別の送信）', () => {
  assert.equal(KEY, `owner-1|room-1|${LINK.message_id}|${LINK.part}`);
  const others = [answerSendKey('owner-2', 'room-1', LINK.message_id, LINK.part), answerSendKey('owner-1', 'room-2', LINK.message_id, LINK.part),
    answerSendKey('owner-1', 'room-1', 'bbbbbbbb-0000-4000-8000-000000000001', LINK.part), answerSendKey('owner-1', 'room-1', LINK.message_id, 'pe13cc096-1')];
  assert.equal(new Set([KEY, ...others]).size, 5);
});

test('部品の外に持つので、部品が作り直されても同じ送信 ID が残る（知らせも届く）', () => {
  resetAnswerSendsForTest(memoryStorage());
  let calls = 0;
  const off = subscribeAnswerSends(() => { calls += 1; });
  setAnswerSend(KEY, entry());
  assert.equal(getAnswerSend(KEY).id, entry().id);
  assert.equal(calls, 1);
  setAnswerSend(KEY, null);
  assert.equal(getAnswerSend(KEY), null);
  off();
  setAnswerSend(KEY, entry());
  assert.equal(calls, 2);
});

test('決着していない状態だけページの読み直しをまたぐ（保存済みの一時状態と「聞いている途中」は残さない）', () => {
  const st = memoryStorage();
  resetAnswerSendsForTest(st);
  const keys = ['sending', 'unknown', 'failed', 'saved'].map((s, i) => [s, answerSendKey('owner-1', 'room-1', LINK.message_id, `p0000000${i}`)]);
  for (const [s, k] of keys) setAnswerSend(k, entry({ status: s, checking: true }));
  const stored = JSON.parse(st.data[ANSWER_SENDS_STORAGE_KEY]);
  assert.deepEqual(Object.values(stored).map((e) => e.status).sort(), ['failed', 'sending', 'unknown']);
  assert.ok(Object.values(stored).every((e) => e.checking === false));
  resetAnswerSendsForTest(st);   // ページの読み直し
  for (const [s, k] of keys) {
    const e = getAnswerSend(k);
    if (s === 'saved') assert.equal(e, null);
    else {
      assert.equal(e.status, s);
      assert.equal(e.checking, false);
    }
  }
});

test('押せるようにする前の確かめが要るのは、分からない・失敗・ほかのページの送信中', () => {
  assert.equal(needsCheck(entry({ status: 'unknown' })), true);
  assert.equal(needsCheck(entry({ status: 'failed' })), true);
  assert.equal(needsCheck(entry({ status: 'sending', page: 'another-page' })), true);   // 読み直す前のページの送信: その通信はもう無い
  assert.equal(needsCheck(entry({ status: 'sending' })), false);                         // このページで通信中
  assert.equal(needsCheck(entry({ status: 'saved' })), false);
});

test('寿命は7日・数は200件まで（古い順に消す）。壊れた中身は読まない', () => {
  const now = Date.now();
  const old = { ...entry(), at: now - KEEP_MS - 1000 };
  const fresh = { ...entry({ id: '44444444-0000-4000-8000-000000000004' }), at: now - 1000 };
  resetAnswerSendsForTest(memoryStorage({ [ANSWER_SENDS_STORAGE_KEY]: JSON.stringify({ old: old, fresh: fresh }) }));
  assert.equal(getAnswerSend('old'), null);
  assert.equal(getAnswerSend('fresh').id, fresh.id);
  const st = memoryStorage();
  resetAnswerSendsForTest(st);
  for (let i = 0; i < MAX_ENTRIES + 5; i++) setAnswerSend(`k${i}`, entry({ id: `id-${i}` }));
  const kept = Object.keys(JSON.parse(st.data[ANSWER_SENDS_STORAGE_KEY]));
  assert.equal(kept.length, MAX_ENTRIES);
  resetAnswerSendsForTest(memoryStorage({ [ANSWER_SENDS_STORAGE_KEY]: '{not json' }));
  assert.equal(getAnswerSend(KEY), null);
  resetAnswerSendsForTest(memoryStorage({ [ANSWER_SENDS_STORAGE_KEY]: JSON.stringify({ [KEY]: { id: 1, status: 'unknown' } }) }));
  assert.equal(getAnswerSend(KEY), null);   // 形の違う物は読まない
});

test('保存先が使えない時も同じタブの中では持ち続ける', () => {
  resetAnswerSendsForTest({ getItem: () => { throw new Error('denied'); }, setItem: () => { throw new Error('denied'); } });
  setAnswerSend(KEY, entry());
  assert.equal(getAnswerSend(KEY).id, entry().id);
});
