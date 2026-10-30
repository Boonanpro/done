import { VoiceControlsRuntime } from '@/components/artifacts/voice-controls-runtime';
import { DedicatedArtifactProvider } from '@/components/artifacts/artifact-link';
import { LiveVersionMark } from '@/components/artifacts/live-version-mark';
import { InspectorRuntimeLoader } from '@/components/dan/inspector-runtime-loader';
import { installLiveGuard } from '@/lib/live-version/guard';
import { readLiveVersion } from '@/lib/live-version/server';
import type { Metadata } from 'next';
import { headers } from 'next/headers';
import { CUSTOM_DOMAIN_SLUG_MAP } from '@/lib/custom-domain-rewrites.generated';
import { artifactSlugFromServerHost } from '../../../scripts/artifact-routing-config';

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
 *
 * ④ liveGuardScript（成果物タブ＝開発サーバー 3001 の時だけ）:
 *    画面が動かしている部品の版と、今のファイルの版を比べ、違えば部品を取り直して
 *    読み直す（lib/live-version/guard.ts）。ダンが直した物と本人が見ている物が
 *    食い違わないようにする。HTML は毎回取り直されるので、部品が古くてもこの処理は新しい。
 */

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

function prePaintScript(fallbackSlug: string | null): string {
  // JSON serialization is intentional: this value becomes a JavaScript
  // literal inside the blocking script below, not executable source.
  const serializedFallbackSlug = JSON.stringify(fallbackSlug || '');
  return `
(function(){
  try {
    // 公開閲覧モード (iframe 外、トップレベル訪問) では何もしない。
    // 直書き運用 (DB をバイパスして JSX を直接更新) になったので、
    // localStorage の override は不要。残骸があれば触らずに無視する。
    var inIframe = false;
    try { inIframe = window.top !== window.self; } catch (e) { inIframe = true; }
    if (!inIframe) return;
    if (new URLSearchParams(location.search).get('dan_preview') === '1') return;
    var match = location.pathname.match(/\\/(?:artifacts|preview)\\/([^/]+)/);
    var slug = match && match[1];
    // A dedicated Vercel project serves its artifact from the root path. Its project
    // configuration is the authoritative identity in that case.
    if (!slug) slug = ${serializedFallbackSlug};
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
}

function liveGuardScript(serverVersion: string): string {
  return `(${installLiveGuard.toString()})(${JSON.stringify({ serverVersion })});`;
}

const scrollResetStyle = `
html, body {
  height: auto !important;
  overflow: auto !important;
}
`.trim();

export default async function ArtifactsLayout({ children }: { children: React.ReactNode }) {
  // This is deliberately server-only. ARTIFACT_ONLY_SLUG is set on every
  // one-artifact Vercel project and must not be copied into a public host map.
  //
  // 公開済み編集の反映はここでは行わない。公開時に成果物ディレクトリへ焼き込まれた
  // release.gen.json を各成果物の server page が読み、EditableText が初回 HTML に
  // 描画する（lib/editable-release.ts）。配信ページに DOM 後書き換えは存在しない。
  const requestHeaders = await headers();
  const dedicatedArtifactSlug = artifactSlugFromServerHost(requestHeaders.get('host') || '', CUSTOM_DOMAIN_SLUG_MAP, process.env);
  // 開発サーバー（3001）だけが current.gen.ts を書く。本番ビルド・Vercel では空。
  const liveVersion = process.env.NODE_ENV === 'development' ? readLiveVersion() : '';
  return (
    <>
      {liveVersion ? <script dangerouslySetInnerHTML={{ __html: liveGuardScript(liveVersion) }} /> : null}
      <style dangerouslySetInnerHTML={{ __html: scrollResetStyle }} />
      <script dangerouslySetInnerHTML={{ __html: prePaintScript(dedicatedArtifactSlug) }} />
      <ArtifactStructuredData />
      <ArtifactAnalytics />
      <DedicatedArtifactProvider slug={dedicatedArtifactSlug}>{children}</DedicatedArtifactProvider>
      <InspectorRuntimeLoader fallbackSlug={dedicatedArtifactSlug} />
      <LiveVersionMark />
      <VoiceControlsRuntime />
    </>
  );
}
