"use client";

import * as React from "react";

/**
 * 吉川特装HP専用レイアウト。
 * - ルート layout.tsx が固定しているダーク背景 / overflow:hidden を解除
 * - CSS変数を白ベースの新明和風テーマに上書き
 */
export default function YoshikawaLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  React.useEffect(() => {
    // 手動編集で壊れた overrides を一度だけクリア。
    try {
      const RESET_FLAG = "kikkawa-inspector-reset-2026-04-26-v2";
      if (!localStorage.getItem(RESET_FLAG)) {
        localStorage.removeItem("dan-inspector-overrides-yoshikawa-tokuso");
        localStorage.removeItem("dan-inspector-overrides-kittoku");
        document.getElementById("dan-inspector-prepaint")?.remove();
        localStorage.setItem(RESET_FLAG, "1");
      }
    } catch {
      /* ignore */
    }

    // クライアント共有ドメインでは PWA Service Worker を unregister し、
    // CacheStorage を全クリアして「古いHP状態が残る」現象を防ぐ。
    try {
      if (
        typeof navigator !== "undefined" &&
        "serviceWorker" in navigator &&
        window.location.hostname.startsWith("kittoku")
      ) {
        navigator.serviceWorker.getRegistrations().then((regs) => {
          regs.forEach((r) => r.unregister());
        });
        if ("caches" in window) {
          caches.keys().then((keys) => {
            keys.forEach((k) => caches.delete(k));
          });
        }
      }
    } catch {
      /* ignore */
    }

    const html = document.documentElement;
    const body = document.body;
    const prevClass = html.className;
    const prevColorScheme = html.style.colorScheme;
    const prevHtmlOverflow = html.style.overflow;
    const prevBodyOverflow = body.style.overflow;
    const prevBodyHeight = body.style.height;
    const prevHtmlHeight = html.style.height;

    html.classList.remove("dark");
    html.style.colorScheme = "light";
    html.style.overflow = "auto";
    html.style.height = "auto";
    body.style.overflow = "auto";
    body.style.height = "auto";

    return () => {
      html.className = prevClass;
      html.style.colorScheme = prevColorScheme;
      html.style.overflow = prevHtmlOverflow;
      html.style.height = prevHtmlHeight;
      body.style.overflow = prevBodyOverflow;
      body.style.height = prevBodyHeight;
    };
  }, []);

  return (
    <>
      <style>{`
        .theme-yoshikawa {
          --background: oklch(0.99 0.003 240);
          --foreground: oklch(0.22 0.03 250);
          --card: #ffffff;
          --card-foreground: oklch(0.22 0.03 250);
          --popover: #ffffff;
          --popover-foreground: oklch(0.22 0.03 250);
          --primary: oklch(0.32 0.14 255);
          --primary-foreground: #ffffff;
          --secondary: oklch(0.96 0.005 250);
          --secondary-foreground: oklch(0.26 0.04 250);
          --muted: oklch(0.96 0.005 250);
          --muted-foreground: oklch(0.5 0.02 250);
          --accent: oklch(0.93 0.02 250);
          --accent-foreground: oklch(0.22 0.03 250);
          --destructive: oklch(0.58 0.21 27);
          --border: oklch(0.92 0.01 250);
          --input: oklch(0.92 0.01 250);
          --ring: oklch(0.32 0.14 255 / 0.5);
          --radius: 0.375rem;

          --yk-navy: oklch(0.32 0.14 255);
          --yk-navy-dark: oklch(0.22 0.12 255);
          --yk-gold: oklch(0.82 0.17 85);
          --yk-gold-dark: oklch(0.7 0.18 80);
          --yk-steel: oklch(0.45 0.02 250);

          background-color: var(--background);
          color: var(--foreground);
          font-family: "Noto Sans JP", "Hiragino Kaku Gothic ProN", "Yu Gothic", "Meiryo", sans-serif;
          -webkit-font-smoothing: antialiased;
          min-height: 100vh;
        }
        .theme-yoshikawa h1, .theme-yoshikawa h2, .theme-yoshikawa h3, .theme-yoshikawa .font-headline {
          font-family: "Zen Kaku Gothic New", "Noto Sans JP", sans-serif;
          letter-spacing: -0.01em;
        }
        .theme-yoshikawa .font-mono-data {
          font-family: "Roboto Mono", "SFMono-Regular", Menlo, monospace;
          font-feature-settings: "tnum" 1;
        }
        .theme-yoshikawa .font-eyebrow {
          font-family: "Space Grotesk", sans-serif;
          text-transform: uppercase;
          letter-spacing: 0.18em;
        }
      `}</style>
      <link
        rel="stylesheet"
        href="https://fonts.googleapis.com/css2?family=Zen+Kaku+Gothic+New:wght@500;700;900&family=Noto+Sans+JP:wght@400;500;700&family=Roboto+Mono:wght@400;500&family=Space+Grotesk:wght@500&display=swap"
      />
      <div className="theme-yoshikawa">{children}</div>
    </>
  );
}
