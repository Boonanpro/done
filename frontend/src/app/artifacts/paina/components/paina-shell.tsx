"use client";

import * as React from "react";
import { PainaNav } from "./paina-nav";
import { PainaFooter } from "./paina-footer";

/**
 * 株式会社パイナ サイト共通シェル。
 * - ライト基調の warm ink テーマを CSS 変数で定義
 * - 見出し: Noto Serif JP / Fraunces（思索的なマニフェスト調）
 * - 本文: Noto Sans JP / ラベル・EN: Space Grotesk
 */
export function PainaShell({ children }: { children: React.ReactNode }) {
  React.useEffect(() => {
    const html = document.documentElement;
    const prev = html.style.colorScheme;
    html.style.colorScheme = "light";
    return () => {
      html.style.colorScheme = prev;
    };
  }, []);

  return (
    <>
      <link
        rel="stylesheet"
        href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,500;1,9..144,400&family=Space+Grotesk:wght@400;500;600&family=Noto+Sans+JP:wght@300;400;500;700&family=Noto+Serif+JP:wght@400;500;600&display=swap"
      />
      <style>{`
        .theme-paina {
          --paina-bg: #faf9f7;
          --paina-bg-soft: #f3f1ec;
          --paina-fg: #1a1712;
          --paina-muted: #6f685c;
          --paina-faint: #9b9486;
          --paina-border: #e6e2d9;
          --paina-border-strong: #d6d0c4;
          --paina-gold: #a8842f;
          --paina-gold-soft: #f0e7d2;

          background-color: var(--paina-bg);
          color: var(--paina-fg);
          font-family: "Noto Sans JP", "Hiragino Kaku Gothic ProN", "Yu Gothic", sans-serif;
          font-weight: 400;
          -webkit-font-smoothing: antialiased;
          text-rendering: optimizeLegibility;
          min-height: 100vh;
        }
        .theme-paina ::selection { background: var(--paina-gold-soft); }

        .theme-paina .font-serif-jp {
          font-family: "Noto Serif JP", "Hiragino Mincho ProN", serif;
          font-weight: 500;
        }
        .theme-paina .font-en {
          font-family: "Fraunces", "Noto Serif JP", serif;
          font-weight: 400;
        }
        .theme-paina .font-label {
          font-family: "Space Grotesk", "Noto Sans JP", sans-serif;
        }
        .theme-paina .lead {
          color: var(--paina-muted);
          line-height: 2.1;
          font-weight: 400;
        }
        .theme-paina .kicker {
          font-family: "Space Grotesk", sans-serif;
          font-size: 11px;
          letter-spacing: 0.32em;
          text-transform: uppercase;
          color: var(--paina-gold);
        }
        .theme-paina .hairline { background: var(--paina-border); }
        .theme-paina .link-underline {
          background-image: linear-gradient(var(--paina-fg), var(--paina-fg));
          background-size: 0% 1px;
          background-repeat: no-repeat;
          background-position: 0 100%;
          transition: background-size 0.4s cubic-bezier(0.22,1,0.36,1);
          padding-bottom: 2px;
        }
        .theme-paina .link-underline:hover { background-size: 100% 1px; }

        @keyframes paina-fade-up {
          from { opacity: 0; transform: translateY(16px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @media (prefers-reduced-motion: reduce) {
          .theme-paina [data-reveal] { opacity: 1 !important; transform: none !important; }
        }
      `}</style>
      <div className="theme-paina">
        <PainaNav />
        <main>{children}</main>
        <PainaFooter />
      </div>
    </>
  );
}
