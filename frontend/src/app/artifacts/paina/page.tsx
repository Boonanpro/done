"use client";

import * as React from "react";
import { ArtifactLink as Link } from "@/components/artifacts/artifact-link";
import { ArrowUpRight } from "lucide-react";
import { Reveal } from "./components/reveal";
import { WaitlistForm } from "./components/waitlist-form";

const APPROACH = [
  {
    no: "01",
    title: "人の隣で働くこと",
    body: "私たちが目指すのは、人に代わる存在ではなく、人の隣で働く相棒です。判断は人が握り、面倒な実務はダンが引き受ける。その境界を丁寧に設計することが、信頼できるAIの出発点だと考えています。",
  },
  {
    no: "02",
    title: "最後までやり切ること",
    body: "「やっておいて」が、本当に終わっている。ダン（Done）という名前には、提案で止まらず、調べ、操作し、結果を見て直すまでを一人で完結させるという約束を込めています。",
  },
  {
    no: "03",
    title: "土台を正しくつくること",
    body: "派手な機能より、壊れない土台。記憶、認証、安全に止まる仕組み。地味でも正しい順序で積み上げることが、長く使えるAIをつくる唯一の道だと信じています。",
  },
  {
    no: "04",
    title: "使いながら学ぶこと",
    body: "実際の現場で使い、つまずき、直す。私たちは自分たちの仕事をダン自身に任せながら開発しています。現実から逆算することでしか、本当に役立つAIは生まれません。",
  },
];

const BUSINESS = [
  {
    label: "Product",
    title: "Done（ダン）の開発",
    body: "自律的に働くAIエージェント。現在は自社で運用しながら磨いています。第三者への提供は coming soon。",
  },
  {
    label: "Service",
    title: "ホームページ制作",
    body: "事業の世界観と信頼を、言葉とデザインで形にします。",
  },
  {
    label: "Service",
    title: "ソフトウェア・ツールによるDX支援",
    body: "現場の手作業を、仕組みに変える。業務に合わせた道具を作ります。",
  },
];

export default function PainaHome() {
  return (
    <div>
      {/* ===== Hero ===== */}
      <section className="relative overflow-hidden px-6 pb-24 pt-36 md:px-10 md:pb-36 md:pt-48">
        <div
          className="pointer-events-none absolute -right-40 -top-24 h-[520px] w-[520px] rounded-full opacity-60"
          style={{
            background:
              "radial-gradient(circle, rgba(168,132,47,0.10) 0%, rgba(168,132,47,0) 68%)",
          }}
        />
        <div className="mx-auto max-w-[1180px]">
          <Reveal>
            <p className="kicker" data-edit-id="hero-kicker">
              PAINA — AI Agent Company
            </p>
          </Reveal>
          <Reveal delay={120}>
            <h1
              className="font-serif-jp mt-8 max-w-[16ch] text-[2.5rem] leading-[1.32] tracking-[0.005em] text-[var(--paina-fg)] sm:text-[3.4rem] md:text-[4.2rem] md:leading-[1.28]"
              data-edit-id="hero-headline"
            >
              人とともに働くAIを、
              <br />
              ひとつずつ。
            </h1>
          </Reveal>
          <Reveal delay={240}>
            <p
              className="lead mt-10 max-w-[52ch] text-[16px] md:text-[17px]"
              data-edit-id="hero-lead"
            >
              株式会社パイナは、自律的に動くAIエージェント「Done（ダン）」を開発しています。
              人に代わるのではなく、人の隣で実務をやり切る相棒として。
              私たちは、その考え方とつくり方をここに記します。
            </p>
          </Reveal>
          <Reveal delay={360}>
            <div className="mt-12 flex flex-wrap items-center gap-x-8 gap-y-4">
              <Link
                href="/artifacts/paina/business#done"
                className="font-label inline-flex items-center gap-2 rounded-full bg-[var(--paina-fg)] px-7 py-3.5 text-[13px] tracking-wide text-[var(--paina-bg)] transition-opacity hover:opacity-90"
              >
                Done の提供を待つ
                <ArrowUpRight className="h-4 w-4" />
              </Link>
              <Link
                href="/artifacts/paina/business"
                className="font-label link-underline inline-flex items-center gap-1.5 text-[14px] text-[var(--paina-fg)]"
              >
                事業内容を見る
              </Link>
            </div>
          </Reveal>
        </div>
      </section>

      <div className="mx-auto max-w-[1180px] px-6 md:px-10">
        <div className="hairline h-px w-full" />
      </div>

      {/* ===== Manifesto / 想い ===== */}
      <section className="px-6 py-24 md:px-10 md:py-36">
        <div className="mx-auto grid max-w-[1180px] gap-y-12 md:grid-cols-[0.8fr_1.6fr] md:gap-x-20">
          <Reveal>
            <div className="md:sticky md:top-32">
              <p className="kicker">Our Belief</p>
              <h2 className="font-serif-jp mt-5 text-[1.6rem] leading-[1.6] text-[var(--paina-fg)]">
                想い
              </h2>
            </div>
          </Reveal>
          <div className="max-w-[58ch] space-y-8">
            <Reveal>
              <p
                className="font-serif-jp text-[1.35rem] leading-[2] text-[var(--paina-fg)] md:text-[1.6rem]"
                data-edit-id="manifesto-lead"
              >
                AIは、急速に賢くなりました。
                けれど「賢いこと」と「役に立つこと」のあいだには、まだ大きな隔たりがあります。
              </p>
            </Reveal>
            <Reveal delay={80}>
              <p className="lead text-[16px] md:text-[17px]">
                多くのAIは、答えを返すところで止まります。
                でも私たちが本当に欲しいのは、答えではなく、終わっている状態です。
                調べ、判断し、実際に手を動かし、結果を確かめて、必要なら自分で直す。
                その最後の一歩までを引き受けてはじめて、AIは仕事の相棒になります。
              </p>
            </Reveal>
            <Reveal delay={120}>
              <p className="lead text-[16px] md:text-[17px]">
                私たちはこのAIを「Done（ダン）」と名づけました。
                「やっておいて」と頼んだことが、本当に終わっている。
                その当たり前を、誰にとっても当たり前にしたい。
                それが株式会社パイナの出発点です。
              </p>
            </Reveal>
            <Reveal delay={160}>
              <p className="lead text-[16px] md:text-[17px]">
                自律と暴走は紙一重です。だからこそ私たちは、力を増やすことと同じだけ、
                人が安心して任せられる境界をつくることに時間をかけます。
                派手さより、確かさ。私たちは、長く隣にいられるAIを目指します。
              </p>
            </Reveal>
          </div>
        </div>
      </section>

      {/* ===== Approach / アプローチ ===== */}
      <section className="bg-[var(--paina-bg-soft)] px-6 py-24 md:px-10 md:py-36">
        <div className="mx-auto max-w-[1180px]">
          <Reveal>
            <p className="kicker">How We Build</p>
            <h2 className="font-serif-jp mt-5 max-w-[20ch] text-[1.9rem] leading-[1.5] text-[var(--paina-fg)] md:text-[2.6rem] md:leading-[1.45]">
              ダンを、どうつくっているか。
            </h2>
          </Reveal>

          <div className="mt-16 grid gap-px overflow-hidden rounded-2xl border border-[var(--paina-border)] bg-[var(--paina-border)] md:grid-cols-2">
            {APPROACH.map((a, i) => (
              <Reveal key={a.no} delay={i * 80} className="bg-[var(--paina-bg)]">
                <div className="flex h-full flex-col gap-5 p-8 md:p-11">
                  <span className="font-en text-[2.2rem] italic leading-none text-[var(--paina-gold)]">
                    {a.no}
                  </span>
                  <h3 className="font-serif-jp text-[1.3rem] leading-[1.6] text-[var(--paina-fg)]">
                    {a.title}
                  </h3>
                  <p className="lead text-[15px] leading-[2]">{a.body}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ===== Business summary ===== */}
      <section className="px-6 py-24 md:px-10 md:py-36">
        <div className="mx-auto max-w-[1180px]">
          <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
            <Reveal>
              <div>
                <p className="kicker">What We Do</p>
                <h2 className="font-serif-jp mt-5 text-[1.9rem] leading-[1.5] text-[var(--paina-fg)] md:text-[2.6rem]">
                  事業内容
                </h2>
              </div>
            </Reveal>
            <Reveal delay={120}>
              <Link
                href="/artifacts/paina/business"
                className="font-label link-underline inline-flex items-center gap-1.5 text-[14px]"
              >
                すべて見る
                <ArrowUpRight className="h-4 w-4" />
              </Link>
            </Reveal>
          </div>

          <div className="mt-14 grid gap-10 md:grid-cols-3">
            {BUSINESS.map((b, i) => (
              <Reveal key={b.title} delay={i * 80}>
                <div className="flex h-full flex-col border-t border-[var(--paina-border-strong)] pt-7">
                  <span className="font-label text-[11px] uppercase tracking-[0.24em] text-[var(--paina-gold)]">
                    {b.label}
                  </span>
                  <h3 className="font-serif-jp mt-4 text-[1.25rem] leading-[1.6] text-[var(--paina-fg)]">
                    {b.title}
                  </h3>
                  <p className="lead mt-4 text-[15px]">{b.body}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ===== Done waitlist CTA ===== */}
      <section id="done" className="px-6 pb-12 md:px-10">
        <div className="mx-auto max-w-[1180px]">
          <Reveal>
            <div className="overflow-hidden rounded-3xl border border-[var(--paina-border)] bg-[var(--paina-fg)] px-8 py-14 text-[var(--paina-bg)] md:px-16 md:py-20">
              <p className="font-label text-[11px] uppercase tracking-[0.3em] text-[var(--paina-gold-soft)]">
                Coming soon
              </p>
              <h2 className="font-serif-jp mt-6 max-w-[22ch] text-[1.8rem] leading-[1.5] md:text-[2.5rem] md:leading-[1.45]">
                Done（ダン）の提供開始を、
                <br className="hidden md:block" />
                最初にお知らせします。
              </h2>
              <p className="mt-6 max-w-[52ch] text-[15px] leading-[2] text-[var(--paina-bg)]/75">
                第三者向けの提供を準備中です。ウェイティングリストにご登録いただいた方へ、
                先行してご案内します。
              </p>
              <div className="mt-9 max-w-[640px]">
                <WaitlistForm tone="dark" />
              </div>
            </div>
          </Reveal>
        </div>
      </section>
    </div>
  );
}
