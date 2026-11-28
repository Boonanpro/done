// 字幕は1文字ずつ出さない（2026-11-28 本人）。node --experimental-strip-types で動かす。
import { revealTokens } from './caption-reveal.ts';
import assert from 'node:assert/strict';

// 区切りが無いタイプの字幕は、まとめて全部出す（前は1字ずつ均等に出ていた）
assert.equal(revealTokens({ text: 'そう言ってくれて嬉しいですね', start: 10, end: 12 }, 'typewriter').length, 1);
// 区切りが本文と合わない（語合わせの書き換え・打ち直し）時もまとめて全部
assert.equal(revealTokens({ text: 'そう言ってくれて嬉しいですね', start: 10, end: 12, words: [{ text: 'そう', start: 10 }, { text: 'いう', start: 11 }] }, 'typewriter').length, 1);
// 書いた前半→後半の区切りはそのまま2段で出す・最後の end が null でも字幕の終わりまで
const two = revealTokens({ text: 'そう言ってくれて\n嬉しいですね', start: 10, end: 12, words: [{ text: 'そう言ってくれて\n', start: 10, end: 10.8 }, { text: '嬉しいですね', start: 10.8, end: null }] }, 'typewriter');
assert.deepEqual(two.map((t) => [t.text, t.start, t.end]), [['そう言ってくれて\n', 10, 10.8], ['嬉しいですね', 10.8, 12]]);
// カラオケは語ごとに光らせるので、時刻が無ければ1字ずつ割る（今までどおり）
assert.equal(revealTokens({ text: 'あいう', start: 0, end: 3 }, 'karaoke').length, 3);
console.log('caption-reveal ok');
