import { InspectorRuntimeLoader } from '@/components/dan/inspector-runtime-loader';
import type { Metadata } from 'next';

import { ArtifactAnalytics } from './_seo/analytics';
import { ArtifactStructuredData } from './_seo/structured-data';

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
 *
 * ③ scrollResetStyle:
 *    ルート globals.css は html/body を `height:100%; overflow:hidden` に固定
 *    している（チャットシェルが画面いっぱいに収まり、スクロールは内部ペインで
 *    行う設計のため正しい）。しかし成果物ページ (LP / 募集ページ / 縦長ツール) は
 *    「ブラウザの通常の文書スクロール」で見るものなので、この床を引き継ぐと
 *    画面より下が切れてスクロールできなくなる。
 *    そこで /artifacts・/preview 配下だけ html/body のスクロールを解放する。
 *    - unlayered な <style> なので globals.css の @layer base より優先される
 *    - `h-screen` で自分を画面高に固定するダッシュボード型成果物 (例 new-attack) は
 *      height:100vh で自己完結するため body:auto でも壊れず両立する
 *    - これにより「成果物は普通にスクロールできる」が既定になり、ページ個別に
 *      解除を書き忘れて縦長ページが切れる事故が再発しなくなる
 */

const publicArtifactHostMap = JSON.stringify({
  'kittoku.vercel.app': 'kittoku',
  'yoshikawa-tokuso.vercel.app': 'kittoku',
});

const envArtifactHostMap = JSON.stringify(
  process.env.NEXT_PUBLIC_ARTIFACT_HOST_MAP || '',
);

export const metadata: Metadata = {
  title: '成果物プレビュー',
  description: 'DANで作成した成果物の公開プレビューです。',
  manifest: '/manifest.webmanifest',
  appleWebApp: {
    capable: true,
    title: '成果物',
    statusBarStyle: 'default',
  },
};

const prePaintScript = `
(function(){
  try {
    // 公開閲覧モード (iframe 外、トップレベル訪問) では何もしない。
    // 直書き運用 (DB をバイパスして JSX を直接更新) になったので、
    // localStorage の override は不要。残骸があれば触らずに無視する。
    var inIframe = false;
    try { inIframe = window.top !== window.self; } catch (e) { inIframe = true; }
    if (!inIframe) return;
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

const scrollResetStyle = `
html, body {
  height: auto !important;
  overflow: auto !important;
}
`.trim();

export default function ArtifactsLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <style dangerouslySetInnerHTML={{ __html: scrollResetStyle }} />
      <script dangerouslySetInnerHTML={{ __html: prePaintScript }} />
      <ArtifactStructuredData />
      <ArtifactAnalytics />
      {children}
      <InspectorRuntimeLoader />
    </>
  );
}
