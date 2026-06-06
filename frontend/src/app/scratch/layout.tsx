/**
 * scratch ページ共通レイアウト。
 *
 * scratch/ は使い捨ての実験・コンポーネントギャラリー置き場。
 *
 * ルート globals.css は html/body を `height:100%; overflow:hidden` に固定している
 * （チャットシェルが画面いっぱいに収まり、スクロールは内部ペインで行う固定
 * ビューポート設計のため正しい）。しかし scratch のページは「ブラウザの通常の
 * 文書スクロール」で見るので、この床を引き継ぐと縦長ページが切れてスクロール
 * できなくなる。artifacts/layout.tsx と同じ手口で scratch 配下だけ解放する。
 *
 * - unlayered な <style> なので globals.css の @layer base より優先される
 * - `h-screen overflow-y-auto` で自己完結する既存ページ（motion/typography 等）も
 *   body:auto で両立する（中身が 100vh なので body 自体は溢れない）
 * - これにより scratch ページは既定でスクロールでき、ページ個別に解除を書き忘れて
 *   縦長ページが切れる事故が再発しない
 */

const scrollResetStyle = `
html, body {
  height: auto !important;
  overflow: auto !important;
}
`.trim();

export default function ScratchLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <style dangerouslySetInnerHTML={{ __html: scrollResetStyle }} />
      {children}
    </>
  );
}
