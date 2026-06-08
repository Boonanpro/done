import type { Metadata } from "next";
import { PainaShell } from "./components/paina-shell";

export const metadata: Metadata = {
  title: "株式会社パイナ｜AIエージェント Done（ダン）の開発",
  description:
    "株式会社パイナは、人とともに働くAIエージェント「Done（ダン）」を開発しています。思想とアプローチ、事業内容（Done開発・HP制作・DX支援）、実績をご紹介します。",
  manifest: "/artifacts/paina/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    title: "PAINA",
    statusBarStyle: "default",
  },
  openGraph: {
    title: "株式会社パイナ｜AIエージェント Done（ダン）の開発",
    description:
      "人とともに働くAIエージェント「Done（ダン）」を開発する会社です。",
    type: "website",
  },
};

export default function PainaLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <PainaShell>{children}</PainaShell>;
}
