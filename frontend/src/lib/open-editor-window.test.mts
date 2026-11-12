// node --experimental-strip-types frontend/src/lib/open-editor-window.test.mts
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { editorWorkLink } from './open-editor-window.ts';

const R = 'a588ca6f-95b1-484a-a13d-cf7771ebffb8';
const C = 'd43d7307-f2a9-45a3-81f8-00c88064279b';

test('作品へのリンクは部屋と作品を返す（道・公開の入口・この PC の住所）', () => {
  for (const base of ['', 'https://dan.paina.info', 'http://localhost:3000']) {
    assert.deepEqual(editorWorkLink(`${base}/production-workspace?room_id=${R}&content_id=${C}`), { roomId: R, contentId: C });
  }
  assert.deepEqual(editorWorkLink(`/production-workspace?room_id=${R}`), { roomId: R, contentId: null });
});

test('ほかのリンク・よその住所・形の崩れた id は作品のリンクにしない', () => {
  assert.equal(editorWorkLink('/api/v1/files/x.jpg'), null);
  assert.equal(editorWorkLink(`https://evil.example/production-workspace?room_id=${R}`), null);
  assert.equal(editorWorkLink('/production-workspace?room_id=../../x'), null);
  assert.equal(editorWorkLink(undefined), null);
  assert.deepEqual(editorWorkLink(`/production-workspace?room_id=${R}&content_id=<script>`), { roomId: R, contentId: null });
});
