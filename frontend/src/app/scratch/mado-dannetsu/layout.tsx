import type { Viewport } from "next";

/**
 * まど断熱シート（冬用）ドライテストLP の閲覧用レイアウト。
 * recipes/image-first-lp.md 手順5の必須事項:
 * - globals.css の html/body overflow:hidden を解除して文書スクロールに戻す
 * - ルート layout の maximumScale:1 を上書きしてピンチ拡大を許可
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

export default function MadoDannetsuLayout({
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
