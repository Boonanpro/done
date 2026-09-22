const {test} = require('node:test');
const assert = require('node:assert/strict');
const ts = require('../mobile/node_modules/typescript');
const vm = require('node:vm'), fs = require('node:fs');
const context = {exports:{}};
vm.runInNewContext(ts.transpileModule(fs.readFileSync('mobile/call-intent.ts','utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,context);
const {explicitCallEnd,needsCallControlReview} = context.exports;
test('actual spoken ending requests close even without Live delegation', () => {
  for(const text of ['もういいわ、ちょ、電話切って','OK、電話切って','切った?会話終わりにしてよ','この話はもういい。通話を切ってください。','会話を終わらせて','この会話を終わらせてください']) assert.equal(explicitCallEnd(text),true,text);
});

test('ambiguous call-ending words select contextual review, never direct hangup', () => {
  for(const text of ['切って','あ、ごめん、ちょっと電話きて','また呼ぶから待機して','今日はここまで。また後で']) {
    assert.equal(needsCallControlReview(text),true,text);
    assert.equal(explicitCallEnd(text),false,text);
  }
  for(const text of ['今日何曜日？','音が小さい','この動画を編集して','調査は終わった？'])
    assert.equal(needsCallControlReview(text),false,text);
});
test('negation, quotes, questions and work cancellation do not terminate the call', () => {
  for(const text of ['電話切ってほしくない','電話を切っていいか聞いて','「電話切って」と言ったのに','この作業は終わりにして','電話切った？','会話を終了しても作業は続く？','切って','通話を切らないで','電話切って。いや、まだ切らないで']) assert.equal(explicitCallEnd(text),false,text);
});
