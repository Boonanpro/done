"use client";

import * as React from "react";
import { usePathname } from "next/navigation";
import { ArtifactLink as Link } from "@/components/artifacts/artifact-link";
import { Menu, X } from "lucide-react";

const NAV = [
  { label: "事業内容", en: "Business", href: "/artifacts/paina/business" },
  { label: "問い合わせ", en: "Contact", href: "/artifacts/paina/contact" },
];

function isActive(pathname: string, href: string) {
  const norm = (s: string) => s.replace(/^\/(artifacts|preview)/, "").replace(/\/$/, "");
  return norm(pathname) === norm(href);
}

export function PainaNav() {
  const pathname = usePathname() || "";
  const [open, setOpen] = React.useState(false);
  const [scrolled, setScrolled] = React.useState(false);

  React.useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

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
          <Link href="/artifacts/paina" className="flex items-center" onClick={() => setOpen(false)}>
            <img
              src="/paina/logo.png"
              alt="株式会社パイナ PAINA"
              className="h-[18px] w-auto md:h-[22px]"
            />
          </Link>

          <nav className="hidden items-center gap-10 md:flex">
            {NAV.map((n) => (
              <Link
                key={n.href}
                href={n.href}
                className="group flex flex-col items-start"
              >
                <span
                  className={`font-label text-[13px] tracking-wide transition-colors ${
                    isActive(pathname, n.href)
                      ? "text-[var(--paina-fg)]"
                      : "text-[var(--paina-muted)] group-hover:text-[var(--paina-fg)]"
                  }`}
                >
                  {n.label}
                </span>
              </Link>
            ))}
            <Link
              href="/artifacts/paina/business#done"
              className="font-label rounded-full border border-[var(--paina-border-strong)] px-5 py-2 text-[12px] tracking-wide text-[var(--paina-fg)] transition-colors hover:border-[var(--paina-fg)]"
            >
              ダンを待つ
            </Link>
          </nav>

          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="flex h-9 w-9 items-center justify-center text-[var(--paina-fg)] md:hidden"
            aria-label={open ? "メニューを閉じる" : "メニューを開く"}
          >
            {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>
      </header>

      {/* モバイルメニュー */}
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
                  {n.label}
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
            ダンを待つ
          </Link>
        </div>
      )}
    </>
  );
}
