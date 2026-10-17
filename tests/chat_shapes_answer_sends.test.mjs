// 部品の答えの送信の置き場（frontend/src/lib/chat-shapes/answer-sends.ts）の試験。
// 部屋を離れて戻る・ページを読み直す・ほかのタブ、をまたいで同じ送信 ID を持ち続けること（VERIFY4 P1-1・VERIFY5 P1-1）、
// 送信の状態が前にしか進まないこと、照会の回数（VERIFY5 P2-1）、保存と開始を分けた戻り道（VERIFY5 P2-2）。
// 実行: node --experimental-strip-types --test tests/chat_shapes_answer_sends.test.mjs
import test, { mock } from 'node:test';
import assert from 'node:assert/strict';
import {
  ANSWER_SENDS_STORAGE_KEY, KEEP_MS, KICK_DELAYS, MAX_ENTRIES, PAGE, START_CHECK_DELAYS, answerSendHere, answerSendKey, attachAnswerSend,
  getAnswerSend, mergeAnswerSend, needsCheck, recheckAnswerSend, resetAnswerSendsForTest, sendAnswer, setAnswerSend, startReplyOf,
  subscribeAnswerSends,
} from '../frontend/src/lib/chat-shapes/answer-sends.ts';

const SOURCE = new URL('../frontend/src/lib/chat-shapes/answer-sends.ts', import.meta.url).href;
let tabCount = 0;
/** 同じブラウザの別のタブ（同じファイルの別の読み込み＝別のメモリ。保存先は共有） */
async function openTab(storage) {
  tabCount += 1;
  const tab = await import(`${SOURCE}?tab${tabCount}`);
  tab.resetAnswerSendsForTest(storage);
  return tab;
}

function memoryStorage(init = {}) {
  const data = { ...init };
  return { data, getItem: (k) => (k in data ? data[k] : null), setItem: (k, v) => { data[k] = String(v); } };
}

const flush = async () => { for (let i = 0; i < 20; i++) await new Promise((r) => setImmediate(r)); };

const LINK = { message_id: 'aaaaaaaa-0000-4000-8000-000000000001', part: 'pe13cc096', kind: 'choice', value: 'A', question: '進め方' };
const KEY = answerSendKey('owner-1', 'room-1', LINK.message_id, LINK.part);
const ID = '33333333-0000-4000-8000-000000000003';
const entry = (over = {}) => ({ id: ID, status: 'unknown', value: 'A', text: '進め方 → A', answerTo: LINK, page: PAGE, at: 0, ...over });
const stored = (st) => JSON.parse(st.data[ANSWER_SENDS_STORAGE_KEY] || '{}');

/** 偽のサーバー: ask（保存されたか）と submit（送る）の呼ばれ方を記録し、答えを差し替えられる */
function fakeServer() {
  const s = {
    asks: [], submits: [],
    saved: true, started: true, start: 'begun', askFails: false,
    submitResult: 'saved', startSeen: false,
    ask: async (id) => {
      s.asks.push(id);
      if (s.askFails) throw new Error('503');
      return s.saved ? { saved: true, started: s.started, start: s.start } : { saved: false };
    },
    submit: async (text, answerTo, id, opts) => {
      s.submits.push({ id, background: !!opts?.background });
      const result = s.submitResult;
      setImmediate(() => opts?.onEnded?.(s.startSeen));
      if (result === 'unknown') throw new Error('unknown');
      if (result === 'failed') throw new Error('not saved');
      if (result === 'busy') throw new Error('busy');
      return { id };
    },
  };
  return s;
}

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
  assert.equal(getAnswerSend(KEY).id, ID);
  assert.equal(calls, 1);
  off();
  setAnswerSend(KEY, entry({ status: 'failed' }));
  assert.equal(calls, 1);
  assert.equal(getAnswerSend(KEY).status, 'failed');
});

test('保存済みも含めて送信 ID と事実がページの読み直しをまたぐ。表示ごとの印は書かない', () => {
  const st = memoryStorage();
  resetAnswerSendsForTest(st);
  const keys = ['sending', 'unknown', 'failed', 'saved'].map((s, i) => [s, answerSendKey('owner-1', 'room-1', LINK.message_id, `p0000000${i}`)]);
  for (const [s, k] of keys) setAnswerSend(k, entry({ status: s, ...(s === 'saved' ? { start: 'pending' } : {}), checking: true, seenBy: 'x', kicked: true, seen: true }));
  const values = Object.values(stored(st));
  assert.deepEqual(values.map((e) => e.status).sort(), ['failed', 'saved', 'sending', 'unknown']);
  for (const e of values) for (const mark of ['checking', 'seenBy', 'kicked', 'seen', 'again']) assert.equal(mark in e, false, mark);
  resetAnswerSendsForTest(st);   // ページの読み直し
  for (const [s, k] of keys) {
    const e = getAnswerSend(k);
    assert.equal(e.id, ID);
    assert.equal(e.status, s);
    assert.equal(e.start, s === 'saved' ? 'pending' : undefined);
  }
});

test('前にしか進まない: 同じ ID の保存済みは戻らず、違う ID はこちらの続きの時だけ取り込む', () => {
  const saved = entry({ status: 'saved', start: 'pending', at: 1 });
  assert.equal(mergeAnswerSend(saved, entry({ status: 'unknown', at: 9 })), saved);                 // 後の「分からない」でも戻らない
  assert.equal(mergeAnswerSend(entry({ at: 9 }), saved).status, 'saved');                             // ほかの見え方の保存済みは取り込む
  assert.equal(mergeAnswerSend(saved, entry({ status: 'saved', start: 'started' })).start, 'started');
  assert.equal(mergeAnswerSend(entry({ status: 'saved', start: 'started' }), saved).start, 'started');
  const mine = entry({ status: 'unknown', at: 5 });
  assert.equal(mergeAnswerSend(mine, undefined), mine);                                              // 無いことは「送っていない」の根拠にしない
  assert.equal(mergeAnswerSend(mine, entry({ id: 'other', status: 'saved', at: 9 })), mine);          // 関係の分からない ID には移らない
  const next = entry({ id: 'next', status: 'sending', prev: [ID], at: 9 });
  assert.equal(mergeAnswerSend(mine, next), next);                                                   // こちらが取り消された後の続き
  assert.equal(mergeAnswerSend(next, mine), next);                                                   // 古い方には戻らない
  assert.equal(mergeAnswerSend(entry({ status: 'failed', at: 1 }), entry({ status: 'unknown', at: 2 })).status, 'unknown');
  // このタブ自身の書き込みも同じ決まりを通る
  resetAnswerSendsForTest(memoryStorage());
  setAnswerSend(KEY, saved);
  setAnswerSend(KEY, entry({ status: 'failed' }));
  assert.equal(getAnswerSend(KEY).status, 'saved');
  setAnswerSend(KEY, entry({ id: 'unrelated', status: 'sending' }));
  assert.equal(getAnswerSend(KEY).id, ID);
});

test('VERIFY5 P1-1: ほかのタブが保存を確かめると、こちらは保存済みになる（未送信に戻って別 ID で送れることはない）', async () => {
  const st = memoryStorage();
  const a = await openTab(st);
  const b = await openTab(st);
  const server = fakeServer();
  // A: 保存されたが応答を失い、確かめにも失敗した（unknown）
  a.attachAnswerSend(KEY, { ask: server.ask, submit: server.submit });
  server.submitResult = 'unknown';
  a.sendAnswer(KEY, { id: ID, value: 'A', text: '進め方 → A', answerTo: LINK, page: a.PAGE });
  await flush();
  assert.equal(a.getAnswerSend(KEY).status, 'unknown');
  b.storageEventForTest();
  assert.equal(b.getAnswerSend(KEY).status, 'unknown');
  // B（後で開いた別のタブ）が描かれた時に確かめると保存済み
  b.attachAnswerSend(KEY, { ask: server.ask, submit: server.submit });
  await b.resumeAnswerSend(KEY);
  assert.equal(b.getAnswerSend(KEY).status, 'saved');
  assert.equal(stored(st)[KEY].status, 'saved');                // 共有する事実
  a.storageEventForTest();
  const ea = a.getAnswerSend(KEY);
  assert.equal(ea.status, 'saved');                             // 前は idle（置き場から消えて押せた）
  assert.equal(ea.id, ID);
  assert.equal(a.isGone(ea, false), false);                     // A はこの行を記録で見ていない: 取り消しではない
  // 保存先が空になった・項目が消えた知らせでも、A は持ち続ける
  st.data[ANSWER_SENDS_STORAGE_KEY] = '{}';
  a.storageEventForTest();
  assert.equal(a.getAnswerSend(KEY).id, ID);
  assert.equal(a.getAnswerSend(KEY).status, 'saved');
});

test('故障なしで2タブを先に開いた時も、送った方の保存済みがもう片方に届き、別 ID は作られない', async () => {
  const st = memoryStorage();
  const a = await openTab(st);
  const b = await openTab(st);
  const server = fakeServer();
  a.attachAnswerSend(KEY, { ask: server.ask, submit: server.submit });
  b.attachAnswerSend(KEY, { ask: server.ask, submit: server.submit });
  await b.resumeAnswerSend(KEY);   // B は答える前に描かれた（置き場は空）
  a.sendAnswer(KEY, { id: ID, value: 'A', text: '進め方 → A', answerTo: LINK, page: a.PAGE });
  b.storageEventForTest();
  assert.equal(b.getAnswerSend(KEY).status, 'sending');         // ほかのタブの送信中（押せない）
  await flush();
  b.storageEventForTest();
  assert.equal(b.getAnswerSend(KEY).status, 'saved');
  assert.equal(b.getAnswerSend(KEY).id, ID);
  assert.deepEqual(server.submits.map((x) => x.id), [ID]);
});

test('このタブが送っている間は、ほかのタブの「失敗」を取り込まずに自分の結果を待つ', async () => {
  const st = memoryStorage();
  const a = await openTab(st);
  const b = await openTab(st);
  let release;
  const slow = { ask: async () => ({ saved: false }), submit: (t, at, id, opts) => new Promise((r) => { release = () => { r({ id }); setImmediate(() => opts?.onEnded?.(true)); }; }) };
  a.attachAnswerSend(KEY, slow);
  a.sendAnswer(KEY, { id: ID, value: 'A', text: '進め方 → A', answerTo: LINK, page: a.PAGE });
  b.storageEventForTest();
  b.attachAnswerSend(KEY, slow);
  await b.resumeAnswerSend(KEY);                                // B が描かれて聞くと、まだ保存されていない
  assert.equal(b.getAnswerSend(KEY).status, 'failed');
  a.storageEventForTest();
  assert.equal(a.getAnswerSend(KEY).status, 'sending');
  release();
  await flush();
  assert.equal(a.getAnswerSend(KEY).status, 'saved');
  b.storageEventForTest();
  assert.equal(b.getAnswerSend(KEY).status, 'saved');
});

test('VERIFY5 P2-1: 保存が分からない2タブは、取り込みでは聞き直さない（照会は描かれた時の1回ずつ）', async () => {
  const st = memoryStorage();
  const a = await openTab(st);
  const b = await openTab(st);
  const server = fakeServer();
  server.askFails = true;
  server.submitResult = 'unknown';
  a.attachAnswerSend(KEY, { ask: server.ask, submit: server.submit });
  b.attachAnswerSend(KEY, { ask: server.ask, submit: server.submit });
  a.sendAnswer(KEY, { id: ID, value: 'A', text: '進め方 → A', answerTo: LINK, page: a.PAGE });
  await flush();
  for (let i = 0; i < 50; i++) { b.storageEventForTest(); a.storageEventForTest(); await flush(); }
  assert.equal(server.asks.length, 0);                          // 取り込みだけでは聞かない（前は2秒で約550回）
  await Promise.all([a.resumeAnswerSend(KEY), a.resumeAnswerSend(KEY), b.resumeAnswerSend(KEY)]);   // 描かれた時（同じタブの同時は1つにまとまる）
  assert.equal(server.asks.length, 2);
  for (let i = 0; i < 50; i++) { b.storageEventForTest(); a.storageEventForTest(); await flush(); }
  assert.equal(server.asks.length, 2);
  assert.equal(a.getAnswerSend(KEY).status, 'unknown');
  assert.equal(a.answerSendHere(KEY).unsure, ID);
  assert.equal(a.answerSendHere(KEY).checking, false);
  assert.equal(b.getAnswerSend(KEY).status, 'unknown');
});

test('取り消しを確かめた後だけ新しい ID（前の ID を prev に持ち、ほかのタブはそれを続きとして取り込む）', async () => {
  const st = memoryStorage();
  const a = await openTab(st);
  const b = await openTab(st);
  const server = fakeServer();
  a.attachAnswerSend(KEY, { ask: server.ask, submit: server.submit });
  a.sendAnswer(KEY, { id: ID, value: 'A', text: '進め方 → A', answerTo: LINK, page: a.PAGE });
  await flush();
  b.storageEventForTest();
  const e = a.getAnswerSend(KEY);
  assert.equal(a.isGone(e, false), false);   // まだ記録で見ていない
  a.noteInRecord(ID);
  assert.equal(a.isGone(e, true), false);
  assert.equal(a.isGone(e, false), true);    // 記録に載った後で消えた: 取り消し
  assert.equal(b.isGone(b.getAnswerSend(KEY), false), false);   // B は確かめていない（押せない）
  a.sendAnswer(KEY, { id: 'next-id', value: 'B', text: '進め方 → B', answerTo: { ...LINK, value: 'B' }, page: a.PAGE, prev: [ID] });
  await flush();
  b.storageEventForTest();
  assert.equal(b.getAnswerSend(KEY).id, 'next-id');
  // 照会で「もう無い」と分かった保存済みも取り消し（読み直したタブ）
  const c = await openTab(st);
  setAnswerSendIn(c, entry({ id: 'gone-id', status: 'saved', start: 'started' }), answerSendKey('owner-1', 'room-1', LINK.message_id, 'p2'));
  server.saved = false;
  c.attachAnswerSend(answerSendKey('owner-1', 'room-1', LINK.message_id, 'p2'), { ask: server.ask, submit: server.submit });
  await c.resumeAnswerSend(answerSendKey('owner-1', 'room-1', LINK.message_id, 'p2'));
  const gone = c.getAnswerSend(answerSendKey('owner-1', 'room-1', LINK.message_id, 'p2'));
  assert.equal(gone.status, 'saved');        // 事実は保存済みのまま
  assert.equal(c.isGone(gone, false), true); // このタブでは取り消しと確かめた
});
function setAnswerSendIn(tab, e, key) { tab.setAnswerSend(key, e); }

test('開始の状態の読み方: null は始まったことにしない', () => {
  assert.equal(startReplyOf({ saved: true, started: true }, true), 'started');
  assert.equal(startReplyOf({ saved: true, started: false }, true), 'not_started');
  assert.equal(startReplyOf({ saved: true, started: null, start: 'taken' }, true), 'starting');
  assert.equal(startReplyOf({ saved: true, started: null }, true), 'starting');
  assert.equal(startReplyOf({ saved: true, started: null, start: 'unknown' }, true), 'unknown');
  assert.equal(startReplyOf({ saved: true }, true), 'unknown');     // 古い Core（started を返さない）: 送り直さない
  assert.equal(startReplyOf({ id: 'x' }, false), null);             // echo で保存が分かった: 開始は分からない
});

function attachTo(server) {
  attachAnswerSend(KEY, { ask: server.ask, submit: server.submit });
}
async function sendOnce() {
  sendAnswer(KEY, { id: ID, value: 'A', text: '進め方 → A', answerTo: LINK, page: PAGE });
  await flush();
}
/** 偽の時計を進めながら、条件が満たされるまで（最大 limit 回） */
async function tickUntil(cond, step = 1000, limit = 400) {
  for (let i = 0; i < limit && !cond(); i++) { mock.timers.tick(step); await flush(); }
  return cond();
}

test('VERIFY5 P2-2 (1)(2): 開始が確かでない保存済みの答えは間をあけて確かめ、始まっていない時だけ同じ ID で送り直す。送り直しが届かなくても続ける', async () => {
  mock.timers.enable({ apis: ['setTimeout'] });
  try {
    resetAnswerSendsForTest(memoryStorage());
    const server = fakeServer();
    server.started = null;
    server.start = 'taken';
    attachTo(server);
    await sendOnce();
    // echo で保存（通信の中で始まった印なし）→ 終わった後に聞く → 誰かが始めようとしている（null）: 始まったことにしない
    assert.deepEqual(server.asks, [ID]);
    assert.equal(getAnswerSend(KEY).start, 'pending');
    mock.timers.tick(START_CHECK_DELAYS[0] - 1);
    await flush();
    assert.equal(server.asks.length, 1);                        // 間をあける（すぐには聞き直さない）
    // （1）null → false: 次の確かめで分かり、同じ ID で送り直す。その送り直しは届かない（ほかの通信中・Core に届く前の失敗）
    server.started = false;
    server.submitResult = 'busy';
    assert.ok(await tickUntil(() => server.submits.some((x) => x.background)));
    // （2）送り直しが届かなくても、間をあけてまた確かめ、まだ始まっていなければまた送り直す
    assert.ok(await tickUntil(() => server.submits.filter((x) => x.background).length >= 2));
    server.submitResult = 'saved';
    server.startSeen = true;                                     // 次の送り直しで始まる
    assert.ok(await tickUntil(() => getAnswerSend(KEY).start === 'started'));
    assert.deepEqual([...new Set(server.submits.map((x) => x.id))], [ID]);   // いつも同じ ID（サーバーは1回しか始めない）
    assert.ok(server.submits.filter((x) => x.background).length <= KICK_DELAYS.length);
    const asked = server.asks.length;
    for (let i = 0; i < 10; i++) { mock.timers.tick(64000); await flush(); }
    assert.equal(server.asks.length, asked);                     // 始まったら聞かない
  } finally {
    mock.timers.reset();
  }
});

test('開始の確かめ: 通信の中で始まった印を見たら聞かない・サーバーが知らなければ止める・使い切ったら止めて「確かめる」', async () => {
  mock.timers.enable({ apis: ['setTimeout'] });
  try {
    resetAnswerSendsForTest(memoryStorage());
    let server = fakeServer();
    server.startSeen = true;
    attachTo(server);
    await sendOnce();
    assert.equal(server.asks.length, 0);
    assert.equal(getAnswerSend(KEY).start, 'started');

    resetAnswerSendsForTest(memoryStorage());
    server = fakeServer();
    server.started = null;
    server.start = 'unknown';                   // この Core は知らない（再起動の前の保存）: 送り直さない・聞き続けない
    attachTo(server);
    await sendOnce();
    for (let i = 0; i < 10; i++) { mock.timers.tick(64000); await flush(); }
    assert.equal(server.asks.length, 1);
    assert.equal(server.submits.length, 1);
    assert.equal(getAnswerSend(KEY).start, 'unknowable');

    resetAnswerSendsForTest(memoryStorage());
    server = fakeServer();
    server.askFails = true;                      // 聞けない: 間隔をあけて、使い切ったら止める
    attachTo(server);
    await sendOnce();
    for (let i = 0; i < 20; i++) { mock.timers.tick(64000); await flush(); }
    assert.equal(server.asks.length, 1 + START_CHECK_DELAYS.length);
    assert.equal(answerSendHere(KEY).gaveUp, ID);
    assert.equal(getAnswerSend(KEY).start, 'pending');   // 始まったことにはしない
    server.askFails = false;
    await recheckAnswerSend(KEY);                         // 「確かめる」
    await flush();
    assert.equal(getAnswerSend(KEY).start, 'started');
    assert.equal(answerSendHere(KEY).gaveUp, null);

    // 送り直しを使い切っても始まらない: 止めて「確かめる」（二重には送らない）
    resetAnswerSendsForTest(memoryStorage());
    server = fakeServer();
    server.started = false;
    attachTo(server);
    await sendOnce();
    for (let i = 0; i < 40; i++) { mock.timers.tick(64000); await flush(); }
    assert.equal(server.submits.filter((x) => x.background).length, KICK_DELAYS.length);
    assert.equal(answerSendHere(KEY).gaveUp, ID);
  } finally {
    mock.timers.reset();
  }
});

test('描いている部品が無くなったら開始の確かめは止まり、次に描かれた時に続ける', async () => {
  mock.timers.enable({ apis: ['setTimeout'] });
  try {
    resetAnswerSendsForTest(memoryStorage());
    const server = fakeServer();
    server.started = null;
    server.start = 'taken';
    const detach = attachAnswerSend(KEY, { ask: server.ask, submit: server.submit });
    await sendOnce();
    detach();                                                    // 部屋を離れた
    for (let i = 0; i < 10; i++) { mock.timers.tick(64000); await flush(); }
    assert.equal(server.asks.length, 1);
    server.started = true;
    attachAnswerSend(KEY, { ask: server.ask, submit: server.submit });
    const { resumeAnswerSend } = await import('../frontend/src/lib/chat-shapes/answer-sends.ts');
    await resumeAnswerSend(KEY);                                 // 戻った: 描かれた時の確かめ
    await flush();
    assert.equal(server.asks.length, 2);
    assert.equal(getAnswerSend(KEY).start, 'started');
  } finally {
    mock.timers.reset();
  }
});

test('押せるようにする前・描かれた時の確かめが要る時', () => {
  resetAnswerSendsForTest(memoryStorage());
  assert.equal(needsCheck(entry({ status: 'unknown' })), true);
  assert.equal(needsCheck(entry({ status: 'failed' })), true);
  assert.equal(needsCheck(entry({ status: 'sending', page: 'another-page' })), true);   // このタブが送っていない送信中
  assert.equal(needsCheck(entry({ status: 'sending' }), false, true), false);            // このタブが通信中
  assert.equal(needsCheck(entry({ status: 'saved', start: 'started' }), true), false);    // 記録にある・始まった
  assert.equal(needsCheck(entry({ status: 'saved', start: 'started' }), false), true);    // このタブではまだ確かめていない
  assert.equal(needsCheck(entry({ status: 'saved', start: 'pending' }), true), true);     // 始まったと確かでない
});

test('寿命は7日・数は200件まで（新しい方を残す）。壊れた中身は読まない', () => {
  const now = Date.now();
  const old = { ...entry(), at: now - KEEP_MS - 1000 };
  const fresh = { ...entry({ id: '44444444-0000-4000-8000-000000000004' }), at: now - 1000 };
  resetAnswerSendsForTest(memoryStorage({ [ANSWER_SENDS_STORAGE_KEY]: JSON.stringify({ old, fresh }) }));
  assert.equal(getAnswerSend('old'), null);
  assert.equal(getAnswerSend('fresh').id, fresh.id);
  const st = memoryStorage();
  resetAnswerSendsForTest(st);
  for (let i = 0; i < MAX_ENTRIES + 5; i++) setAnswerSend(`k${i}`, entry({ id: `id-${i}` }));
  assert.equal(Object.keys(stored(st)).length, MAX_ENTRIES);
  resetAnswerSendsForTest(memoryStorage({ [ANSWER_SENDS_STORAGE_KEY]: '{not json' }));
  assert.equal(getAnswerSend(KEY), null);
  resetAnswerSendsForTest(memoryStorage({ [ANSWER_SENDS_STORAGE_KEY]: JSON.stringify({ [KEY]: { id: 1, status: 'unknown' } }) }));
  assert.equal(getAnswerSend(KEY), null);   // 形の違う物は読まない
});

test('保存先が使えない時も同じタブの中では持ち続ける', () => {
  resetAnswerSendsForTest({ getItem: () => { throw new Error('denied'); }, setItem: () => { throw new Error('denied'); } });
  setAnswerSend(KEY, entry());
  assert.equal(getAnswerSend(KEY).id, ID);
});
