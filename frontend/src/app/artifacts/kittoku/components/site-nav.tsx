"use client";

import * as React from "react";
import Link from "next/link";
import { Phone, Menu, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Logo } from "./logo";

const NAV_ITEMS = [
  { label: "ホーム", href: "/artifacts/kittoku" },
  { label: "事業・サービス", href: "/artifacts/kittoku/services" },
  { label: "会社情報", href: "/artifacts/kittoku/company" },
  { label: "採用情報", href: "/artifacts/kittoku/careers" },
];

export function SiteNav() {
  const [scrolled, setScrolled] = React.useState(false);
  const [open, setOpen] = React.useState(false);

  React.useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 10);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <div
      className={cn(
        "w-full transition-shadow",
        scrolled ? "shadow-sm" : "shadow-none",
      )}
    >
      <div className="mx-auto max-w-7xl px-4 sm:px-6">
        <div className="flex h-16 sm:h-20 items-center justify-between gap-4">
          <Logo size="md" />
          <nav className="hidden lg:flex items-center gap-7">
            {NAV_ITEMS.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className="text-sm font-medium text-[var(--yk-steel)] hover:text-[var(--yk-navy)] transition-colors"
              >
                {item.label}
              </Link>
            ))}
          </nav>
          <div className="flex items-center gap-3">
            <a
              href="tel:0859-27-4885"
              className="hidden sm:flex items-center gap-2 text-[var(--yk-navy)] hover:text-[var(--yk-navy-dark)] transition-colors"
            >
              <Phone className="h-4 w-4" />
              <span className="font-mono-data text-base font-bold">
                0859-27-4885
              </span>
            </a>
            <Button
              asChild
              className="hidden sm:inline-flex bg-[var(--yk-navy)] hover:bg-[var(--yk-navy-dark)] text-white rounded-sm"
            >
              <Link href="/artifacts/kittoku/contact">お問い合わせ</Link>
            </Button>
            <button
              type="button"
              className="lg:hidden inline-flex h-10 w-10 items-center justify-center rounded-sm text-[var(--yk-navy)]"
              onClick={() => setOpen((v) => !v)}
              aria-label="メニュー"
            >
              {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
            </button>
          </div>
        </div>
      </div>
      {open && (
        <div className="lg:hidden border-t border-border bg-white">
          <div className="mx-auto max-w-7xl px-4 py-4 flex flex-col gap-1">
            {NAV_ITEMS.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className="py-3 px-2 text-sm font-medium text-[var(--yk-navy)] hover:bg-[var(--yk-navy)]/5 rounded-sm"
                onClick={() => setOpen(false)}
              >
                {item.label}
              </Link>
            ))}
            <a
              href="tel:0859-27-4885"
              className="py-3 px-2 text-sm font-medium text-[var(--yk-navy)] border-t border-border mt-2 flex items-center gap-2"
            >
              <Phone className="h-4 w-4" />
              <span className="font-mono-data">0859-27-4885</span>
            </a>
            <Link
              href="/artifacts/kittoku/contact"
              className="mt-2 bg-[var(--yk-navy)] text-white py-3 text-center rounded-sm text-sm font-bold"
              onClick={() => setOpen(false)}
            >
              お問い合わせ
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
