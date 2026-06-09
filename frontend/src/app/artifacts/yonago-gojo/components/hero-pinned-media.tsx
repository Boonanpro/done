"use client";

import * as React from "react";

/**
 * ヒーローの背景映像を画面に「完全固定」する（position: fixed）。
 * スクロールしても映像は一切動かず・サイズも変わらず、上のロゴ/バッジ/文字だけが流れる。
 * ヒーローを抜けると、後続セクション（不透明背景）が自然にこの映像を覆い隠す。
 * ※ この環境では position:sticky は不安定だが position:fixed は安定動作する。
 */
export function HeroPinnedMedia() {
  return (
    <div className="fixed inset-0 z-0 h-[100svh] w-full overflow-hidden">
      {/* PC 映像 */}
      <video
        src="/yonago-gojo/hero-pc.mp4"
        poster="/yonago-gojo/hero-poster.jpg"
        autoPlay
        loop
        muted
        playsInline
        preload="metadata"
        aria-label="五条の板場のようす"
        className="absolute inset-0 hidden h-full w-full object-cover sm:block"
        style={{ filter: "brightness(0.62) saturate(1.05)" }}
      />
      {/* モバイル映像 */}
      <video
        src="/yonago-gojo/hero-mobile.mp4"
        poster="/yonago-gojo/hero-poster.jpg"
        autoPlay
        loop
        muted
        playsInline
        preload="metadata"
        aria-hidden
        className="absolute inset-0 h-full w-full object-cover sm:hidden"
        style={{ filter: "brightness(0.58) saturate(1.05)" }}
      />
      {/* 可読性のためのグラデーション（下を濃く・中央〜上は映像を活かす） */}
      <div className="absolute inset-0 bg-gradient-to-t from-[var(--gojo-sumi)] via-[var(--gojo-sumi)]/25 to-[var(--gojo-sumi)]/55" />
      <div className="absolute inset-0 bg-gradient-to-r from-[var(--gojo-sumi)]/65 via-transparent to-transparent" />
    </div>
  );
}
