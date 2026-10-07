// node --test: drives hooks/core.mjs with a fake Jev, an in-memory ledger
// file and a fixed clock. No network, no real key.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  DEFAULTS,
  compactWithJev,
  currentTurnLength,
  maybeCompactAtTurnEnd,
  normalizeLedger,
  readConfig,
  sanitize,
  summaryLine,
} from '../hooks/core.mjs';

const KEY = 'tsk_TEST_SECRET_KEY_0123456789';
const LEDGER = 'C:/fake/.dan/workspace/memory/.compact_jev_ledger.json';
const NOW = new Date('2026-10-07T03:00:00Z');

function memFs(initial = {}) {
  const files = new Map(Object.entries(initial));
  return {
    files,
    read: async (p) => {
      if (!files.has(p)) throw new Error(`ENOENT ${p}`);
      return files.get(p);
    },
    write: async (p, t) => {
      files.set(p, t);
    },
    exists: async (p) => files.has(p),
  };
}

/** A transcript: an opening prompt, `calls` tool calls with big results, then `tail` text-only messages (pinned as recent). */
function transcript(calls = 8, tail = 6, resultChars = 1500) {
  const messages = [{ role: 'user', text: 'Fix the failing test. Never edit src/generated.', toolUses: [], handle: 'h0' }];
  for (let i = 0; i < calls; i++) {
    const id = `toolu_${i}`;
    const text = `result ${i} ` + 'x'.repeat(resultChars);
    messages.push({
      role: 'assistant',
      text: i % 2 ? '' : `Looking at file ${i}.`,
      toolUses: [{ tool_use_id: id, tool: i % 2 ? 'Bash' : 'Read', input: { file_path: `src/${i}.ts` }, text }],
      handle: `ha${i}`,
    });
    messages.push({
      role: 'user',
      text: '',
      toolUses: [],
      toolResults: [{ tool_use_id: id, text, isError: false }],
      handle: `hu${i}`,
    });
  }
  for (let i = 0; i < tail; i++) {
    messages.push({ role: i % 2 ? 'assistant' : 'user', text: `recent ${i}: keep this sentence exactly.`, toolUses: [], handle: `ht${i}` });
  }
  return messages;
}

/** A fake Jev: answers every noul question with the given probabilities. */
function fakeJev({ keepCall = 0.1, keepResult = 0.1, usage = true, status = 200, bodyText, throwError } = {}) {
  const calls = [];
  const fetchFn = async (url, init) => {
    calls.push({ url, init });
    if (throwError) throw throwError;
    if (status !== 200) return { status, ok: false, text: bodyText ?? `error ${status}` };
    const body = JSON.parse(init.body);
    const answers = {};
    for (const name of Object.keys(body.questions)) {
      const p = name.startsWith('call_') ? keepCall : keepResult;
      answers[name] = { type: 'noul', noul: typeof p === 'function' ? p(name) : p };
    }
    const response = { model: 'jev-latest', answers };
    if (usage) response.usage = { input_tokens: 1000, output_tokens: 10 };
    return { status: 200, ok: true, text: JSON.stringify(response) };
  };
  return { calls, fetchFn };
}

function env(extra = {}) {
  return { TYPESAFE_API_KEY: KEY, DAN_COMPACT_LEDGER_PATH: LEDGER, ...extra };
}

function deps({ fs = memFs(), jev = fakeJev(), logs = [], environment = env() } = {}) {
  return {
    fs,
    jev,
    logs,
    d: { env: environment, fs, fetch: jev.fetchFn, log: (t) => logs.push(t), now: () => NOW },
  };
}

function texts(messages) {
  return messages.map((m) => m.text);
}

test('no key: falls back to the built-in summary without calling Jev, and the ledger says why', async () => {
  const { d, fs, jev, logs } = deps({ environment: { DAN_COMPACT_LEDGER_PATH: LEDGER } });
  let nextCalled = 0;
  const result = await compactWithJev(d, { trigger: 'auto', messages: transcript() }, async (e) => {
    nextCalled += 1;
    return { messages: e.messages.slice(-1) };
  });
  assert.equal(nextCalled, 1);
  assert.equal(result.messages.length, 1);
  assert.equal(jev.calls.length, 0);
  const ledger = JSON.parse(fs.files.get(LEDGER));
  assert.equal(ledger.month, '2026-10');
  assert.equal(ledger.yen, 0);
  assert.equal(ledger.runs, 0);
  assert.equal(ledger.last.outcome, 'fallback');
  assert.match(ledger.last.reason, /TYPESAFE_API_KEY/);
  assert.equal(logs.length, 1);
  assert.match(logs[0], /組み込み要約に戻す/);
});

test('compacts: drops stale tool calls, keeps every sentence verbatim, keeps engine objects, writes the ledger', async () => {
  const input = transcript(8, 6);
  const { d, fs, jev, logs } = deps();
  let nextCalled = 0;
  const result = await compactWithJev(d, { trigger: 'auto', messages: input }, async () => {
    nextCalled += 1;
    return { messages: [] };
  });
  assert.equal(nextCalled, 0, 'the hook answered for itself');
  assert.ok(jev.calls.length >= 1);
  assert.equal(jev.calls[0].init.headers.authorization, `Bearer ${KEY}`);
  // Every text that survives is one of the input texts, in order; the recent tail and the first prompt survive whole.
  const inputTexts = texts(input);
  let cursor = 0;
  for (const t of texts(result.messages)) {
    const at = inputTexts.indexOf(t, cursor);
    assert.ok(at >= 0, `text kept verbatim: ${t}`);
    cursor = at + 1;
  }
  assert.equal(result.messages[0], input[0], 'first message is the engine object (handle kept)');
  for (const m of input.slice(-6)) assert.ok(result.messages.includes(m), 'recent message is the engine object');
  // Stale calls were removed (fake Jev says 0.1 < threshold).
  const callsAfter = result.messages.reduce((n, m) => n + (m.toolUses?.length ?? 0), 0);
  assert.equal(callsAfter, 0);
  assert.ok(result.messages.length < input.length);
  const ledger = JSON.parse(fs.files.get(LEDGER));
  assert.equal(ledger.runs, 1);
  assert.ok(ledger.yen > 0);
  assert.equal(ledger.last.outcome, 'compacted');
  assert.equal(ledger.last.callsDropped, 8);
  assert.equal(ledger.last.requests, jev.calls.length);
  assert.equal(ledger.last.tokens, 1000 * jev.calls.length, 'cost uses the tokens Jev reported');
  assert.equal(ledger.last.yen, (1000 * jev.calls.length) / 1e6 * DEFAULTS.jpyPerMillionTokens);
  assert.equal(logs.length, 1);
  assert.match(logs[0], /Jev で短縮: 呼び出し 8 件を捨てた/);
  assert.match(logs[0], /\d+字→\d+字/);
  assert.ok(!logs[0].includes(KEY));
  assert.ok(!JSON.stringify(ledger).includes(KEY));
});

test('cost falls back to the library estimate when Jev reports no usage', async () => {
  const { d, fs } = deps({ jev: fakeJev({ usage: false }) });
  await compactWithJev(d, { trigger: 'auto', messages: transcript() }, async () => ({ messages: [] }));
  const ledger = JSON.parse(fs.files.get(LEDGER));
  assert.ok(ledger.last.tokens > 0);
  assert.ok(ledger.last.chars > ledger.last.tokens, 'estimate is below the character count');
});

test('monthly cap reached: Jev is not called and the built-in summary runs', async () => {
  const fs = memFs({ [LEDGER]: JSON.stringify({ month: '2026-10', yen: 100.5, runs: 40, last: null }) });
  const { d, jev, logs } = deps({ fs });
  let nextCalled = 0;
  await compactWithJev(d, { trigger: 'auto', messages: transcript() }, async () => {
    nextCalled += 1;
    return { messages: [] };
  });
  assert.equal(nextCalled, 1);
  assert.equal(jev.calls.length, 0);
  const ledger = JSON.parse(fs.files.get(LEDGER));
  assert.equal(ledger.yen, 100.5, 'nothing added');
  assert.equal(ledger.runs, 40);
  assert.match(ledger.last.reason, /monthly cap reached/);
  assert.match(logs[0], /monthly cap reached/);
});

test('cap is configurable: DAN_COMPACT_MONTHLY_CAP_JPY=1000 lets a 100.5 yen month continue', async () => {
  const fs = memFs({ [LEDGER]: JSON.stringify({ month: '2026-10', yen: 100.5, runs: 40, last: null }) });
  const { d, jev } = deps({ fs, environment: env({ DAN_COMPACT_MONTHLY_CAP_JPY: '1000' }) });
  const result = await compactWithJev(d, { trigger: 'auto', messages: transcript() }, async () => ({ messages: [] }));
  assert.ok(jev.calls.length >= 1);
  assert.ok(result.messages.length > 0);
  const ledger = JSON.parse(fs.files.get(LEDGER));
  assert.equal(ledger.runs, 41);
  assert.ok(ledger.yen > 100.5);
});

test('a ledger from another month starts over at zero', async () => {
  const fs = memFs({ [LEDGER]: JSON.stringify({ month: '2026-09', yen: 999, runs: 10, last: { outcome: 'compacted' } }) });
  const { d, jev } = deps({ fs });
  await compactWithJev(d, { trigger: 'auto', messages: transcript() }, async () => ({ messages: [] }));
  assert.ok(jev.calls.length >= 1);
  const ledger = JSON.parse(fs.files.get(LEDGER));
  assert.equal(ledger.month, '2026-10');
  assert.equal(ledger.runs, 1);
  assert.ok(ledger.yen < 1);
  assert.equal(normalizeLedger({ month: '2026-09', yen: 5, runs: 1 }, '2026-10').yen, 0);
  assert.equal(normalizeLedger('garbage', '2026-10').runs, 0);
});

test('Jev HTTP error: falls back, records what was spent, never leaks the key even when the error body echoes it', async () => {
  const jev = fakeJev({ status: 401, bodyText: `unauthorized: bad key ${KEY} rejected` });
  const { d, fs, logs } = deps({ jev });
  let nextCalled = 0;
  await compactWithJev(d, { trigger: 'auto', messages: transcript() }, async () => {
    nextCalled += 1;
    return { messages: [] };
  });
  assert.equal(nextCalled, 1);
  const ledger = JSON.parse(fs.files.get(LEDGER));
  assert.equal(ledger.last.outcome, 'fallback');
  assert.match(ledger.last.reason, /jev error/);
  assert.equal(ledger.runs, 1, 'a failed request still counts as a run');
  assert.ok(ledger.yen > 0, 'the request that failed is still paid for');
  assert.ok(!ledger.last.reason.includes(KEY));
  assert.ok(!JSON.stringify(ledger).includes(KEY));
  assert.ok(!logs.join('\n').includes(KEY));
  assert.match(logs[0], /\*\*\*/);
});

test('network failure (fetch throws): falls back without throwing', async () => {
  const jev = fakeJev({ throwError: new TypeError('fetch failed') });
  const { d, fs } = deps({ jev });
  let nextCalled = 0;
  const result = await compactWithJev(d, { trigger: 'auto', messages: transcript() }, async () => {
    nextCalled += 1;
    return { messages: ['summary'] };
  });
  assert.equal(nextCalled, 1);
  assert.deepEqual(result, { messages: ['summary'] });
  assert.match(JSON.parse(fs.files.get(LEDGER)).last.reason, /fetch failed/);
});

test('malformed Jev answers: falls back', async () => {
  const jev = { calls: [], fetchFn: async () => ({ status: 200, ok: true, text: '{"answers":{}}' }) };
  const { d, fs } = deps({ jev });
  let nextCalled = 0;
  await compactWithJev(d, { trigger: 'auto', messages: transcript() }, async () => {
    nextCalled += 1;
    return { messages: [] };
  });
  assert.equal(nextCalled, 1);
  assert.match(JSON.parse(fs.files.get(LEDGER)).last.reason, /Invalid Jev answer/);
});

test('reduction below the minimum: falls back (Jev says keep everything)', async () => {
  const { d, fs, logs } = deps({ jev: fakeJev({ keepCall: 0.9, keepResult: 0.9 }) });
  let nextCalled = 0;
  await compactWithJev(d, { trigger: 'auto', messages: transcript() }, async () => {
    nextCalled += 1;
    return { messages: [] };
  });
  assert.equal(nextCalled, 1);
  const ledger = JSON.parse(fs.files.get(LEDGER));
  assert.match(ledger.last.reason, /below minimum/);
  assert.equal(ledger.last.kept, 8);
  assert.match(logs[0], /below minimum/);
});

test('DAN_COMPACT_KEEP_THRESHOLD decides: 0.4 probabilities drop at 0.5 and stay at 0.3', async () => {
  const run = async (threshold) => {
    const { d, fs } = deps({ jev: fakeJev({ keepCall: 0.4, keepResult: 0.4 }), environment: env({ DAN_COMPACT_KEEP_THRESHOLD: threshold }) });
    let nextCalled = 0;
    await compactWithJev(d, { trigger: 'auto', messages: transcript() }, async () => {
      nextCalled += 1;
      return { messages: [] };
    });
    return { nextCalled, last: JSON.parse(fs.files.get(LEDGER)).last };
  };
  const strict = await run('0.5');
  assert.equal(strict.last.outcome, 'compacted');
  assert.equal(strict.last.callsDropped, 8);
  const lenient = await run('0.3');
  assert.equal(lenient.nextCalled, 1, 'everything kept → below minimum → built-in summary');
  assert.equal(lenient.last.kept, 8);
  assert.equal(lenient.last.keepThreshold, 0.3);
});

test('ledger write failure does not break the compaction', async () => {
  const fs = memFs();
  fs.write = async () => {
    throw new Error('EACCES');
  };
  const { d, logs } = deps({ fs });
  const result = await compactWithJev(d, { trigger: 'auto', messages: transcript() }, async () => ({ messages: [] }));
  assert.ok(result.messages.length > 0);
  assert.match(logs[0], /ledger not saved/);
});

test('turn end: compacts once the context reaches the percentage, not twice at the same token count, never when disabled', async () => {
  const calls = [];
  const session = (percent, tokens) => ({
    usage: async () => ({ context: { percent, tokens, window: 200000 } }),
    compact: async () => {
      calls.push(percent);
      return { messages: [] };
    },
  });
  const state = { compacting: false, lastTokens: undefined };
  const d = { env: env({ DAN_COMPACT_AT_PERCENT: '60' }), log: () => {} };
  const next = async (e) => ({ ...e, seen: true });
  assert.equal((await maybeCompactAtTurnEnd(d, session(30, 60000), state, { a: 1 }, next)).seen, true);
  assert.equal(calls.length, 0);
  await maybeCompactAtTurnEnd(d, session(61, 122000), state, {}, next);
  assert.equal(calls.length, 1);
  await maybeCompactAtTurnEnd(d, session(61, 122000), state, {}, next);
  assert.equal(calls.length, 1, 'same token count → the previous compaction did not take → skip');
  await maybeCompactAtTurnEnd(d, session(70, 140000), state, {}, next);
  assert.equal(calls.length, 2);
  const off = { env: env({ DAN_COMPACT_AT_PERCENT: '0' }), log: () => {} };
  await maybeCompactAtTurnEnd(off, session(99, 198000), { compacting: false }, {}, next);
  assert.equal(calls.length, 2);
  const failing = { usage: async () => { throw new Error('no usage in this host'); }, compact: async () => {} };
  assert.equal((await maybeCompactAtTurnEnd(d, failing, { compacting: false }, { a: 2 }, next)).seen, true);
});

test('readConfig: Windows home path, override, defaults and bounds', () => {
  const c = readConfig({ USERPROFILE: 'C:\\Users\\Owner' });
  assert.equal(c.ledgerPath, 'C:\\Users\\Owner\\.dan\\workspace\\memory\\.compact_jev_ledger.json');
  assert.equal(readConfig({ HOME: '/home/dan' }).ledgerPath, '/home/dan/.dan/workspace/memory/.compact_jev_ledger.json');
  assert.equal(readConfig({ DAN_COMPACT_LEDGER_PATH: 'X:/l.json', USERPROFILE: 'C:\\x' }).ledgerPath, 'X:/l.json');
  assert.equal(readConfig({}).ledgerPath, undefined);
  assert.equal(c.keepThreshold, DEFAULTS.keepThreshold);
  assert.equal(c.monthlyCapJpy, 100);
  assert.equal(readConfig({ DAN_COMPACT_KEEP_THRESHOLD: '7' }).keepThreshold, 1);
  assert.equal(readConfig({ DAN_COMPACT_KEEP_THRESHOLD: 'abc' }).keepThreshold, DEFAULTS.keepThreshold);
  assert.equal(readConfig({ DAN_COMPACT_MONTHLY_CAP_JPY: '-5' }).monthlyCapJpy, 0);
  assert.equal(readConfig({ TYPESAFE_API_KEY: '  ' }).apiKey, undefined);
});

test('the turn in progress is never offered to Jev (a mid-turn auto compaction keeps its tool results)', async () => {
  // Turn 1: prompt + 8 calls + answer. Turn 2 (in progress): prompt + 8 calls, no answer yet, no recent tail.
  const input = transcript(8, 1);
  input[input.length - 1] = { role: 'assistant', text: 'f1..f8 done.', toolUses: [], handle: 'answer1' };
  input.push({ role: 'user', text: 'Now read f9..f16.', toolUses: [], handle: 'prompt2' });
  for (let i = 0; i < 8; i++) {
    const id = `toolu_turn2_${i}`;
    const text = `result2 ${i} ` + 'y'.repeat(1500);
    input.push({ role: 'assistant', text: '', toolUses: [{ tool_use_id: id, tool: 'Read', input: { file_path: `f${9 + i}.txt` }, text }], handle: `h2a${i}` });
    input.push({ role: 'user', text: '', toolUses: [], toolResults: [{ tool_use_id: id, text, isError: false }], handle: `h2u${i}` });
  }
  assert.equal(currentTurnLength(input), 17);
  assert.equal(currentTurnLength([{ role: 'user', text: '<system-reminder>x</system-reminder>', toolUses: [] }]), 0);
  assert.equal(currentTurnLength([]), 0);
  const { d, fs } = deps();
  const result = await compactWithJev(d, { trigger: 'auto', messages: input }, async () => ({ messages: [] }));
  const turn2 = input.slice(-17);
  for (const m of turn2) assert.ok(result.messages.includes(m), 'every message of the turn in progress is kept, as the engine object');
  const ledger = JSON.parse(fs.files.get(LEDGER));
  assert.equal(ledger.last.outcome, 'compacted');
  assert.equal(ledger.last.preserveRecent, 17);
  assert.equal(ledger.last.pinned, 8, 'the 8 calls of the current turn are pinned');
  assert.equal(ledger.last.callsDropped, 8, 'only turn 1 calls were candidates');
  // DAN_COMPACT_PRESERVE_RECENT larger than the turn still wins.
  const wide = deps({ environment: env({ DAN_COMPACT_PRESERVE_RECENT: '30' }) });
  await compactWithJev(wide.d, { trigger: 'auto', messages: input }, async () => ({ messages: [] }));
  assert.equal(JSON.parse(wide.fs.files.get(LEDGER)).last.preserveRecent, 30);
});

test('sanitize and summaryLine never carry the key', () => {
  assert.equal(sanitize(`boom ${KEY} boom`, KEY), 'boom *** boom');
  assert.equal(sanitize('a'.repeat(300), undefined, 10).length, 13);
  const line = summaryLine({ outcome: 'fallback', reason: 'x', requests: 1, tokens: 10, yen: 0.0001, monthYen: 0.5, capJpy: 100 });
  assert.match(line, /組み込み要約に戻す \(x\)/);
  assert.match(line, /month_yen=0\.5\/100/);
});
