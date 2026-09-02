"use client";

import * as React from "react";

/**
 * 足元パネルヒーターLP専用テーマシェル（クライアント側）。
 * - ルート layout.tsx が固定している overflow:hidden を解除してスクロール可能にする
 * - CSS変数を「在宅ワークの朝の机／冷えた白い床と、足元だけの熾火」の配色に上書きする
 *
 * 配色は artifacts/oku-yukadanbou（置く床暖房）と同じブランド世界を踏襲する。
 * 日本の暖房・生活家電ブランドは例外なく明るい地で、温度感は写真の光で出す。
 * 暗い画面は「冷たい・安い」に振れるため地は明るく取り、熾火色は CTA と数値だけに絞る。
 * 地は前作の生成りよりわずかに白へ寄せ、机上の空気に合わせている。
 */
export function ThemeShell({ children }: { children: React.ReactNode }) {
  React.useEffect(() => {
    const html = document.documentElement;
    const body = document.body;
    const prevHtmlOverflow = html.style.overflow;
    const prevBodyOverflow = body.style.overflow;
    const prevBodyHeight = body.style.height;
    const prevHtmlHeight = html.style.height;

    html.style.overflow = "auto";
    html.style.height = "auto";
    body.style.overflow = "auto";
    body.style.height = "auto";

    return () => {
      html.style.overflow = prevHtmlOverflow;
      html.style.height = prevHtmlHeight;
      body.style.overflow = prevBodyOverflow;
      body.style.height = prevBodyHeight;
    };
  }, []);

  return (
    <>
      <style>{`
        .theme-ashimoto {
          /* Neutral 88% — 朝の机上の白 */
          --background: oklch(0.976 0.005 92);
          --card: oklch(1 0 0);
          --popover: oklch(1 0 0);
          --secondary: oklch(0.950 0.006 90);
          --muted: oklch(0.950 0.006 90);
          --accent: oklch(0.932 0.008 88);

          /* Primary — 炭 */
          --foreground: oklch(0.215 0.012 55);
          --card-foreground: oklch(0.215 0.012 55);
          --popover-foreground: oklch(0.215 0.012 55);
          --secondary-foreground: oklch(0.245 0.012 55);
          --accent-foreground: oklch(0.245 0.012 55);

          /* Secondary — 補助・罫線 */
          --muted-foreground: oklch(0.505 0.014 62);
          --border: oklch(0.892 0.008 84);
          --input: oklch(0.892 0.008 84);

          /* Accent（最小面積） — 熾火 */
          --primary: oklch(0.565 0.168 41);
          --primary-foreground: oklch(0.985 0.006 80);
          --destructive: oklch(0.58 0.20 27);
          --ring: oklch(0.565 0.168 41 / 0.45);
          --radius: 0.25rem;

          --ah-ember: oklch(0.565 0.168 41);
          --ah-ember-soft: oklch(0.565 0.168 41 / 0.10);
          /* 冷えを示す青。温度スケールの寒い側にだけ使い、必ず熾火と対で出す */
          --ah-cold: oklch(0.52 0.085 245);
          --ah-cold-soft: oklch(0.52 0.085 245 / 0.12);

          background-color: var(--background);
          color: var(--foreground);
          font-family: "Noto Sans JP", "Hiragino Kaku Gothic ProN", "Yu Gothic", "Meiryo", sans-serif;
          -webkit-font-smoothing: antialiased;
          min-height: 100vh;
        }
        .theme-ashimoto h1,
        .theme-ashimoto h2,
        .theme-ashimoto h3,
        .theme-ashimoto .font-headline {
          font-family: "Zen Old Mincho", "Hiragino Mincho ProN", "Yu Mincho", serif;
          font-weight: 600;
          letter-spacing: 0.015em;
        }
        .theme-ashimoto .font-num {
          font-family: "Barlow Condensed", "Roboto Condensed", sans-serif;
          font-weight: 600;
          font-feature-settings: "tnum" 1;
          letter-spacing: 0.01em;
        }
        .theme-ashimoto .font-eyebrow {
          font-family: "Barlow Condensed", sans-serif;
          text-transform: uppercase;
          letter-spacing: 0.26em;
          font-weight: 600;
        }
        /* 足元だけに溜まる熱。明るい地の上なので極薄で当てる */
        .theme-ashimoto .warm-floor {
          background-image: radial-gradient(
            120% 80% at 50% 100%,
            oklch(0.565 0.168 41 / 0.12) 0%,
            oklch(0.565 0.168 41 / 0.04) 44%,
            transparent 74%
          );
        }
        /* ページ唯一の暗い全幅帯（安全セクション）。
           明るいページで1か所だけ暗くすると、そこで視線が止まる。 */
        .theme-ashimoto .ink-band {
          --ink: oklch(0.205 0.014 58);
          --ink-fg: oklch(0.965 0.010 82);
          --ink-fg-muted: oklch(0.80 0.014 80);
          --ink-fg-dim: oklch(0.72 0.014 80);
          --ink-border: oklch(0.32 0.014 60);
          background-color: var(--ink);
          color: var(--ink-fg);
        }
        .theme-ashimoto .ink-band .ink-heading { color: var(--ink-fg); }
        .theme-ashimoto .ink-band .ink-body { color: var(--ink-fg-muted); }
        .theme-ashimoto .ink-band .ink-note {
          color: var(--ink-fg-dim);
          border-color: var(--ink-border);
        }
      `}</style>
      <link
        rel="stylesheet"
        href="https://fonts.googleapis.com/css2?family=Zen+Old+Mincho:wght@400;500;600;700&family=Noto+Sans+JP:wght@400;500;700&family=Barlow+Condensed:wght@500;600;700&display=swap"
      />
      <div className="theme-ashimoto">{children}</div>
    </>
  );
}
