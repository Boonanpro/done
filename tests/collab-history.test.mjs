import test from 'node:test';
import assert from 'node:assert/strict';
import { mergeLatest, mergeOlder } from '../frontend/src/lib/collab-scroll.ts';
import { isOwnGuestMessage } from '../frontend/src/lib/collab-identity.ts';

const message = i => ({ id: String(i), created_at: new Date(1_700_000_000_000 + i * 1000).toISOString() });
test('reconnecting after more than a page of messages does not strand an invisible gap', () => {
  const old = Array.from({ length: 10 }, (_, i) => message(i));
  const latest = Array.from({ length: 50 }, (_, i) => message(i + 100));
  const result = mergeLatest(old, latest);
  assert.equal(result[0].id, '100');
  const older = Array.from({ length: 50 }, (_, i) => message(i + 50));
  assert.equal(mergeOlder(result, older)[0].id, '50');
});
test('overlapping refresh preserves the older history already being read', () => {
  const old = Array.from({ length: 100 }, (_, i) => message(i));
  const latest = Array.from({ length: 50 }, (_, i) => message(i + 70));
  assert.equal(mergeLatest(old, latest).length, 120);
});
test('same names do not turn another participant into me, and renaming keeps old messages mine', () => {
  const m = { sender_type: 'guest', sender_name: '同じ名前', metadata: { sender_id: 'a' } };
  assert.equal(isOwnGuestMessage(m, 'b', '同じ名前'), false);
  assert.equal(isOwnGuestMessage(m, 'a', '新しい名前'), true);
});
