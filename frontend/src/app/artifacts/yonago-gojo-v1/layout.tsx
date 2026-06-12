"use client";

import * as React from "react";

/**
 * OBANZAI bar 五条 (米子) — 初版（比較用スナップショット）。
 * 現行案 /yonago-gojo の「最初の一発出し」状態を別ページとして復元したもの。
 * テーマ（暗色・フォント）は現行と同じ定義を使用。
 * - 見出し=Zen Old Mincho / 本文=Noto Sans JP / ラベル=Zen Kaku Gothic New
 */
export default function GojoV1Layout({
  children,
}: {
  children: React.ReactNode;
}) {
  React.useEffect(() => {
    const html = document.documentElement;
    const prevColorScheme = html.style.colorScheme;
    html.style.colorScheme = "dark";
    return () => {
      html.style.colorScheme = prevColorScheme;
    };
  }, []);

  return (
    <>
      <style>{`
        .theme-gojo {
          --background: oklch(0.17 0.014 55);
          --foreground: oklch(0.93 0.018 80);
          --card: oklch(0.215 0.016 55);
          --card-foreground: oklch(0.93 0.018 80);
          --popover: oklch(0.215 0.016 55);
          --popover-foreground: oklch(0.93 0.018 80);
          --primary: oklch(0.74 0.135 65);
          --primary-foreground: oklch(0.18 0.02 55);
          --secondary: oklch(0.26 0.018 55);
          --secondary-foreground: oklch(0.93 0.018 80);
          --muted: oklch(0.24 0.014 55);
          --muted-foreground: oklch(0.7 0.022 75);
          --accent: oklch(0.3 0.02 60);
          --accent-foreground: oklch(0.93 0.018 80);
          --destructive: oklch(0.58 0.21 27);
          --border: oklch(0.33 0.016 55);
          --input: oklch(0.33 0.016 55);
          --ring: oklch(0.74 0.135 65 / 0.5);
          --radius: 0.4rem;

          --gojo-amber: oklch(0.78 0.14 70);
          --gojo-sumi: oklch(0.12 0.01 55);

          background-color: var(--background);
          color: var(--foreground);
          font-family: "Noto Sans JP", "Hiragino Kaku Gothic ProN", "Yu Gothic", "Meiryo", sans-serif;
          -webkit-font-smoothing: antialiased;
          min-height: 100vh;
        }
        .theme-gojo h1, .theme-gojo h2, .theme-gojo h3, .theme-gojo .font-headline {
          font-family: "Zen Old Mincho", "Noto Serif JP", serif;
          font-weight: 600;
          letter-spacing: 0.01em;
        }
        .theme-gojo .font-label {
          font-family: "Zen Kaku Gothic New", "Noto Sans JP", sans-serif;
        }
        .theme-gojo .font-en {
          font-family: "Cormorant Garamond", "Zen Old Mincho", serif;
          letter-spacing: 0.04em;
        }
      `}</style>
      <link
        rel="stylesheet"
        href="https://fonts.googleapis.com/css2?family=Zen+Old+Mincho:wght@400;500;600;700;900&family=Zen+Kaku+Gothic+New:wght@400;500;700&family=Noto+Sans+JP:wght@400;500;700&family=Cormorant+Garamond:wght@500;600&display=swap"
      />
      <div className="theme-gojo">{children}</div>
    </>
  );
}
