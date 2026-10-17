// 選択肢・表のセルの「実物」（色見本・縮小画像）の値の検査と、文字だけの選択肢の後方互換、部品を描けない画面の文章化。
// 検査は frontend/src/lib/chat-shapes/plain.ts（safeColor・safeImageUrl・readLook）の1か所で、画面（chat-shapes.tsx）・
// 選択肢の整え方と完成時の検証（schema.ts）・アプリの写し（mobile/chat-shapes-plain.ts）が同じ関数を使う。
// 実行: node --experimental-strip-types --test tests/chat_shapes_looks.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createLibrary, defineComponent, createParser } from '../frontend/node_modules/@openuidev/lang-core/dist/index.mjs';
import {
  ChoiceProps, CompareProps, SHAPE_SPECS, choiceOptions, normalizeOptions, validateComplete,
} from '../frontend/src/lib/chat-shapes/schema.ts';
import { parseShapeCall, readLook, replaceShapeBlocks, safeColor, safeImageUrl } from '../frontend/src/lib/chat-shapes/plain.ts';
import * as app from '../mobile/chat-shapes-plain.ts';

const BS = '\\';                       // 1文字のバックスラッシュ
const NUL = String.fromCharCode(0);
const LF = String.fromCharCode(10);
const TAB = String.fromCharCode(9);
const DEL = String.fromCharCode(0x7f);
const NBSP = String.fromCharCode(0xa0);
const IDEO_SPACE = String.fromCharCode(0x3000);
const LINE_SEP = String.fromCharCode(0x2028);

test('色の値: #rgb・#rrggbb・rgb(r, g, b) だけを受け付け、読んだ数字から作り直した値を返す', () => {
  const good = [
    ['#abc', '#abc'], ['#ABC', '#abc'], ['#d8c7a8', '#d8c7a8'], ['#D8C7A8', '#d8c7a8'], [' #000000 ', '#000000'], ['#fff', '#fff'],
    ['rgb(216, 199, 168)', 'rgb(216, 199, 168)'], ['rgb(0,0,0)', 'rgb(0, 0, 0)'], ['RGB( 255 , 255 , 255 )', 'rgb(255, 255, 255)'],
    ['rgb(10 20 30)', 'rgb(10, 20, 30)'], ['rgb(007, 8, 9)', 'rgb(7, 8, 9)'],
  ];
  for (const [v, want] of good) assert.equal(safeColor(v), want, v);
});

test('色の値: それ以外（色の名前・透明度つき・範囲外・小数・hsl・var・数値や物）は null', () => {
  const bad = [
    'red', 'beige', 'transparent', 'currentColor', '#abcd', '#abcdef12', '#ab', '#abcde', '#ggg', 'abc', '#', '',
    'rgb(256, 0, 0)', 'rgb(-1, 0, 0)', 'rgb(1.5, 2, 3)', 'rgb(1, 2)', 'rgb(1, 2, 3, 4)', 'rgba(0, 0, 0, 0.5)', 'rgb(1,2,3', 'rgb (1,2,3)',
    'rgb(10%, 20%, 30%)', 'hsl(0, 0%, 0%)', 'var(--primary)', 'inherit', 'initial',
    null, undefined, 123, 0x123456, {}, [], ['#fff'], { color: '#fff' }, true,
    '#' + 'f'.repeat(41),
  ];
  for (const v of bad) assert.equal(safeColor(v), null, JSON.stringify(v));
});

test('色の値: CSS への差し込みの試みは全部 null（宣言の区切り・url()・expression・重要度・改行・コメント・エスケープ）', () => {
  const attacks = [
    'red; background: url(https://evil.test/x)', '#fff; background-image: url(https://evil.test/x)', '#fff;', '#fff ;',
    'rgb(1,2,3); color: red', 'rgb(1,2,3) url(https://evil.test/x)', '#fff url(x)', 'url(https://evil.test/x)',
    'expression(alert(1))', '#fff !important', '#fff/*x*/', '/*x*/#fff', `#fff${LF}color:red`, `#fff${NUL}`,
    `#f${BS}66`, `${BS}23fff`, '#fff}body{background:red', '#fff" onmouseover="x', "#fff' x='", '<style>', 'rgb(1,2,3)}',
    `rgb(1,2,3)${LF};x:y`, 'rgb(1,2,3)/**/', 'image-set(url(x) 1x)', 'attr(data-x)', 'env(x)',
  ];
  for (const v of attacks) assert.equal(safeColor(v), null, JSON.stringify(v));
});

test('画像の URL: ダンのファイル（/api/v1/files/<名前>）と https:// だけ', () => {
  const good = [
    '/api/v1/files/a.png', '/api/v1/files/3f6d2a10-8c1e-4b7a-9d55-0a1b2c3d4e01.png', '/api/v1/files/%E3%83%AD%E3%82%B4.png',
    '/api/v1/files/a.png?v=2', '/api/v1/files/ロゴ案.png', ' /api/v1/files/a.png ',
    'https://example.com/a.png', 'https://cdn.example.com:8443/x/y.jpg?w=1#f', 'HTTPS://Example.com/A.PNG', 'https://example.com',
    'https://127.0.0.1/a.png', 'https://a-b.example.co.jp/img/a b%20c.png'.replace(' ', '_'),
  ];
  for (const v of good) assert.equal(safeImageUrl(v), v.trim(), v);
});

test('画像の URL: javascript:・data:・http:// ほか、それ以外は全部 null', () => {
  const bad = [
    'javascript:alert(1)', 'JaVaScRiPt:alert(1)', ' javascript:alert(1)', `java${TAB}script:alert(1)`, `javascript${LF}:alert(1)`,
    'vbscript:x', 'data:image/png;base64,AAAA', 'DATA:image/svg+xml,<svg onload=alert(1)>', 'blob:https://example.com/1',
    'http://example.com/a.png', 'HTTP://example.com/a.png', 'ftp://example.com/a.png', 'file:///C:/a.png', 'about:blank',
    '//evil.test/a.png', '///evil.test/a.png', `/${BS}evil.test/a.png`, `${BS}${BS}evil.test${BS}a.png`,
    'D:/done/uploads/a.png', `D:${BS}done${BS}uploads${BS}a.png`, 'C:/a.png', 'uploads/a.png', 'a.png', './a.png', '../a.png',
    'https://user:pass@example.com/a.png', 'https://user@example.com/a.png', 'https://example.com@evil.test/a.png',
    'https://', 'https:///a.png', 'https://-bad.example/a.png', 'https://bad-.example/a.png', 'https://exa mple.com/a.png',
    'https://example.com/a b.png', `https://example.com/a.png${LF}`.trim() + LF + 'x', `https://example.com/${NUL}`, `https://example.com/${DEL}`,
    `https://example.com/${NBSP}a`, `https://example.com/${IDEO_SPACE}a`, `https://example.com/${LINE_SEP}a`, 'https://example.com.',
    'https:example.com/a.png', 'https:/example.com/a.png', 'https://example.com?x=1', `https://example.com/${BS}a`,
    '', '   ', null, undefined, 1, {}, [], ['/api/v1/files/a.png'], { url: '/api/v1/files/a.png' },
    'https://example.com/' + 'a'.repeat(2048),
  ];
  for (const v of bad) assert.equal(safeImageUrl(v), null, JSON.stringify(v));
});

test('画像の URL: 同じサイトの道はダンのファイルの配信だけ（Cookie つきの GET になるため）。抜け道（.. ・符号化した / ・別の口）は null', () => {
  const bad = [
    '/api/v1/files/', '/api/v1/files', '/api/v1/files/../chat/logout', '/api/v1/files/..', '/api/v1/files/.', '/api/v1/files/%2e%2e',
    '/api/v1/files/%2E%2E', '/api/v1/files/%2e', '/api/v1/files/a%2Fb', '/api/v1/files/a%2fb', '/api/v1/files/a%5Cb', '/api/v1/files/a%3Fb',
    '/api/v1/files/a%23b', '/api/v1/files/a%00b', '/api/v1/files/a%0Ab', '/api/v1/files/a/b.png', '/api/v1/files/a.png/', '/api/v1/files//a.png',
    '/api/v1/files/%ZZ', '/api/v1/files/a.png?x=<script>', '/api/v1/files/a.png?x=1#f', '/api/v1/files/a.png#f', '/api/v1/files/a.png?a/b',
    '/api/v1/chat/rooms', '/api/v1/chat/dan/cancel', '/api/v1/file/a.png', '/api/v1/filesx/a.png', '/API/V1/FILES/a.png', '/a.png', '/', '/artifacts/x/a.png',
  ];
  for (const v of bad) assert.equal(safeImageUrl(v), null, JSON.stringify(v));
});

test('画像の URL: この画面のホストを指す https:// は同じサイトの道の決まりで見る（ダンのファイルなら道だけを返す）', () => {
  const host = 'dan.paina.info';
  assert.equal(safeImageUrl('https://dan.paina.info/api/v1/files/a.png', host), '/api/v1/files/a.png');
  assert.equal(safeImageUrl('https://DAN.paina.info:443/api/v1/files/a.png?v=1', host), '/api/v1/files/a.png?v=1');
  for (const v of ['https://dan.paina.info/api/v1/chat/dan/cancel', 'https://dan.paina.info/', 'https://dan.paina.info',
    'https://dan.paina.info/api/v1/files/../chat/x', 'https://dan.paina.info:443/api/v1/chat/rooms']) {
    assert.equal(safeImageUrl(v, host), null, v);
  }
  // ほかのホスト・ほかのポートはふつうの https として通る。ホストを渡さなければ（アプリの文章化など）そのまま
  assert.equal(safeImageUrl('https://cdn.paina.info/a.png', host), 'https://cdn.paina.info/a.png');
  assert.equal(safeImageUrl('https://dan.paina.info/api/v1/chat/x'), 'https://dan.paina.info/api/v1/chat/x');
  assert.equal(safeImageUrl('https://localhost:3000/api/v1/chat/x', 'localhost:3000'), null);
});

// 確かめる役（VERIFY7）の 71 個の URL の例（scratch の verify7/security.mjs と同じ並び。この画面のホストは dan-test.invalid）
const SITE = 'dan-test.invalid';
const VERIFY7_URLS = [
  '/api/v1/files/a.png', '/api/v1/files/a.png?v=1', 'javascript:alert(1)', 'data:image/svg+xml,x', 'http://x.invalid/a', '//x.invalid/a',
  `${BS}${BS}x.invalid/a`, `https:${BS}x.invalid/a`, '/api/v1/chat/dan', '/api/v1/files/..', '/api/v1/files/.', '/api/v1/files/%2e%2e',
  '/api/v1/files/a%2fb', '/api/v1/files/a%3fb', '/api/v1/files/a%23b', '/api/v1/files/a%5cb', '/api/v1/files/a%00b', '/api/v1/files/a%252fb',
  '/api/v1/files/%252e%252e', '/api/v1/files/a?x=%2f%3f%23', '/api/v1/files/日本語.png', '/api/v1/files/a.png#x',
  'https://user:pass@x.invalid/a', 'https://x.invalid@dan-test.invalid/a', 'https://例え.テスト/a', 'https://xn--r8jz45g.xn--zckzah/a',
  'https://127.1/a', 'https://2130706433/a', 'https://0x7f000001/a', 'https://0177.0.0.1/a', 'https://[::1]/a', 'https://x.invalid:99999/a',
  'https://x.invalid/a/../b', 'https://x.invalid/a%2fb?x=%23', `https://x.invalid/a${LF}b`, `https://x.invalid/a${BS}b`, 'https://x.invalid/a%5cb',
  'https://x.invalid/a?q=<svg>', 'https://x.invalid/?token=sample-not-a-secret',
];
for (const h of [SITE, SITE.toUpperCase(), SITE + ':443', SITE + ':0443', SITE + ':00443', SITE + ':8443', SITE + '.', SITE + ':0']) {
  for (const path of ['/api/v1/files/a.png', '/api/v1/chat/dan', '/api/v1/files/../chat/dan', '/api/v1/files/%2e%2e/chat/dan']) VERIFY7_URLS.push('https://' + h + path);
}
// 71 個のうち通る物と、その時に返す値（ほかは全部 null）
const VERIFY7_PASS = new Map([
  ['/api/v1/files/a.png', '/api/v1/files/a.png'], ['/api/v1/files/a.png?v=1', '/api/v1/files/a.png?v=1'],
  ['/api/v1/files/a%252fb', '/api/v1/files/a%252fb'], ['/api/v1/files/%252e%252e', '/api/v1/files/%252e%252e'],
  ['/api/v1/files/a?x=%2f%3f%23', '/api/v1/files/a?x=%2f%3f%23'], ['/api/v1/files/日本語.png', '/api/v1/files/日本語.png'],
  ...['https://xn--r8jz45g.xn--zckzah/a', 'https://127.1/a', 'https://2130706433/a', 'https://0x7f000001/a', 'https://0177.0.0.1/a',
    'https://x.invalid/a/../b', 'https://x.invalid/a%2fb?x=%23', 'https://x.invalid/a%5cb', 'https://x.invalid/a?q=<svg>',
    'https://x.invalid/?token=sample-not-a-secret'].map((u) => [u, u]),
  ...[SITE, SITE.toUpperCase(), SITE + ':443', SITE + ':0443', SITE + ':00443'].map((h) => ['https://' + h + '/api/v1/files/a.png', '/api/v1/files/a.png']),
]);

/** 通った値をブラウザが実際に要求する先（この画面 https://<site>/ から読んだ時）が、この画面のホストならダンのファイル1つ */
function requestedIsSafe(result, site) {
  const page = new URL(`https://${site}/`);
  const u = new URL(result, page);
  if (u.hostname !== page.hostname) return result.startsWith('https://');
  const name = u.pathname.slice('/api/v1/files/'.length);
  return u.origin === page.origin && u.pathname.startsWith('/api/v1/files/') && !!name && !name.includes('/')
    && !['.', '..'].includes(decodeURIComponent(name)) && !u.hash;
}

test('画像の URL: 確かめる役の 71 個の例。同じサイトの判定はブラウザと同じ読み方（ホスト・ポート・道を直してから）で、Web とアプリの写しが同じ', () => {
  assert.equal(VERIFY7_URLS.length, 71);
  for (const v of VERIFY7_URLS) {
    const got = safeImageUrl(v, SITE);
    assert.equal(got, VERIFY7_PASS.get(v) ?? null, JSON.stringify(v));
    assert.equal(app.safeImageUrl(v, SITE), got, JSON.stringify(v));
    assert.equal(app.safeImageUrl(v), safeImageUrl(v), JSON.stringify(v));
    if (got) assert.ok(requestedIsSafe(got, SITE), JSON.stringify(v));
  }
  // VERIFY7 の sameOriginEscape 6 件（前はファイル以外の同じサイトの口へ Cookie つき GET を通した）
  for (const port of [':0443', ':00443']) {
    for (const path of ['/api/v1/chat/dan', '/api/v1/files/../chat/dan', '/api/v1/files/%2e%2e/chat/dan']) {
      assert.equal(safeImageUrl(`https://${SITE}${port}${path}`, SITE), null, port + path);
      assert.equal(app.safeImageUrl(`https://${SITE}${port}${path}`, SITE), null, port + path);
    }
  }
});

test('画像の URL: 同じホストは、ゼロ埋めのポート・数字だけのホストも直してから見る。別のポートは通さない（Cookie はポートで分かれない）', () => {
  const host = '127.0.0.1:3002';   // 試験の画面（next dev）
  const same = ['https://127.0.0.1:3002', 'https://127.0.0.1:03002', 'https://2130706433:3002', 'https://127.1:3002', 'https://0x7f.0.0.1:3002',
    'https://0177.0.0.1:03002', 'https://0x7f000001:3002'];
  for (const origin of same) {
    for (const path of ['/api/v1/chat/dan', '/api/v1/chat/dan?probe=1', '/api/v1/files/../chat/dan', '/api/v1/files/%2e%2e/chat/dan',
      '/api/v1/files/.%2e/chat/dan', '/api/v1/files/%2E./chat/dan', '/api/v1/files/a.png/..', '/api/v1/files/', '/']) {
      assert.equal(safeImageUrl(origin + path, host), null, origin + path);
    }
    assert.equal(safeImageUrl(origin + '/api/v1/files/a.png', host), '/api/v1/files/a.png', origin);
  }
  for (const v of ['https://127.0.0.1:3003/api/v1/files/a.png', 'https://127.0.0.1/api/v1/files/a.png', 'https://127.0.0.1:443/api/v1/files/a.png',
    'https://127.0.0.1:0/api/v1/files/a.png', 'https://2130706433/api/v1/chat/dan', 'https://127.0.0.1:8001/api/v1/chat/dan']) {
    assert.equal(safeImageUrl(v, host), null, v);
  }
  // 本番の形（443 の画面）: :0443・:00443 は 443、:8443 は別のポート
  assert.equal(safeImageUrl('https://dan.paina.info:0443/api/v1/files/a.png', 'dan.paina.info'), '/api/v1/files/a.png');
  assert.equal(safeImageUrl('https://dan.paina.info:00443/api/v1/chat/dan', 'dan.paina.info'), null);
  assert.equal(safeImageUrl('https://dan.paina.info:8443/api/v1/files/a.png', 'dan.paina.info'), null);
  assert.equal(safeImageUrl('https://dan.paina.info:8443/a.png', 'dan.paina.info'), null);
  // ブラウザが URL として読めない物（範囲外のポート・5つ組の数字のホスト）は通さない
  for (const v of ['https://x.invalid:99999/a', 'https://x.invalid:65536/a', 'https://1.2.3.4.5/a', 'https://256.0.0.1/a']) assert.equal(safeImageUrl(v), null, v);
  // 書いた道で通らない物（. を含む道）は、直すとダンのファイルになっても通さない
  assert.equal(safeImageUrl('/api/v1/files/./a.png'), null);
  assert.equal(safeImageUrl('https://dan.paina.info/api/v1/files/x/../a.png', 'dan.paina.info'), null);
  // ほかのホストは今までどおり https の画像として通る（読むのは画面の側で Cookie を送らない要求）
  assert.equal(safeImageUrl('https://images.dan-test.invalid/a.png', SITE), 'https://images.dan-test.invalid/a.png');
});

test('画像の URL: ブラウザと同じ読み方ができない URL（React Native の URL は文字列を切り出すだけ）の所では画像を通さない。アプリの文章は変わらない', () => {
  const choice = 'root = Choice("ロゴ", [{label: "A案", image: "/api/v1/files/a.png"}, {label: "ベージュ", color: "#d8c7a8", image: "https://example.com/b.png"}, "C案"])';
  const code = [
    // React Native 0.81 の URL と同じく、直さずに文字列を持つだけの URL
    "globalThis.URL = class { constructor(u, b) { this._u = b ? String(b).replace(/[/]$/, '') + u : u; } get href() { return this._u; } };",
    `const app = await import(${JSON.stringify(new URL('../mobile/chat-shapes-plain.ts', import.meta.url).href)});`,
    `console.log(JSON.stringify([app.safeImageUrl('/api/v1/files/a.png'), app.safeImageUrl('https://example.com/a.png'), app.readLook({label: 'A', color: '#ABC', image: '/api/v1/files/a.png'}), app.shapeToPlainMarkdown(${JSON.stringify(choice)})]));`,
  ].join('\n');
  const out = JSON.parse(execFileSync(process.execPath, ['--experimental-strip-types', '--no-warnings', '--input-type=module', '-e', code], { encoding: 'utf8' }));
  assert.deepEqual(out.slice(0, 3), [null, null, { label: 'A', color: '#abc', image: null }]);
  assert.equal(out[3], app.shapeToPlainMarkdown(choice));
  assert.match(out[3], /^\*\*ロゴ\*\*\n1\. A案\n2\. ベージュ（#d8c7a8）\n3\. C案\n/);
});

test('選択肢・セル1つの読み方: 文字はそのまま名前、物は名前と検査を通った実物だけ、名前が文字でない物は無い扱い', () => {
  assert.deepEqual(readLook('ベージュ'), { label: 'ベージュ', color: null, image: null });
  assert.deepEqual(readLook({ label: 'ベージュ', color: '#D8C7A8' }), { label: 'ベージュ', color: '#d8c7a8', image: null });
  assert.deepEqual(readLook({ label: 'A案', image: '/api/v1/files/a.png', color: 'red' }), { label: 'A案', color: null, image: '/api/v1/files/a.png' });
  assert.deepEqual(readLook({ label: 'A案', image: 'javascript:alert(1)', color: '#fff;x:y' }), { label: 'A案', color: null, image: null });
  assert.deepEqual(readLook({ label: 'x', colour: '#fff', src: '/api/v1/files/a.png' }), { label: 'x', color: null, image: null });   // ほかの鍵は見ない
  for (const v of [null, undefined, 1, true, [], ['a'], {}, { color: '#fff' }, { label: 1 }, { label: null, color: '#fff' }]) {
    assert.equal(readLook(v), null, JSON.stringify(v));
  }
});

test('後方互換: 文字だけの選択肢は今までと同じに整え、検証も今までと同じ', () => {
  assert.deepEqual(normalizeOptions(['A', ' A ', '', 'B', 'B']), ['A', 'B']);
  assert.deepEqual(choiceOptions(['ベージュ', 'グレー']), [
    { label: 'ベージュ', color: null, image: null }, { label: 'グレー', color: null, image: null },
  ]);
  assert.equal(ChoiceProps.safeParse({ question: 'Q', options: ['A', 'B'] }).success, true);
  assert.equal(ChoiceProps.safeParse({ question: 'Q', options: ['A', 'A', ''] }).success, false);
  assert.deepEqual(validateComplete('Choice', { question: '進め方', options: ['先に見積もりを取る', '今すぐ発注する'] }), { ok: true });
  assert.equal(CompareProps.safeParse({ columns: ['観点', 'A', 'B'], rows: [['費用', '1', '2']] }).success, true);
  // 選択肢の引数は今までどおり2つ（位置で渡す順番は変わらない）
  assert.deepEqual(Object.keys(ChoiceProps.shape), ['question', 'options']);
  assert.deepEqual(Object.keys(CompareProps.shape), ['columns', 'rows', 'caption']);
});

test('実物つきの選択肢: 文字と混ぜてよい。重複は名前で落とす。悪い色や画像は捨てて名前は残す（部品はコードに戻さない）', () => {
  const options = [{ label: 'ベージュ', color: '#d8c7a8' }, ' グレー ', { label: 'ブラウン', color: 'brown' }, { label: 'ベージュ', color: '#000' }];
  assert.deepEqual(choiceOptions(options), [
    { label: 'ベージュ', color: '#d8c7a8', image: null }, { label: 'グレー', color: null, image: null }, { label: 'ブラウン', color: null, image: null },
  ]);
  assert.deepEqual(normalizeOptions(options), ['ベージュ', 'グレー', 'ブラウン']);
  assert.deepEqual(validateComplete('Choice', { question: '生地の色', options }), { ok: true });
  assert.deepEqual(validateComplete('Choice', { question: 'ロゴ', options: [{ label: 'A案', image: 'data:x' }, { label: 'B案', image: '/api/v1/files/b.png' }] }), { ok: true });
  // 名前の無い物・名前が長すぎる物は、今までの文字の選択肢と同じく完成した部品として通らない（コードに戻す）
  assert.equal(validateComplete('Choice', { question: 'Q', options: [{ color: '#fff' }, 'A', 'B'] }).ok, false);
  assert.equal(validateComplete('Choice', { question: 'Q', options: [{ label: 'x'.repeat(201) }, 'A'] }).ok, false);
  assert.equal(validateComplete('Choice', { question: 'Q', options: [{ label: 'A' }, { label: 'A', color: '#fff' }] }).ok, false);   // 名前で重複→1個
  // 生成の途中の物（lang-core が途中の鍵を null で埋める）は名前だけを読む
  assert.deepEqual(choiceOptions([{ label: 'ベージュ', col: null, '?': null }]), [{ label: 'ベージュ', color: null, image: null }]);
});

test('表: 見出し・セルは文字か {label, color}。名前が空の見出しは今までどおり通らない', () => {
  const ok = { columns: ['観点', { label: 'ベージュ', color: '#d8c7a8' }, 'グレー'], rows: [['色', { label: 'ベージュ', color: '#d8c7a8' }, { label: 'グレー', color: 'rgb(150, 150, 150)' }], ['汚れ', '目立つ', '目立ちにくい']] };
  assert.equal(CompareProps.safeParse(ok).success, true);
  assert.equal(CompareProps.safeParse({ columns: ['観点', { label: ' ', color: '#fff' }], rows: [['a', 'b']] }).success, false);
  assert.equal(CompareProps.safeParse({ columns: ['観点', 'A'], rows: [['a', { color: '#fff' }]] }).success, false);
});

test('表: 先頭（観点の列）の見出しだけは空でもよい（実モデルが左上を空けて書いた。ほかの列の見出しは今までどおり空は不可）', () => {
  assert.equal(CompareProps.safeParse({ columns: ['', 'Qwen3-TTS', 'Fish Audio'], rows: [['費用', '0円', '月$11']] }).success, true);
  assert.equal(CompareProps.safeParse({ columns: [' ', 'A'], rows: [['費用', '1']] }).success, true);
  assert.equal(CompareProps.safeParse({ columns: ['', ''], rows: [['費用', '1']] }).success, false);
  assert.equal(CompareProps.safeParse({ columns: ['観点', ' '], rows: [['費用', '1']] }).success, false);
  assert.equal(CompareProps.safeParse({ columns: [''], rows: [['費用']] }).success, false);
  assert.match(replaceShapeBlocks('```openui-lang\nroot = Compare(["", "A", "B"], [["費用", "1", "2"]])\n```'), /^\|  \| A \| B \|\n\|---\|---\|---\|\n\| 費用 \| 1 \| 2 \|$/);
});

test('OpenUI Lang: lang-core（画面）と plain の読み手が、実物つきの選択肢と表を同じ値で読む', () => {
  const lib = createLibrary({ components: SHAPE_SPECS.map((s) => defineComponent({ name: s.name, description: s.description, props: s.props, component: null })) });
  const parser = createParser(lib.toJSONSchema());
  for (const code of [
    'root = Choice("見本の表面生地の色", [{label: "ベージュ", color: "#d8c7a8"}, {"label": "グレー", "color": "#9a9a9a"}, "ブラウン"])',
    'root = Choice("ロゴ", [{label: "A案", image: "/api/v1/files/a.png"}, {label: "B案", image: "https://example.com/b.png"}])',
    'root = Compare(["観点", {label: "ベージュ", color: "#d8c7a8"}], [["色", {label: "ベージュ", color: "rgb(216, 199, 168)"}]])',
  ]) {
    const web = parser.parse(code).root?.props;
    assert.ok(web, code);
    const call = parseShapeCall(code);
    const keys = Object.keys(SHAPE_SPECS.find((s) => s.name === call.name).props.shape);
    assert.deepEqual(Object.fromEntries(call.args.map((a, i) => [keys[i], a])), web);
    assert.deepEqual(validateComplete(call.name, web), { ok: true }, code);
  }
});

test('部品を描けない画面（アプリ）: 色は名前の後ろに括弧で色の値、画像は名前だけ。アプリの写しも同じ出力', () => {
  const text = [
    '工場への返事の色を選んでください（色は目安です）。',
    '',
    '```openui-lang',
    'root = Choice("見本の表面生地の色", [{label: "ベージュ", color: "#D8C7A8"}, {label: "グレー", color: "red; x:y"}, "ブラウン"])',
    '```',
    '',
    '```openui-lang',
    'root = Choice("ロゴ", [{label: "A案", image: "/api/v1/files/a.png"}, {label: "B案", image: "javascript:alert(1)"}])',
    '```',
    '',
    '```openui-lang',
    'root = Compare(["観点", {label: "ベージュ", color: "#d8c7a8"}, "グレー"], [["色", {label: "明るい", color: "rgb(216,199,168)"}, "暗め"]])',
    '```',
  ].join('\n');
  const out = replaceShapeBlocks(text);
  assert.match(out, /\*\*見本の表面生地の色\*\*\n1\. ベージュ（#d8c7a8）\n2\. グレー\n3\. ブラウン\n/);
  assert.match(out, /\*\*ロゴ\*\*\n1\. A案\n2\. B案\n/);
  assert.match(out, /\| 観点 \| ベージュ（#d8c7a8） \| グレー \|\n\|---\|---\|---\|\n\| 色 \| 明るい（rgb\(216, 199, 168\)） \| 暗め \|/);
  assert.equal(out.includes('/api/v1/files'), false);
  assert.equal(out.includes('javascript'), false);
  assert.equal(out.includes('```'), false);
  assert.equal(app.replaceShapeBlocks(text), out);
  // 文字だけの選択肢は今までと同じ文章
  assert.equal(replaceShapeBlocks('```openui-lang\nroot = Choice("プラン", ["ベーシック", "プレミアム"])\n```'),
    '**プラン**\n1. ベーシック\n2. プレミアム\n\n（この画面では押せません。番号か選択肢の文字をそのまま送ってください: 「プラン → …」）');
});
