"use client";

import * as React from "react";
import { ArtifactLink as Link } from "@/components/artifacts/artifact-link";
import { ArrowUpRight } from "lucide-react";
import { Reveal } from "../components/reveal";
import { WaitlistForm } from "../components/waitlist-form";

type CaseItem = {
  client: string;
  reading: string;
  summary: string;
  tags: string[];
  thumb: string;
  href?: string;
};

const HP_CASES: CaseItem[] = [
  {
    client: "吉川特装",
    reading: "Yoshikawa Tokuso",
    summary:
      "特装車輌の架装・整備を手がける事業の信頼を、力強いビジュアルと実績の見せ方で伝えるコーポレートサイトを制作。",
    tags: ["コーポレートサイト", "ブランディング"],
    thumb: "/paina/case-kittoku.png",
    href: "https://kittoku.vercel.app",
  },
  {
    client: "OBANZAI bar 五条",
    reading: "Gojo, Yonago",
    summary:
      "夜の隠れ家のような世界観を、温かい暗色と縦書き、手書き風のあしらいで表現した飲食店サイトを制作。",
    tags: ["店舗サイト", "ブランディング"],
    thumb: "/paina/case-gojo.png",
    href: "https://yonago-gojo-done.vercel.app",
  },
];

const DX_CASES: CaseItem[] = [
  {
    client: "スタイルアップ",
    reading: "Style Up",
    summary:
      "美容サロンの予約サイトへのスタイル投稿を自動化。手作業だった掲載運用を仕組みに変え、更新の手間を大きく削減。",
    tags: ["業務自動化", "ツール開発"],
    thumb: "/paina/case-styleup.png",
  },
  {
    client: "電管ナレッジ",
    reading: "Denkan Knowledge",
    summary:
      "電気主任技術者の現場知識を蓄積・検索できるナレッジ基盤を構築。属人化していた情報を、誰でも引ける形に整理。",
    tags: ["ナレッジ基盤", "DX支援"],
    thumb: "/paina/case-denki.png",
  },
];

function CaseCard({ c, index }: { c: CaseItem; index: number }) {
  const inner = (
    <div className="group flex h-full flex-col overflow-hidden rounded-2xl border border-[var(--paina-border)] bg-[var(--paina-bg)] transition-colors hover:border-[var(--paina-border-strong)]">
      {/* サムネイル */}
      <div className="relative aspect-[16/10] overflow-hidden border-b border-[var(--paina-border)] bg-[var(--paina-bg-soft)]">
        <img
          src={c.thumb}
          alt={`${c.client} の実績サムネイル`}
          loading="lazy"
          className="h-full w-full object-cover object-top transition-transform duration-700 group-hover:scale-[1.03]"
        />
        {c.href && (
          <span className="absolute right-3 top-3 flex h-8 w-8 items-center justify-center rounded-full bg-[var(--paina-bg)]/90 text-[var(--paina-fg)] shadow-sm backdrop-blur">
            <ArrowUpRight className="h-4 w-4" />
          </span>
        )}
      </div>

      {/* 本文 */}
      <div className="flex flex-1 flex-col justify-between p-7 md:p-8">
        <div>
          <h4 className="font-serif-jp text-[1.35rem] leading-[1.5] text-[var(--paina-fg)]">
            {c.client}
          </h4>
          <p className="font-en mt-1 text-[13px] italic text-[var(--paina-faint)]">
            {c.reading}
          </p>
          <p className="lead mt-5 text-[15px] leading-[2]">{c.summary}</p>
        </div>
        <div className="mt-7 flex flex-wrap gap-2">
          {c.tags.map((t) => (
            <span
              key={t}
              className="font-label rounded-full border border-[var(--paina-border)] px-3 py-1 text-[11px] tracking-wide text-[var(--paina-muted)]"
            >
              {t}
            </span>
          ))}
        </div>
      </div>
    </div>
  );

  return (
    <Reveal delay={index * 90}>
      {c.href ? (
        <a href={c.href} target="_blank" rel="noopener noreferrer" className="block h-full">
          {inner}
        </a>
      ) : (
        inner
      )}
    </Reveal>
  );
}

export default function PainaBusiness() {
  return (
    <div>
      {/* ===== Hero ===== */}
      <section className="px-6 pb-16 pt-36 md:px-10 md:pb-20 md:pt-48">
        <div className="mx-auto max-w-[1180px]">
          <Reveal>
            <p className="kicker">Business</p>
          </Reveal>
          <Reveal delay={120}>
            <h1 className="font-serif-jp mt-7 text-[2.4rem] leading-[1.32] text-[var(--paina-fg)] md:text-[3.4rem]">
              事業内容
            </h1>
          </Reveal>
          <Reveal delay={220}>
            <p className="lead mt-8 max-w-[54ch] text-[16px] md:text-[17px]">
              私たちの中心はAIエージェント「Done（ダン）」の開発です。
              そこで培った技術と視点を、ホームページ制作とDX支援という形で、
              いまの事業者の課題解決にも還元しています。
            </p>
          </Reveal>
        </div>
      </section>

      {/* ===== 01 Done ===== */}
      <section id="done" className="scroll-mt-24 px-6 py-20 md:px-10 md:py-28">
        <div className="mx-auto max-w-[1180px]">
          <div className="overflow-hidden rounded-3xl bg-[var(--paina-fg)] px-8 py-14 text-[var(--paina-bg)] md:px-16 md:py-20">
            <Reveal>
              <div className="flex items-start gap-5 sm:gap-6">
                <img
                  src="/paina/done-icon.png"
                  alt="ダン（Done）アプリアイコン"
                  className="h-16 w-16 shrink-0 rounded-[18px] shadow-lg shadow-black/20 sm:h-[76px] sm:w-[76px]"
                />
                <div>
                  <div className="flex flex-wrap items-center gap-3">
                    <span className="font-en text-[1.4rem] italic text-[var(--paina-gold)]">01</span>
                    <span className="font-label rounded-full border border-[var(--paina-gold-soft)]/40 px-3 py-1 text-[11px] uppercase tracking-[0.24em] text-[var(--paina-gold-soft)]">
                      Product — Coming soon
                    </span>
                  </div>
                  <h2 className="font-serif-jp mt-4 max-w-[20ch] text-[2rem] leading-[1.4] md:text-[2.6rem]">
                    Done（ダン）の開発
                  </h2>
                </div>
              </div>
              <p className="mt-7 max-w-[58ch] text-[16px] leading-[2.1] text-[var(--paina-bg)]/80">
                「やっておいて」が、本当に終わっている。
                調べ、判断し、操作し、結果を確かめて直すまでを自分で完結する、
                自律的なAIエージェントです。いまは私たち自身の事業運営に使いながら、
                毎日鍛えています。第三者への提供は現在準備中です。
              </p>
            </Reveal>

            <Reveal delay={120}>
              <div className="mt-10 grid gap-6 border-t border-[var(--paina-bg)]/15 pt-10 sm:grid-cols-3">
                {[
                  ["自律実行", "提案で止まらず、実務を最後までやり切る。"],
                  ["記憶と学習", "あなたの文脈を覚え、使うほど馴染む。"],
                  ["安全な境界", "任せる範囲を設計し、安心して預けられる。"],
                ].map(([t, d]) => (
                  <div key={t}>
                    <h3 className="font-serif-jp text-[1.1rem] text-[var(--paina-bg)]">{t}</h3>
                    <p className="mt-2 text-[14px] leading-[1.9] text-[var(--paina-bg)]/65">{d}</p>
                  </div>
                ))}
              </div>
            </Reveal>

            <Reveal delay={200}>
              <div className="mt-12">
                <p className="font-label text-[12px] uppercase tracking-[0.24em] text-[var(--paina-gold-soft)]">
                  Waiting list
                </p>
                <p className="mt-4 max-w-[50ch] text-[15px] leading-[2] text-[var(--paina-bg)]/80">
                  提供開始の際に、先行してご案内します。下記よりご登録ください。
                </p>
                <div className="mt-6 max-w-[640px]">
                  <WaitlistForm tone="dark" />
                </div>
              </div>
            </Reveal>
          </div>
        </div>
      </section>

      {/* ===== 02 HP制作 ===== */}
      <section className="px-6 py-16 md:px-10 md:py-24">
        <div className="mx-auto max-w-[1180px]">
          <Reveal>
            <div className="flex items-center gap-4">
              <span className="font-en text-[1.4rem] italic text-[var(--paina-gold)]">02</span>
              <span className="font-label text-[11px] uppercase tracking-[0.24em] text-[var(--paina-gold)]">
                Service
              </span>
            </div>
            <h2 className="font-serif-jp mt-6 text-[1.9rem] leading-[1.5] text-[var(--paina-fg)] md:text-[2.6rem]">
              ホームページ制作
            </h2>
            <p className="lead mt-6 max-w-[54ch] text-[16px]">
              事業の世界観と信頼を、言葉とデザインで形にします。
              テンプレートに当てはめるのではなく、何を伝えたいかから設計します。
            </p>
          </Reveal>

          <div className="mt-12 grid gap-6 md:grid-cols-2">
            {HP_CASES.map((c, i) => (
              <CaseCard key={c.client} c={c} index={i} />
            ))}
          </div>
        </div>
      </section>

      {/* ===== 03 DX支援 ===== */}
      <section className="bg-[var(--paina-bg-soft)] px-6 py-16 md:px-10 md:py-24">
        <div className="mx-auto max-w-[1180px]">
          <Reveal>
            <div className="flex items-center gap-4">
              <span className="font-en text-[1.4rem] italic text-[var(--paina-gold)]">03</span>
              <span className="font-label text-[11px] uppercase tracking-[0.24em] text-[var(--paina-gold)]">
                Service
              </span>
            </div>
            <h2 className="font-serif-jp mt-6 text-[1.9rem] leading-[1.5] text-[var(--paina-fg)] md:text-[2.6rem]">
              ソフトウェア・ツールによるDX支援
            </h2>
            <p className="lead mt-6 max-w-[54ch] text-[16px]">
              現場の手作業を、仕組みに変える。業務に合わせた道具をつくり、
              繰り返しの負担と属人化を減らします。
            </p>
          </Reveal>

          <div className="mt-12 grid gap-6 md:grid-cols-2">
            {DX_CASES.map((c, i) => (
              <CaseCard key={c.client} c={c} index={i} />
            ))}
          </div>
        </div>
      </section>

      {/* ===== Final CTA ===== */}
      <section className="px-6 py-24 md:px-10 md:py-32">
        <div className="mx-auto max-w-[1180px] text-center">
          <Reveal>
            <h2 className="font-serif-jp text-[1.8rem] leading-[1.55] text-[var(--paina-fg)] md:text-[2.4rem]">
              制作・DX支援のご相談はお気軽に。
            </h2>
            <p className="lead mx-auto mt-6 max-w-[48ch] text-[16px]">
              小さな自動化から、サイト制作まで。まずはお話を聞かせてください。
            </p>
            <Link
              href="/artifacts/paina/contact"
              className="font-label mt-10 inline-flex items-center gap-2 rounded-full bg-[var(--paina-fg)] px-8 py-3.5 text-[13px] tracking-wide text-[var(--paina-bg)] transition-opacity hover:opacity-90"
            >
              問い合わせる
              <ArrowUpRight className="h-4 w-4" />
            </Link>
          </Reveal>
        </div>
      </section>
    </div>
  );
}
