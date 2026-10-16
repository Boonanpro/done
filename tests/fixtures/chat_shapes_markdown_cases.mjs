// 部品のコードブロックの読み手（plain.ts topLevelFences と app/agent/chat_shapes.py top_level_fences）を
// Markdown の読み手 remark-parse（micromark）と突き合わせるための入力。
// - verifierCases: 確かめる役の27入力（scratch verify3/parity.mjs と同じ作り方）
// - targetedCases: 段落・入れ物・HTML・空白・タブ・改行・言語名の境目を狙った入力
// - generatedCases: 下の行の部品を種つきの乱数で並べた入力（同じ種なら同じ入力）
// 期待値は remark-parse から作る（tests/chat_shapes_markdown.test.mjs と make_chat_shapes_markdown_corpus.mjs）。

const B = '```';
const SHAPE = 'root = Choice("Q", ["A", "B"])';

export function verifierCases() {
  const block = B + 'openui-lang\nroot = Choice("Q 😀", ["A", "B"])\n' + B;
  const cases = {
    normal: block, twice: block + '\n' + block, crlf: block.replaceAll('\n', '\r\n'), comment: '<!--\n' + block + '\n-->',
    pre: '<pre>\n' + block + '\n</pre>', div: '<div>\n' + block + '\n</div>', htmlAfterFence: B + 'text\nx\n' + B + '\n<x>\n' + block + '\n</x>',
    htmlAfterComment: '<!--x-->\n<x>\n' + block + '\n</x>', htmlAfterHeading: '# Heading\n<x>\n' + block + '\n</x>',
    htmlParagraph: 'hello\n<x>\n' + block + '\n</x>', indented: '    text\n<x>\n' + block + '\n</x>',
    proposal: B + 'proposal\na.json\n' + B + '\n' + block, quoted: '> <!--\n' + block + '\n> -->',
  };
  for (const [name, w] of Object.entries({ nbsp: '\u00a0', bom: '\ufeff', nel: '\u0085', ls: '\u2028', ps: '\u2029', ideographic: '\u3000', tab: '\t' })) {
    cases['ws-' + name] = block.replace('Q 😀', 'Q' + w + '😀');
    cases['html-ws-' + name] = '<span' + w + 'x>\n' + block + '\n</span>';
  }
  return Object.entries(cases).map(([name, text]) => ({ name: 'verifier:' + name, text }));
}

const F = (lang = 'openui-lang', code = SHAPE, fence = B) => fence + lang + '\n' + code + '\n' + fence;

export function targetedCases() {
  const T = {
    // 段落の途中かどうか（種類7は段落を切れない。見出し・フェンス・HTML の後は段落ではない）
    afterHeading: '# h\n<span>\n' + F() + '\n</span>',
    afterSetext: 'a\n===\n<span>\n' + F(),
    afterThematic: '***\n<span>\n' + F(),
    afterClosedFence: B + 'js\nx\n' + B + '\n<span>\n' + F(),
    afterCommentSameLine: '<!-- c -->\n<span>\n' + F(),
    afterIndented: '    code\n<span>\n' + F(),
    afterBlank: 'a\n\n<span>\n' + F(),
    paragraphSpan: 'a\n<span>\n' + F(),
    paragraphDiv: 'a\n<div>\n' + F(),
    paragraphComment: 'a\n<!--\n' + F() + '\n-->',
    divEndsAtBlank: '<div>\n' + F() + '\n\n' + F('openui'),
    commentOneLine: '<!-->\n' + F(),
    commentDashes: '<!--->\n' + F(),
    piOneLine: '<?>\n' + F(),
    declaration: '<!DOCTYPE html>\n' + F(),
    cdata: '<![CDATA[\n' + F() + '\n]]>\n' + F('openui'),
    preSelfClosing: '<pre/>\n' + F(),
    preClose: '</pre>\n' + F(),
    scriptEnd: '<script>\n' + F() + '\n</script>\n' + F('openui'),
    attrs: '<a href="x" title=\'y\' data-x=z>\n' + F(),
    attrBadQuote: '<a b"c">\n' + F(),
    attrEqEq: '<a b=c=d>\n' + F(),
    attrSlashValue: '<a b=/>\n' + F(),
    attrNoSpace: '<a b="c"d>\n' + F(),
    closeTagSpace: '</span >\n' + F(),
    tagTrailingText: '<span> x\n' + F(),
    autolink: '<https://example.com>\n' + F(),
    // 空白の定義（半角スペースとタブだけ）
    wsNelTag: '<span\u0085x>\n' + F(), wsNbspTag: '<span\u00a0x>\n' + F(), wsTabTag: '<span\tx>\n' + F(),
    ideographicBlank: '<div>\n\u3000\n' + F(), nbspBlank: '<div>\n\u00a0\n' + F(), tabBlank: '<div>\n\t\n' + F(),
    langNbsp: F('openui-lang\u00a0x'), langIdeographic: F('openui-lang\u3000'), langTabMeta: F('openui-lang\tmeta'),
    langCase: F('OpenUI-Lang'), langEscape: F('openui\\-lang'), langRef: F('&#111;penui'), langHexRef: F('openui&#x2D;lang'),
    langNamedRef: F('openui&amp;'), langBacktick: B + 'openui-lang `x`\n' + SHAPE + '\n' + B, tildeBacktick: '~~~openui-lang `x`\n' + SHAPE + '\n~~~',
    // 改行・BOM・NUL
    loneCr: 'a\r' + F().replaceAll('\n', '\r'), crlfMulti: B + 'openui-lang\r\nroot = Steps(\r\n["a"])\r\n' + B,
    bom: '\ufeff' + F(), nul: B + 'openui-lang\nroot = Steps(["a\u0000b"])\n' + B,
    unclosed: 'a\n\n' + B + 'openui-lang\n' + SHAPE, unclosedNl: B + 'openui-lang\n' + SHAPE + '\n', unclosedNlNl: B + 'openui-lang\n' + SHAPE + '\n\n',
    emptyFence: B + 'openui-lang\n' + B, openerOnly: B + 'openui-lang',
    // 字下げ・タブ
    indent3: '   ' + F().replaceAll('\n', '\n   '), indent4: '    ' + F().replaceAll('\n', '\n    '),
    indent2Content: '  ' + B + 'openui-lang\n    a\n b\nc\n  ' + B, tabContent: ' ' + B + 'openui-lang\n\ta\n' + B,
    tabIndentFence: '\t' + F(), spaceTabFence: ' \t' + F(), closeIndented4: F().replace(/\n```$/, '\n    ```'),
    closeShort: B + '`openui-lang\n' + SHAPE + '\n' + B + '\n' + B + '`', closeWithText: F().replace(/```$/, '``` x'),
    // 入れ物
    quoteFence: '> ' + F().replaceAll('\n', '\n> '), quoteThenFence: '> a\n' + F(), quoteLazySpan: '> a\n<span>\n' + F(),
    quoteLazySpanBlank: '> a\n<span>\n\n' + F(), quoteLazyDiv: '> a\n<div>\n' + F(), quoteTab: '>\t' + F().replaceAll('\n', '\n>\t'),
    listThenFence: '- a\n' + F(), listBlankFence: '- a\n\n' + F(), listIndentedFence: '- a\n\n  ' + F().replaceAll('\n', '\n  '),
    listInnerFenceOpen: '- a\n  ' + B + 'js\n' + F(), listHeadingSpan: '- # h\n<span>\n' + F(), listLazySpan: '- a\n<span>\n' + F(),
    orderedInterrupt: 'a\n2) b\n' + F(), orderedOne: 'a\n1) b\n   ' + F().replaceAll('\n', '\n   '),
    lazyOrdered: '> a\n2) b\n   ' + F().replaceAll('\n', '\n   '), nestedInterrupt: 'a\n- 2) x\n' + F(),
    indentedThenOrdered: '    code\n\n2) x\n   ' + F().replaceAll('\n', '\n   '), emptyItemInterrupt: 'a\n-\n  ' + F().replaceAll('\n', '\n  '),
    emptyItemBlank: '-\n\n  ' + F().replaceAll('\n', '\n  '), listTab: '-\t' + F().replaceAll('\n', '\n\t'),
    listWide: '-     a\n      ' + F(), siblingItem: '- a\n- ' + F().replaceAll('\n', '\n  '), starBreak: '* * *\n' + F(),
    tenDigits: '1234567890. a\n' + F(), defSetext: '[a]: /b\n===\n<span>\n' + F(), headingSeven: '####### x\n<span>\n' + F(),
    defThenParaSetext: '[a]: /b\nc\n===\n<span>\n' + F(), defTitleSetext: '[a]: /b\n"t"\n===\n<span>\n' + F(),
    defBadSetext: '[a]: /b x\n===\n<span>\n' + F(), defDashOne: '[a]: /b\n-\n  ' + F().replaceAll('\n', '\n  '),
    defMultiLineLabel: '[a\nb]: /c\n===\n<span>\n' + F(), defAngle: '[a]: <b c>\n===\n<span>\n' + F(),
    setextLazy: '> a\n---\n' + F(), setextAfterList: '- a\n===\n<span>\n' + F(),
  };
  return Object.entries(T).map(([name, text]) => ({ name: 'targeted:' + name, text }));
}

// 乱数で並べる行の部品
const LINES = [
  'a', 'text b', '', '  ', '\t', '\u3000', '\u00a0',
  B + 'openui-lang', B + 'openui', '~~~openui-lang', B, '~~~', '````', '````openui-lang', B + 'js', '  ' + B + 'openui-lang', '   ~~~openui',
  '    ' + B + 'openui-lang', B + 'openui-lang x', B + 'OpenUI', SHAPE, '  ' + SHAPE, '\t' + SHAPE,
  '<!--', '-->', '<!-- x -->', '<div>', '</div>', '<span>', '</span>', '<x>', '<pre>', '</pre>', '<pre/>', '<?php', '?>',
  '<!DOCTYPE html>', '<![CDATA[', ']]>', '<span\u0085x>', '<span\u00a0x>', '<span\tx>', '<a href="x">', '<a b=c=d>',
  '# h', '#h', '####### h', '===', '---', '***', '- - -', '___',
  '- a', '* a', '+ a', '1. a', '2) a', '-', '1.', '-\ta', '-     a', '  - b', '   1. c',
  '> a', '>', '> ' + B + 'openui-lang', '> <!--', '>\t' + B, '> - a',
  '    code', '\tcode', '  text', '      deep', '[a]: /b',
  '[a]: /b "t"', '[a]:', '[b]: <c d>', '"t"', "'t'", '[x]: /y (z)', '[x]: a(b', '[]: /u', '[a\\]]: /u', '- [a]: /b',
  '| a | b |', '|---|---|', '| c | d |', 'a | b', '- | x |',
];

function mulberry32(seed) {
  return () => {
    seed |= 0; seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function generatedCases(seed, n, maxLines = 12) {
  const rnd = mulberry32(seed);
  const out = [];
  for (let k = 0; k < n; k++) {
    const count = 1 + Math.floor(rnd() * maxLines);
    const lines = [];
    for (let i = 0; i < count; i++) lines.push(LINES[Math.floor(rnd() * LINES.length)]);
    const r = rnd();
    const eol = r < 0.1 ? '\r\n' : r < 0.15 ? '\r' : '\n';
    let text = lines.join(eol);
    if (rnd() < 0.3) text += eol;
    if (rnd() < 0.03) text = '\ufeff' + text;
    out.push({ name: `generated:${seed}:${k}`, text });
  }
  return out;
}
