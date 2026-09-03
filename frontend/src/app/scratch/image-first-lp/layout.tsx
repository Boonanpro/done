import type { Viewport } from "next";

/**
 * 画像ファーストLP試作の閲覧用レイアウト。
 * - ルート globals.css の html/body { overflow: hidden }（チャットシェル用の床）を
 *   解除して通常の文書スクロールに戻す（artifacts/layout.tsx と同じ手法）
 * - ルート layout の maximumScale:1 を上書きしてピンチ拡大を許可する
 *   （画質確認・スマホ閲覧に必須）
 */

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,
  userScalable: true,
};

const scrollResetStyle = `
html, body {
  height: auto !important;
  overflow: auto !important;
}
`.trim();

export default function ImageFirstLpLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <>
      <style dangerouslySetInnerHTML={{ __html: scrollResetStyle }} />
      {children}
    </>
  );
}
