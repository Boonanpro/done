"use client";

import * as React from "react";

/**
 * OBANZAI bar 五条 — GPT Image 2 主役の別案（comp）レイアウト。
 * 画像コンプを主役にした、写真主導の高級飲食店トーン。
 * 見出し=Zen Old Mincho / 本文=Noto Sans JP / ラベル=Zen Kaku Gothic New。
 */
export default function GojoCompLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  React.useEffect(() => {
    const html = document.documentElement;
    const prev = html.style.colorScheme;
    html.style.colorScheme = "dark";
    return () => {
      html.style.colorScheme = prev;
    };
  }, []);

  return (
    <>
      <style>{`
        .theme-gojoc {
          --background: oklch(0.155 0.012 50);
          --foreground: oklch(0.94 0.016 80);
          --card: oklch(0.2 0.014 50);
          --card-foreground: oklch(0.94 0.016 80);
          --popover: oklch(0.2 0.014 50);
          --popover-foreground: oklch(0.94 0.016 80);
          --primary: oklch(0.76 0.14 62);
          --primary-foreground: oklch(0.17 0.02 50);
          --secondary: oklch(0.25 0.016 50);
          --secondary-foreground: oklch(0.94 0.016 80);
          --muted: oklch(0.23 0.012 50);
          --muted-foreground: oklch(0.72 0.02 75);
          --accent: oklch(0.3 0.018 58);
          --accent-foreground: oklch(0.94 0.016 80);
          --destructive: oklch(0.58 0.21 27);
          --border: oklch(0.32 0.014 50);
          --input: oklch(0.32 0.014 50);
          --ring: oklch(0.76 0.14 62 / 0.5);
          --radius: 0.25rem;

          --gojoc-amber: oklch(0.8 0.145 68);
          --gojoc-sumi: oklch(0.1 0.008 50);

          background-color: var(--background);
          color: var(--foreground);
          font-family: "Noto Sans JP", "Hiragino Kaku Gothic ProN", "Yu Gothic", "Meiryo", sans-serif;
          -webkit-font-smoothing: antialiased;
          min-height: 100vh;
        }
        .theme-gojoc h1, .theme-gojoc h2, .theme-gojoc h3, .theme-gojoc .font-headline {
          font-family: "Zen Old Mincho", "Noto Serif JP", serif;
          font-weight: 600;
          letter-spacing: 0.02em;
        }
        .theme-gojoc .font-label {
          font-family: "Zen Kaku Gothic New", "Noto Sans JP", sans-serif;
        }
        .theme-gojoc .font-en {
          font-family: "Cormorant Garamond", "Zen Old Mincho", serif;
          letter-spacing: 0.04em;
        }
      `}</style>
      <link
        rel="stylesheet"
        href="https://fonts.googleapis.com/css2?family=Zen+Old+Mincho:wght@400;500;600;700;900&family=Zen+Kaku+Gothic+New:wght@400;500;700&family=Noto+Sans+JP:wght@400;500;700&family=Cormorant+Garamond:wght@500;600&display=swap"
      />
      <div className="theme-gojoc">{children}</div>
    </>
  );
}
