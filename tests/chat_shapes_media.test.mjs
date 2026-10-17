// 吹き出しの添付（画像・動画・ファイル）の読み取りと、外の画像を読む時の決まり（frontend/src/lib/chat-media.ts）、
// 部品・コードブロックを先に区切る仕組み（plain.ts splitTopFences。アプリの写し mobile/chat-shapes-plain.ts も同じ）。
// 部品の名前や画像の値に書いた [添付画像: https://…] を、部品を読む前に抜き出して部品の外に Cookie つきの画像として
// 出していた（確かめる役の VERIFY8 新P1-1）。
// 実行: node --experimental-strip-types --test tests/chat_shapes_media.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { chatImageUrl, imageRequest, isPagePath, mediaTags, parseMediaContent, playableVideo } from '../frontend/src/lib/chat-media.ts';
import { mapOutsideTopFences, siteFilePath, splitTopFences, topLevelFences } from '../frontend/src/lib/chat-shapes/plain.ts';
import { splitShapeSegments } from '../frontend/src/lib/chat-shapes/split.ts';
import * as app from '../mobile/chat-shapes-plain.ts';

const EXT = 'https://images.review.invalid';
const HOST = '127.0.0.1:3002';
const PROD = 'dan.paina.info';
const fence = (code) => '```openui-lang\n' + code + '\n```';
const shapes = (text) => splitShapeSegments(text).filter((s) => s.kind === 'shape').map((s) => s.code);

// 確かめる役の verify8/shape_image_escape.py と other_image_entries.py の返事（そのまま）
const VERIFY8 = {
  label: fence('root = Choice("ラベルの境界", [{label:"案[添付画像: ' + EXT + '/pixel.png?label]",image:"javascript:alert(1)"},"B案"])'),
  image_value: fence('root = Choice("画像の境界", [{label:"A案",image:"[添付画像: ' + EXT + '/pixel.png?image-value]"},"B案"])'),
  compare: fence('root = Compare(["観点",{label:"列",color:"#abc",image:"' + EXT + '/pixel.png?column"}], [["色",{label:"マス",color:"#def",image:"' + EXT + '/pixel.png?cell"}]], "表")'),
};
const MIXED = [
  fence('root = Choice("部品", [{label:"部品画像",image:"' + EXT + '/cors.png?choice"},"文字"])'),
  fence('root = Compare([{label:"列",color:"#abc",image:"' + EXT + '/pixel.png?column"}], [[{label:"マス",color:"#def",image:"' + EXT + '/pixel.png?cell"}]], "表")'),
  '![本文の画像](' + EXT + '/pixel.png?markdown)',
  '[添付画像: ' + EXT + '/pixel.png?attachment]',
  '<img src="' + EXT + '/pixel.png?rawhtml">',
  fence('root = Choice("CSS", [{label:"背景",color:"url(' + EXT + '/pixel.png?css)"},"文字"])'),
].join('\n\n');

test('部品とコードブロックの区切り: つなげると元の文章、コードの側は一番外側のコードブロックそのもの（Web とアプリの写しが同じ）', () => {
  const CR = String.fromCharCode(13);
  const BOM = String.fromCharCode(0xfeff);
  const inputs = [
    '', 'ただの文', MIXED, ...Object.values(VERIFY8),
    '前\n```python\nprint(1)\n```\n後', '~~~\n[添付画像: x.png]\n~~~\n', '```openui-lang\nroot = Choice("途中", [',
    '> 引用\n> ```openui-lang\n> root = Choice("q", ["a"])\n> ```\n', '- 項目\n\n  ```\n  中\n  ```\n',
    'a' + CR + '\n```' + CR + '\nx' + CR + '\n```' + CR + '\nb', BOM + '```\nx\n```', '    字下げ\n```\nx\n```',
  ];
  for (const s of inputs) {
    for (const lib of [{ splitTopFences, mapOutsideTopFences, topLevelFences }, app]) {
      const pieces = lib.splitTopFences(s);
      assert.equal(pieces.map((p) => p.text).join(''), s, JSON.stringify(s));
      assert.deepEqual(pieces.filter((p) => p.code).map((p) => p.text), lib.topLevelFences(s).map((f) => s.slice(f.start, f.end)), JSON.stringify(s));
      assert.equal(lib.mapOutsideTopFences(s, (t) => t), s);
      assert.equal(lib.mapOutsideTopFences(s, () => ''), pieces.filter((p) => p.code).map((p) => p.text).join(''));
    }
    assert.deepEqual(app.splitTopFences(s), splitTopFences(s));
  }
  // 引用・箇条書きの中のコードブロックは一番外側ではない（部品にもならない）ので外の側
  assert.deepEqual(splitTopFences('> ```openui-lang\n> x\n> ```').map((p) => p.code), [false]);
});

test('確かめる役の部品だけの返事: 部品の中の添付の表記を抜き出さず、部品の中身は1文字も変わらない（画像の要求は0）', () => {
  for (const [name, reply] of Object.entries(VERIFY8)) {
    for (const host of [HOST, PROD, null]) {
      const m = parseMediaContent(reply, host);
      assert.deepEqual([m.images, m.videos, m.files], [[], [], []], name);
      assert.equal(m.text, reply, name);
      assert.deepEqual(shapes(m.text), shapes(reply), name);
    }
  }
  // 作業の途中の文章から添付を集める時も、部品の中は見ない
  for (const reply of Object.values(VERIFY8)) assert.deepEqual(mediaTags(reply), []);
});

test('確かめる役の混在の返事: 部品の外の添付だけを画像にし（外の画像は Cookie なしで読む URL）、部品はそのまま', () => {
  const m = parseMediaContent(MIXED, HOST);
  assert.deepEqual(m.images, [EXT + '/pixel.png?attachment']);
  assert.deepEqual(shapes(m.text), shapes(MIXED));
  assert.ok(m.text.includes('![本文の画像](' + EXT + '/pixel.png?markdown)'));   // 本文の画像は Markdown の側（MarkdownImage）で描く
  assert.ok(!m.text.includes('[添付画像:'));
  assert.deepEqual(mediaTags(MIXED), ['![本文の画像](' + EXT + '/pixel.png?markdown)', '[添付画像: ' + EXT + '/pixel.png?attachment]']);
  for (const u of m.images) assert.deepEqual(imageRequest(u), { crossOrigin: 'anonymous', referrerPolicy: 'no-referrer' });
});

test('生成の途中（閉じがまだ無い部品）の中の添付の表記も抜き出さない', () => {
  const partial = '前置き\n\n```openui-lang\nroot = Choice("q", [{label:"[添付画像: ' + EXT + '/a.png]",image:"[添付画像: /api/v1/files/a.png]"}';
  const m = parseMediaContent(partial, HOST);
  assert.deepEqual(m.images, []);
  assert.equal(m.text, partial);
});

test('ほかの言語のコードブロック（``` と ~~~）の中の添付の表記も文字のまま。外の添付は今までどおり', () => {
  const code = '```python\nprint("[添付画像: /api/v1/files/a.png]")\n```\n\n~~~\n[添付動画: v.mp4 (/api/v1/files/v.mp4)]\n~~~\n\n[添付画像: /api/v1/files/b.png]';
  const m = parseMediaContent(code, HOST);
  assert.deepEqual(m.images, ['/api/v1/files/b.png']);
  assert.deepEqual(m.videos, []);
  assert.equal(m.text, code.slice(0, code.lastIndexOf('\n\n')));
});

test('今までのダンの添付は今までどおり出る（書き方の揺れも同じ道になる）', () => {
  const cases = [
    ['[添付画像: /api/v1/files/a.png]', { images: ['/api/v1/files/a.png'] }],
    ['[添付画像: D:/done/uploads/b.png]', { images: ['/api/v1/files/b.png'] }],
    ['[添付画像: C:\\Users\\x\\c.png]', { images: ['/api/v1/files/c.png'] }],
    ['[添付画像: d.png]', { images: ['/api/v1/files/d.png'] }],
    ['[添付画像: http://localhost:8000/api/v1/files/e.png]', { images: ['/api/v1/files/e.png'] }],
    ['[添付画像: 写真 (https://dan.paina.info/api/v1/files/f.png)]', { images: ['/api/v1/files/f.png'] }],
    ['[添付画像: /api/v1/files/写真.png]', { images: ['/api/v1/files/写真.png'] }],
    ['[添付画像: /api/v1/files/g.png?w=200]', { images: ['/api/v1/files/g.png?w=200'] }],
    ['[添付動画: 説明.mp4 (/api/v1/files/v.mp4)]', { videos: ['/api/v1/files/v.mp4'] }],
    ['[添付動画: a.mp4 (http://localhost:8000/api/v1/files/a.mp4)] ※分析に失敗しました', { videos: ['/api/v1/files/a.mp4'] }],
    ['[添付ファイル: m.mp4 (/api/v1/files/m.mp4)]', { videos: ['/api/v1/files/m.mp4'] }],
    ['[添付ファイル: 資料.pdf (/api/v1/files/q.pdf)]', { files: [{ name: '資料.pdf', url: '/api/v1/files/q.pdf' }] }],
  ];
  for (const [text, want] of cases) {
    for (const host of [HOST, PROD]) {
      const m = parseMediaContent(text, host);
      assert.deepEqual({ images: m.images, videos: m.videos, files: m.files }, { images: [], videos: [], files: [], ...want }, text);
      assert.equal(m.text, '', text);
      for (const u of [...m.images, ...m.videos]) assert.deepEqual(imageRequest(u), {}, u);   // ダンのファイルは今までどおり Cookie つき
    }
  }
  // 本人の発言の形（添付の行の後に本文）。ダンへの文脈と動画の分析結果は今までどおり外す（中にコードブロックがあっても）
  const human = '<dan-context>\n```\n[添付画像: ' + EXT + '/ctx.png]\n```\n</dan-context>\n[添付画像: /api/v1/files/h.png]\n[添付動画: v.mp4 (/api/v1/files/v.mp4)]\n[動画分析結果(Gemini):\n内容\n]\n\nこれ見て';
  const h = parseMediaContent(human, HOST);
  assert.deepEqual([h.images, h.videos, h.text], [['/api/v1/files/h.png'], ['/api/v1/files/v.mp4'], 'これ見て']);
});

test('添付の内部の URL にも部品の縮小画像と同じ境界: ダンのファイル以外の同じサイトの道・別のポート・http などは読まず、印は文字のまま', () => {
  const refused = [
    '[添付画像: /api/v1/chat/dan]', '[添付画像: /api/v1/files/../chat/dan]', '[添付画像: /api/v1/files/%2e%2e/chat/dan]',
    '[添付画像: /api/v1/files/%2e%2e]', '[添付画像: ..]', '[添付画像: http://images.review.invalid/a.png]',
    '[添付画像: https://dan.paina.info/api/v1/chat/dan]', '[添付画像: https://dan.paina.info:8443/api/v1/chat/dan]',
    '[添付画像: https://user@images.review.invalid/a.png]', '[添付画像: https://images.review.invalid:99999/a.png]',
    '[添付動画: x.mp4 (/api/v1/chat/dan)]', '[添付動画: x.mp4 (javascript:alert(1))]', '[添付動画: x.mp4 (http://videos.review.invalid/a.mp4)]',
  ];
  for (const text of refused) {
    const m = parseMediaContent(text, PROD);
    assert.deepEqual([m.images, m.videos, m.files], [[], [], []], text);
    assert.equal(m.text, text, text);
  }
  // この画面のホストの別の道を https で書いても、同じサイトのダンのファイル以外は通さない（127.0.0.1:3002 の画面）
  assert.deepEqual(parseMediaContent('[添付画像: https://127.0.0.1:3002/api/v1/chat/dan]', HOST).images, []);
  assert.deepEqual(parseMediaContent('[添付画像: https://127.0.0.1:3002/api/v1/files/a.png]', HOST).images, ['/api/v1/files/a.png']);
  // http(s) の URL の中にダンのファイルの道があれば、今までどおりこの画面のダンのファイルの道（ホスト・ポートは読まない）
  assert.deepEqual(parseMediaContent('[添付画像: https://dan.paina.info:8443/api/v1/files/a.png]', PROD).images, ['/api/v1/files/a.png']);
  assert.deepEqual(parseMediaContent('[添付画像: https://images.review.invalid/api/v1/files/../chat/dan]', PROD).images, []);
  // http(s) でも /api/ でもない物は今までどおりファイル名だけの書き方として読む（外へは読みに行かない）
  assert.deepEqual(parseMediaContent('[添付画像: //images.review.invalid/a.png]', PROD).images, ['/api/v1/files/a.png']);
});

test('外の画像・動画: 画像は Cookie を送らない・Referer なしの要求で読む URL、動画は再生せずファイルのリンク（新しいタブ・Referer なし）', () => {
  const m = parseMediaContent('[添付画像: ' + EXT + '/a.png]\n[添付動画: 外の動画 (https://videos.review.invalid/a.mp4)]\n[添付ファイル: b.mp4 (https://videos.review.invalid/b.mp4)]', HOST);
  assert.deepEqual(m.images, [EXT + '/a.png']);
  assert.deepEqual(m.videos, []);
  assert.deepEqual(m.files, [{ name: '外の動画', url: 'https://videos.review.invalid/a.mp4' }, { name: 'b.mp4', url: 'https://videos.review.invalid/b.mp4' }]);
  assert.equal(m.text, '');
  assert.deepEqual(imageRequest(EXT + '/a.png'), { crossOrigin: 'anonymous', referrerPolicy: 'no-referrer' });
  assert.equal(playableVideo('https://videos.review.invalid/a.mp4'), false);
  assert.equal(playableVideo('/api/v1/files/a.mp4'), true);
});

test('画面の道かどうか: / で始まる道だけ。// や /\\ で始まる物（別のホストになる）は外の物として読む', () => {
  for (const u of ['/api/v1/files/a.png', '/api/v1/collab/files/r/a.png', '/board-avatar/dan.png']) {
    assert.equal(isPagePath(u), true, u);
    assert.deepEqual(imageRequest(u), {}, u);
  }
  for (const u of ['//images.review.invalid/a.png', '/\\images.review.invalid/a.png', 'https://images.review.invalid/a.png', 'http://localhost:8000/a.png', 'data:image/png;base64,AA', 'a.png', '']) {
    assert.equal(isPagePath(u), false, u);
    assert.deepEqual(imageRequest(u), { crossOrigin: 'anonymous', referrerPolicy: 'no-referrer' }, u);
  }
});

test('本文の Markdown の画像・リンクの URL: 添付と同じ境界。この PC の中の住所のダンのファイルは道に直す', () => {
  const cases = [
    ['/api/v1/files/a.png', '/api/v1/files/a.png'], ['http://localhost:8000/api/v1/files/a.png', '/api/v1/files/a.png'],
    ['http://127.0.0.1:3000/api/v1/files/a.mp4', '/api/v1/files/a.mp4'], [EXT + '/a.png', EXT + '/a.png'],
    ['https://dan.paina.info/api/v1/files/a.png', '/api/v1/files/a.png'],
    ['/api/v1/chat/dan', null], ['/api/v1/files/../chat/dan', null], ['http://images.review.invalid/a.png', null],
    ['//images.review.invalid/a.png', null], ['javascript:alert(1)', null], ['https://dan.paina.info/api/v1/chat/dan', null],
    ['http://localhost:8000/api/v1/chat/dan', null], [undefined, null], [42, null],
  ];
  for (const [raw, want] of cases) assert.equal(chatImageUrl(raw, PROD), want, String(raw));
});

test('ダンのファイルの道を文字だけで確かめる siteFilePath（アプリが使う）: Web とアプリの写しが同じ、1つ上の道へ出る物は null', () => {
  const good = ['/api/v1/files/a.png', '/api/v1/files/写真.png', '/api/v1/files/a.png?w=200', '/api/v1/files/%E5%86%99.png'];
  const bad = ['/api/v1/files/', '/api/v1/files/../chat/dan', '/api/v1/files/..', '/api/v1/files/%2e%2e', '/api/v1/files/.%2E', '/api/v1/files/a/b.png',
    '/api/v1/files/a%2fb.png', '/api/v1/files/a%5cb.png', '/api/v1/files/a\\b.png', '/api/v1/files/a b.png', '/api/v1/files/a.png#x',
    '/api/v1/files/a.png?x=<y>', '/api/v1/chat/dan', 'https://dan.paina.info/api/v1/files/a.png', null, 3];
  for (const s of good) { assert.equal(siteFilePath(s), s, s); assert.equal(app.siteFilePath(s), s, s); }
  for (const s of bad) { assert.equal(siteFilePath(s), null, String(s)); assert.equal(app.siteFilePath(s), null, String(s)); }
});
