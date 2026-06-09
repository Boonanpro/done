"use client";

import * as React from "react";
import { Instagram, Menu, X } from "lucide-react";

const INSTAGRAM_URL = "https://www.instagram.com/yonago_gojo/";

const NAV = [
  { label: "お品書き", en: "menu", href: "#menu" },
  { label: "こだわり", en: "craft", href: "#craft" },
  { label: "店内の風景", en: "gallery", href: "#gallery" },
  { label: "はじめて", en: "first visit", href: "#first" },
  { label: "アクセス", en: "access", href: "#access" },
];

function Logo({ size = 40 }: { size?: number }) {
  return (
    <span className="relative block" style={{ height: size, width: size }}>
      <img
        src="/yonago-gojo/logo-text.png"
        alt="OBANZAI bar 五条 ロゴ"
        className="h-full w-full object-contain"
      />
    </span>
  );
}

export function GojoNav() {
  const [open, setOpen] = React.useState(false);
  const [scrolled, setScrolled] = React.useState(false);

  React.useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <>
      {/* ===== Desktop: 左固定の縦ナビ ===== */}
      <aside className="fixed left-0 top-0 z-40 hidden h-screen w-[200px] flex-col justify-between bg-background/70 px-7 py-9 backdrop-blur-md lg:flex">
        <a href="#top" className="flex flex-col items-start gap-3">
          <Logo size={72} />
        </a>

        <nav className="flex flex-col gap-6">
          {NAV.map((n) => (
            <a key={n.href} href={n.href} className="group flex flex-col">
              <span className="font-label text-[15px] text-foreground/85 transition-colors group-hover:text-primary">
                {n.label}
              </span>
              <span className="font-en text-[10px] uppercase tracking-[0.2em] text-muted-foreground/70">
                {n.en}
              </span>
            </a>
          ))}
        </nav>

        <div className="font-en text-[10px] uppercase tracking-[0.22em] text-muted-foreground/60">
          Yonago · Tottori
        </div>
      </aside>

      {/* ===== Desktop: 右端の縦書き予約タブ ===== */}
      <a
        href={INSTAGRAM_URL}
        target="_blank"
        rel="noopener noreferrer"
        className="fixed right-0 top-1/2 z-40 hidden -translate-y-1/2 items-center gap-6 rounded-l-xl bg-primary text-primary-foreground shadow-lg shadow-black/30 transition-colors hover:bg-primary/90 lg:flex"
        style={{
          writingMode: "vertical-rl",
          paddingTop: "4rem",
          paddingBottom: "4rem",
          paddingLeft: "1.25rem",
          paddingRight: "1rem",
        }}
        aria-label="Instagramでご予約・お問い合わせ"
      >
        <Instagram className="h-4 w-4 rotate-90" />
        <span className="font-label text-sm font-medium tracking-[0.18em]">
          ご予約・お問い合わせ
        </span>
        <span className="font-en text-[10px] uppercase tracking-[0.2em] opacity-70">
          reservation
        </span>
      </a>

      {/* ===== Mobile: 上部バー ===== */}
      <header
        className={`fixed inset-x-0 top-0 z-50 flex items-center justify-between px-4 py-2.5 transition-colors lg:hidden ${
          scrolled || open
            ? "bg-background/95 backdrop-blur"
            : "bg-gradient-to-b from-black/55 to-transparent"
        }`}
      >
        <a href="#top" className="flex items-center" onClick={() => setOpen(false)}>
          <Logo size={48} />
        </a>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex h-10 w-10 items-center justify-center text-white"
          aria-label={open ? "メニューを閉じる" : "メニューを開く"}
        >
          {open ? <X className="h-6 w-6" /> : <Menu className="h-6 w-6" />}
        </button>
      </header>

      {/* ===== Mobile: メニュー ===== */}
      {open && (
        <div className="fixed inset-0 top-[52px] z-40 bg-background/98 px-6 py-8 backdrop-blur lg:hidden">
          <nav className="flex flex-col">
            {NAV.map((n) => (
              <a
                key={n.href}
                href={n.href}
                onClick={() => setOpen(false)}
                className="flex items-baseline justify-between py-4"
              >
                <span className="font-headline text-xl text-foreground">{n.label}</span>
                <span className="font-en text-[11px] uppercase tracking-[0.2em] text-muted-foreground">
                  {n.en}
                </span>
              </a>
            ))}
          </nav>
        </div>
      )}

      {/* ===== Mobile: 下部固定CTA（予約のみ） ===== */}
      <a
        href={INSTAGRAM_URL}
        target="_blank"
        rel="noopener noreferrer"
        className="fixed inset-x-0 bottom-0 z-40 flex items-center justify-center gap-2 bg-primary py-3.5 font-label text-sm font-medium text-primary-foreground lg:hidden"
      >
        <Instagram className="h-4 w-4" />
        ご予約・お問い合わせ
      </a>
    </>
  );
}
