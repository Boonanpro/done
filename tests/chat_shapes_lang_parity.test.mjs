// Web（OpenUI の lang-core が読む値）と、部品を描けない画面向けの読み手（plain.ts parseShapeCall）が同じ値を読むか。
// 文字列のエスケープ（\uXXXX、\r、\"、\/、\b、\f、\t、\n、サロゲートペア）と、'...' の独自規則。
// lang-core が受け付けないエスケープは、Web では生の文字（バックスラッシュごと）になるが、plain は読めない（null）として
// 元のブロックを残す（黙って別の文字列に変えない）。その違いもここで固定する。
// 実行: node --experimental-strip-types --test tests/chat_shapes_lang_parity.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { createLibrary, defineComponent, createParser } from '../frontend/node_modules/@openuidev/lang-core/dist/index.mjs';
import { SHAPE_SPECS } from '../frontend/src/lib/chat-shapes/schema.ts';
import { parseShapeCall, replaceShapeBlocks } from '../frontend/src/lib/chat-shapes/plain.ts';
import { replaceShapeBlocks as mobileReplace } from '../mobile/chat-shapes-plain.ts';

const BS = '\\';   // 1文字のバックスラッシュ（試験の本文に \u をそのまま書かない）
const lib = createLibrary({ components: SHAPE_SPECS.map((s) => defineComponent({ name: s.name, description: s.description, props: s.props, component: null })) });
const parser = createParser(lib.toJSONSchema());
const webProps = (code) => parser.parse(code).root?.props ?? null;
const plainProps = (code) => {
  const call = parseShapeCall(code);
  if (!call) return null;
  const keys = Object.keys(SHAPE_SPECS.find((s) => s.name === call.name).props.shape);
  return Object.fromEntries(call.args.map((a, i) => [keys[i], a]));
};

test('"..." の JSON エスケープ: Web と同じ値を読む（日本語の \\u、CR、引用符、スラッシュ、絵文字のサロゲートペア）', () => {
  const code = `root = Steps(["${BS}u65e5${BS}u672c${BS}u8a9e", "a${BS}rb", "q${BS}"x", "s${BS}/l", "${BS}ud83d${BS}ude00", "t${BS}tb${BS}bf${BS}f${BS}nz", "back${BS}${BS}slash"])`;
  const web = webProps(code);
  assert.ok(web, 'lang-core reads it');
  assert.deepEqual(plainProps(code), web);
  assert.deepEqual(web.steps, ['日本語', 'a\rb', 'q"x', 's/l', '😀', 't\tb\bf\f\nz', 'back\\slash']);
  // 変換した文章にも同じ値が出る（APK の見え方）
  const out = replaceShapeBlocks('```openui-lang\n' + code + '\n```');
  assert.match(out, /^1\. 日本語\n2\. a\rb\n3\. q"x\n4\. s\/l\n5\. 😀\n/);
  assert.equal(mobileReplace('```openui-lang\n' + code + '\n```'), out);
});

test("'...' の lang-core 独自規則: \\' \\\\ \\n \\t だけ、それ以外はバックスラッシュを落とす（Web と同じ）", () => {
  const code = `root = Steps(['it${BS}'s', 'a${BS}nb', 'x${BS}qy', 'u${BS}u65e5', 'tab${BS}t', 'bs${BS}${BS}'])`;
  const web = webProps(code);
  assert.deepEqual(web.steps, ["it's", 'a\nb', 'xqy', 'uu65e5', 'tab\t', 'bs\\']);
  assert.deepEqual(plainProps(code), web);
});

test('JSON に無いエスケープ・生の制御文字: Web は生の文字を見せるが、plain は読めない（元のブロックを残す）', () => {
  for (const code of [`root = Steps(["bad ${BS}q escape"])`, `root = Steps(["bad ${BS}u12 hex"])`, 'root = Steps(["raw\nnewline"])']) {
    const web = webProps(code);
    assert.ok(web && Array.isArray(web.steps), 'lang-core still shows something');
    assert.equal(parseShapeCall(code), null);
    const block = '```openui-lang\n' + code + '\n```';
    assert.equal(replaceShapeBlocks(block), block);
    assert.equal(mobileReplace(block), block);
  }
});

test('ふつうの部品5つ: 文字列・数値・配列・オブジェクトが Web と同じ値', () => {
  for (const code of [
    'root = Compare(["観点", "A", "B"], [["月額", "368円", "980円"]], "プランの違い")',
    'root = Choice("進め方", ["先に見積もりを取る", "今すぐ発注する"])',
    'root = Input("月の予算", "number", "万円", "例: 3")',
    'root = Steps(["アプリを開く", "予約を確認する"], "当日の流れ")',
    'root = Chart("line", ["9/8", "9/9"], [{name: "広告費", values: [1200, 980.5]}, {name: "登録", values: [1, 0]}], "円", "日別")',
  ]) {
    const web = webProps(code);
    assert.ok(web, code);
    assert.deepEqual(plainProps(code), web, code);
  }
});
