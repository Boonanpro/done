// node --experimental-strip-types frontend/src/lib/voice-fragments.test.mts
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { collapseCalls } from './voice-fragments.ts';

test('通話から頼んだ作業の写し（【作業の依頼】）はチャットに出さない。ほかの案内は残す', () => {
  const rows = [
    { id: '1', sender_type: 'human', content: 'こんにちは', created_at: '2026-11-27T14:00:00Z' },
    { id: '2', sender_type: 'system', content: '【作業の依頼】\nあれが直されてないやん\n通話のここまでの文字起こし…', created_at: '2026-11-27T14:49:00Z' },
    { id: '3', sender_type: 'system', content: '見張りの時刻です', created_at: '2026-11-27T14:50:00Z' },
    { id: '4', sender_type: 'ai', content: '【作業の依頼】という言葉の話です', created_at: '2026-11-27T14:51:00Z' },
  ];
  assert.deepEqual(collapseCalls(rows).map((m) => m.id), ['1', '3', '4']);
});
