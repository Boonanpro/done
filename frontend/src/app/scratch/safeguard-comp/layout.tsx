import type { Metadata, Viewport } from "next";

/**
 * Safeguard LP（第5版）カンプ確認用レイアウト。
 * recipes/image-first-lp.md 手順1「カンプ承認チェックポイント」の簡易プレビュー。
 * - globals.css の html/body overflow:hidden を解除して文書スクロールに戻す
 * - ルート layout の maximumScale:1 を上書きしてピンチ拡大を許可
 */

export const metadata: Metadata = {
  title: "Safeguard LP カンプ（確認用）",
  description: "画像ファーストLPのカンプ全景。承認前の確認用ページ。",
};

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
  background: #0b0b0d;
}
`.trim();

export default function SafeguardCompLayout({
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
