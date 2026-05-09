import { InspectorRuntimeLoader } from '@/components/dan/inspector-runtime-loader';

/**
 * artifacts ページ共通レイアウト。
 *
 * 通常の成果物 (HP / ダッシュボード / ツール / LP) はここに置く。
 * (`demo/` は提案動画用プロトタイプ専用)
 *
 * ① 先頭に blocking inline script を挿入:
 *    localStorage に記録済みの overrides を読み、CSS セレクタに変換して
 *    <style> を head に注入する。初回 paint の時点で既に overrides が
 *    当たっている状態になるので「一瞬元の状態が見える」flash を防ぐ。
 *
 * ② InspectorRuntimeLoader は React ハイドレーション後に動作:
 *    バックエンドから最新 overrides を取得 → localStorage 同期 → DOM 再適用。
 *    src/alt 等 CSS で表現できない属性もここで当てる。
 */

const publicArtifactHostMap = JSON.stringify({
  'kittoku.vercel.app': 'kittoku',
  'yoshikawa-tokuso.vercel.app': 'kittoku',
});

const envArtifactHostMap = JSON.stringify(
  process.env.NEXT_PUBLIC_ARTIFACT_HOST_MAP || '',
);

const prePaintScript = `
(function(){
  try {
    var match = location.pathname.match(/\\/(?:artifacts|preview)\\/([^/]+)/);
    var slug = match && match[1];
    if (!slug) {
      var hosts = ${publicArtifactHostMap};
      slug = hosts[location.host];
    }
    if (!slug) {
      var rawHostMap = ${envArtifactHostMap};
      rawHostMap.split(',').some(function(pair){
        var parts = pair.split(':').map(function(s){ return s.trim(); });
        if (parts[0] && parts[1] && parts[0] === location.host) {
          slug = parts[1];
          return true;
        }
        return false;
      });
    }
    if (!slug) return;
    var raw = localStorage.getItem('dan-inspector-overrides-' + slug);
    if (!raw) return;
    var rows;
    try { rows = JSON.parse(raw); } catch (e) { return; }
    if (!rows || !rows.length) return;
    var css = rows.map(function(r){
      var key = r.elementKey || r.element_key;
      if (!key) return '';
      var parts = key.split('>');
      var sel = 'body';
      for (var i = 0; i < parts.length; i++) {
        var m = parts[i].match(/^(.+?)\\[(\\d+)\\]$/);
        if (!m) return '';
        sel += ' > ' + m[1] + ':nth-child(' + (parseInt(m[2], 10) + 1) + ')';
      }
      var styles = r.styles || {};
      var body = Object.keys(styles).map(function(k){
        return k + ': ' + styles[k] + ' !important';
      }).join('; ');
      if (!body) return '';
      return sel + ' { ' + body + ' }';
    }).filter(Boolean).join('\\n');
    if (!css) return;
    var style = document.createElement('style');
    style.id = 'dan-inspector-prepaint';
    style.textContent = css;
    (document.head || document.documentElement).appendChild(style);
  } catch (err) { /* ignore */ }
})();
`.trim();

export default function ArtifactsLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <script dangerouslySetInnerHTML={{ __html: prePaintScript }} />
      {children}
      <InspectorRuntimeLoader />
    </>
  );
}
