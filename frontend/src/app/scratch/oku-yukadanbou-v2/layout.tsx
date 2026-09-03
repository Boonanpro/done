import type { Metadata, Viewport } from "next";

/**
 * 置く床暖房 ドライテストLP v2（画像ファースト方式）の閲覧用レイアウト。
 * recipes/image-first-lp.md 手順5の必須事項:
 * - globals.css の html/body overflow:hidden を解除して文書スクロールに戻す
 * - ルート layout の maximumScale:1 を上書きしてピンチ拡大を許可
 */

export const metadata: Metadata = {
  title: "置く床暖房 — コンセントで使える床暖房",
  description:
    "工事なし。床に置いてコンセントに挿すだけの床暖房マット。賃貸でも使えます。350×230cm・約1000W。現在開発中、先行登録を受付中です。",
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
  background: #faf3e9;
}
`.trim();

export default function OkuYukadanbouV2Layout({
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
