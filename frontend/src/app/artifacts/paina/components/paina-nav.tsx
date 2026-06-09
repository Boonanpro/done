"use client";

import * as React from "react";
import { usePathname } from "next/navigation";
import { ArtifactLink as Link } from "@/components/artifacts/artifact-link";
import { Menu, X } from "lucide-react";
import { useLang } from "./lang-context";

const NAV = [
  { ja: "パイナについて", en: "About", href: "/artifacts/paina/business" },
  { ja: "問い合わせ", en: "Contact", href: "/artifacts/paina/contact" },
];

function isActive(pathname: string, href: string) {
  const norm = (s: string) =>
    s.replace(/^\/(artifacts|preview)/, "").replace(/\/$/, "");
  return norm(pathname) === norm(href);
}

function LangToggle() {
  const { lang, setLang } = useLang();
  return (
    <div className="font-label flex items-center overflow-hidden rounded-full border border-[var(--paina-border-strong)] text-[11px] tracking-wide">
      {(["ja", "en"] as const).map((l) => (
        <button
          key={l}
          type="button"
          onClick={() => setLang(l)}
          className={`px-3 py-1.5 transition-colors ${
            lang === l
              ? "bg-[var(--paina-fg)] text-[var(--paina-bg)]"
              : "text-[var(--paina-muted)] hover:text-[var(--paina-fg)]"
          }`}
          aria-pressed={lang === l}
        >
          {l === "ja" ? "日本語" : "EN"}
        </button>
      ))}
    </div>
  );
}

export function PainaNav() {
  const pathname = usePathname() || "";
  const { lang } = useLang();
  const [open, setOpen] = React.useState(false);
  const [scrolled, setScrolled] = React.useState(false);

  React.useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const cta = lang === "ja" ? "ダンを待つ" : "Join the waitlist";

  return (
    <>
      <header
        className={`fixed inset-x-0 top-0 z-50 transition-colors duration-300 ${
          scrolled || open
            ? "bg-[var(--paina-bg)]/92 backdrop-blur-md border-b border-[var(--paina-border)]"
            : "bg-transparent"
        }`}
      >
        <div className="mx-auto flex max-w-[1180px] items-center justify-between px-6 py-4 md:px-10 md:py-5">
          <Link
            href="/artifacts/paina"
            className="flex items-center"
            onClick={() => setOpen(false)}
          >
            <img
              src="/paina/logo.png"
              alt="株式会社パイナ PAINA"
              className="h-[18px] w-auto md:h-[22px]"
            />
          </Link>

          <nav className="hidden items-center gap-9 md:flex">
            {NAV.map((n) => (
              <Link key={n.href} href={n.href} className="group flex flex-col">
                <span
                  className={`font-label text-[13px] tracking-wide transition-colors ${
                    isActive(pathname, n.href)
                      ? "text-[var(--paina-fg)]"
                      : "text-[var(--paina-muted)] group-hover:text-[var(--paina-fg)]"
                  }`}
                >
                  {lang === "ja" ? n.ja : n.en}
                </span>
              </Link>
            ))}
            <Link
              href="/artifacts/paina/business#done"
              className="font-label rounded-full border border-[var(--paina-border-strong)] px-5 py-2 text-[12px] tracking-wide text-[var(--paina-fg)] transition-colors hover:border-[var(--paina-fg)]"
            >
              {cta}
            </Link>
            <LangToggle />
          </nav>

          <div className="flex items-center gap-3 md:hidden">
            <LangToggle />
            <button
              type="button"
              onClick={() => setOpen((v) => !v)}
              className="flex h-9 w-9 items-center justify-center text-[var(--paina-fg)]"
              aria-label={open ? "close menu" : "open menu"}
            >
              {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
            </button>
          </div>
        </div>
      </header>

      {open && (
        <div className="fixed inset-0 top-[57px] z-40 bg-[var(--paina-bg)] px-7 py-8 md:hidden">
          <nav className="flex flex-col divide-y divide-[var(--paina-border)]">
            {NAV.map((n) => (
              <Link
                key={n.href}
                href={n.href}
                onClick={() => setOpen(false)}
                className="flex items-baseline justify-between py-5"
              >
                <span className="font-serif-jp text-xl text-[var(--paina-fg)]">
                  {lang === "ja" ? n.ja : n.en}
                </span>
                <span className="font-label text-[11px] uppercase tracking-[0.2em] text-[var(--paina-faint)]">
                  {n.en}
                </span>
              </Link>
            ))}
          </nav>
          <Link
            href="/artifacts/paina/business#done"
            onClick={() => setOpen(false)}
            className="font-label mt-8 flex items-center justify-center rounded-full border border-[var(--paina-fg)] px-6 py-3 text-sm tracking-wide"
          >
            {cta}
          </Link>
        </div>
      )}
    </>
  );
}
