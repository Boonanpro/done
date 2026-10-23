// 見つからないページ。
//
// 成果物タブ（/preview/<slug>）の 404 は、ほとんどが一時的なもの: 成果物プレビュー用の
// 開発サーバー（3001）が設定の変更などで作り直されている数秒の間に、開いていた画面が
// 読み直されると 404 になり、そのまま残った（2026-10-18: 本人の X運用室タブが 404 のまま
// になっていた）。成果物のページなら、表示できるようになった時点で自動で読み直す。
// 文言の切り替えは <html data-dan-nf> と CSS で行う（React が描いた文字を書き換えると、
// 画面の組み立て直しで元に戻される）。
const retryScript = `
(function(){
  if (!/^\\/(preview|artifacts)\\//.test(location.pathname)) return;
  var root = document.documentElement;
  root.setAttribute('data-dan-nf', 'waiting');
  var started = Date.now();
  function retry(){
    fetch(location.href, { cache: 'no-store', credentials: 'same-origin' }).then(function(res){
      if (res.status !== 404) { location.reload(); return; }
      if (Date.now() - started < 180000) setTimeout(retry, 3000);
      else root.removeAttribute('data-dan-nf');
    }, function(){ setTimeout(retry, 3000); });
  }
  setTimeout(retry, 2000);
})();
`.trim();

const style = `
.dan-nf-waiting { display: none; }
html[data-dan-nf="waiting"] .dan-nf-waiting { display: block; }
html[data-dan-nf="waiting"] .dan-nf-default { display: none; }
`.trim();

export default function NotFound() {
  return (
    <div style={{ minHeight: '100dvh', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24, textAlign: 'center', fontFamily: 'system-ui, sans-serif', fontSize: 14 }}>
      <style dangerouslySetInnerHTML={{ __html: style }} />
      <p className="dan-nf-default">404: このページは見つかりませんでした。</p>
      <p className="dan-nf-waiting">このページを表示する準備をしています。表示できるようになったら自動で読み直します。</p>
      <script dangerouslySetInnerHTML={{ __html: retryScript }} />
    </div>
  );
}
