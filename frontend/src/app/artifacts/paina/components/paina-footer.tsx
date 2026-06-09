"use client";

import * as React from "react";
import { ArtifactLink as Link } from "@/components/artifacts/artifact-link";
import { useLang } from "./lang-context";

export function PainaFooter() {
  const { lang } = useLang();
  const ja = lang === "ja";

  return (
    <footer className="mt-32 border-t border-[var(--paina-border)] bg-[var(--paina-bg)]">
      <div className="mx-auto max-w-[1180px] px-6 py-16 md:px-10 md:py-20">
        <div className="flex flex-col gap-12 md:flex-row md:items-start md:justify-between">
          <div className="max-w-sm">
            <img
              src="/paina/logo.png"
              alt="株式会社パイナ PAINA"
              className="h-[20px] w-auto"
            />
            <p className="lead mt-6 text-[14px] leading-[2]">
              {ja
                ? "人とともに働くAIエージェント Done（ダン）を開発しています。"
                : "Developing Done — an AI agent that works alongside people."}
            </p>
          </div>

          <nav className="flex gap-16">
            <div className="flex flex-col gap-3">
              <span className="font-label text-[11px] uppercase tracking-[0.24em] text-[var(--paina-faint)]">
                Site
              </span>
              <Link href="/artifacts/paina" className="link-underline text-[14px]">
                {ja ? "ホーム" : "Home"}
              </Link>
              <Link
                href="/artifacts/paina/business"
                className="link-underline text-[14px]"
              >
                {ja ? "パイナについて" : "About"}
              </Link>
              <Link
                href="/artifacts/paina/contact"
                className="link-underline text-[14px]"
              >
                {ja ? "問い合わせ" : "Contact"}
              </Link>
            </div>
            <div className="flex flex-col gap-3">
              <span className="font-label text-[11px] uppercase tracking-[0.24em] text-[var(--paina-faint)]">
                Contact
              </span>
              <a
                href="mailto:shub6923@gmail.com"
                className="link-underline text-[14px]"
              >
                shub6923@gmail.com
              </a>
            </div>
          </nav>
        </div>

        <div className="mt-16 flex flex-col gap-2 border-t border-[var(--paina-border)] pt-7 md:flex-row md:items-center md:justify-between">
          <span className="font-label text-[11px] tracking-wide text-[var(--paina-faint)]">
            © {new Date().getFullYear()} 株式会社パイナ — PAINA Inc.
          </span>
          <span className="font-en text-[12px] italic text-[var(--paina-faint)]">
            Building AI that works alongside people.
          </span>
        </div>
      </div>
    </footer>
  );
}
