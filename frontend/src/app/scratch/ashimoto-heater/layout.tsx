import type { Metadata, Viewport } from "next";

import { ThemeShell } from "./theme-shell";

/**
 * 足元パネルヒーター（ドライテストLP）専用レイアウト（server component）。
 * metadata をここで宣言し、テーマ適用はクライアント側の ThemeShell に委譲する。
 * ルート layout の maximumScale:1 を上書きして、スマホでのピンチ拡大を許可する。
 */
export const metadata: Metadata = {
  title: "足元パネルヒーター — 足元だけ、暖める。｜デスクの下に置く150Wの遠赤外線パネル",
  description:
    "暖房は効いているのに、足だけ寒い。デスクの下に置く遠赤外線パネルヒーター。消費電力150Wで1時間およそ4.7円。音ゼロ・風ゼロ・乾燥しない。開発中につき先行登録を受付中です。",
  openGraph: {
    title: "足元パネルヒーター — 足元だけ、暖める。",
    description:
      "デスクの下に置く150Wの遠赤外線パネル。1時間およそ4.7円、音も風もありません。開発中の先行登録を受付中。",
    type: "website",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,
  userScalable: true,
};

export default function AshimotoHeaterLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <ThemeShell>{children}</ThemeShell>;
}
