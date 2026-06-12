"use client";

import * as React from "react";
import Image from "next/image";
import { Instagram, Menu, X } from "lucide-react";

const INSTAGRAM_URL = "https://www.instagram.com/yonago_gojo/";

const NAV = [
  { label: "五条について", href: "#about" },
  { label: "お品書き", href: "#menu" },
  { label: "店内", href: "#interior" },
  { label: "アクセス", href: "#access" },
];

export function CompNav() {
  const [scrolled, setScrolled] = React.useState(false);
  const [open, setOpen] = React.useState(false);

  React.useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 40);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const solid = scrolled || open;

  return (
    <>
      <header
        className={`fixed inset-x-0 top-0 z-50 transition-colors duration-300 ${
          solid
            ? "border-b border-border/50 bg-background/90 backdrop-blur-md"
            : "bg-gradient-to-b from-black/55 to-transparent"
        }`}
      >
        <div className="mx-auto flex max-w-7xl items-center justify-between px-5 py-3 sm:px-8">
          {/* ロゴ */}
          <a href="#top" className="flex items-center gap-3" onClick={() => setOpen(false)}>
            <span className="relative h-9 w-9 overflow-hidden rounded-full bg-white/90 ring-1 ring-white/30 sm:h-10 sm:w-10">
              <Image
                src="/yonago-gojo/logo.jpg"
                alt="OBANZAI bar 五条 ロゴ"
                fill
                className="object-cover"
                sizes="40px"
              />
            </span>
            <span className="leading-tight">
              <span className="block font-headline text-[15px] text-white sm:text-base">
                おばんざいバー 五条
              </span>
              <span className="font-en block text-[9px] tracking-[0.24em] text-white/70 sm:text-[10px]">
                OBANZAI bar GOJO · 米子
              </span>
            </span>
          </a>

          {/* デスクトップ・中央ナビ */}
          <nav className="hidden items-center gap-9 md:flex">
            {NAV.map((n) => (
              <a
                key={n.href}
                href={n.href}
                className="font-label text-sm text-white/85 transition-colors hover:text-primary"
              >
                {n.label}
              </a>
            ))}
          </nav>

          {/* 予約ボタン（デスクトップ） */}
          <a
            href={INSTAGRAM_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="hidden items-center gap-2 rounded-full bg-primary px-5 py-2 font-label text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 md:inline-flex"
          >
            <Instagram className="h-4 w-4" />
            ご予約・お問い合わせ
          </a>

          {/* モバイル・メニューボタン */}
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="flex h-9 w-9 items-center justify-center rounded-full bg-white/10 text-white ring-1 ring-white/20 md:hidden"
            aria-label={open ? "メニューを閉じる" : "メニューを開く"}
          >
            {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>
      </header>

      {/* モバイル・メニュー */}
      {open && (
        <div className="fixed inset-0 top-[56px] z-40 bg-background/98 px-6 py-8 backdrop-blur md:hidden">
          <nav className="flex flex-col divide-y divide-border/50">
            {NAV.map((n) => (
              <a
                key={n.href}
                href={n.href}
                onClick={() => setOpen(false)}
                className="py-4 font-headline text-xl text-foreground"
              >
                {n.label}
              </a>
            ))}
          </nav>
          <a
            href={INSTAGRAM_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-8 inline-flex w-full items-center justify-center gap-2 rounded-full bg-primary px-5 py-3 font-label font-medium text-primary-foreground"
          >
            <Instagram className="h-4 w-4" />
            ご予約・お問い合わせはDMで
          </a>
        </div>
      )}

      {/* モバイル下部CTA */}
      <a
        href={INSTAGRAM_URL}
        target="_blank"
        rel="noopener noreferrer"
        className="fixed inset-x-0 bottom-0 z-40 flex items-center justify-center gap-2 border-t border-primary/40 bg-primary py-3.5 font-label text-sm font-medium text-primary-foreground md:hidden"
      >
        <Instagram className="h-4 w-4" />
        ご予約・お問い合わせはDMで
      </a>
    </>
  );
}
