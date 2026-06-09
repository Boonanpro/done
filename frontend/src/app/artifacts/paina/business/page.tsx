"use client";

import * as React from "react";
import { ArtifactLink as Link } from "@/components/artifacts/artifact-link";
import { ArrowUpRight } from "lucide-react";
import { Reveal } from "../components/reveal";
import { WaitlistForm } from "../components/waitlist-form";
import { useLang, type Lang } from "../components/lang-context";

type CaseItem = {
  client: string;
  reading: string;
  summary: { ja: string; en: string };
  tags: { ja: string[]; en: string[] };
  thumb: string;
  /** 実サイトのヒーローをそのまま生で埋め込んで動かす（href のページを表示） */
  liveHero?: boolean;
  href?: string;
};

const HP_CASES: CaseItem[] = [
  {
    client: "吉川特装",
    reading: "Yoshikawa Tokuso",
    summary: {
      ja: "特装車輌の架装・整備を手がける事業の信頼を、力強いビジュアルと実績の見せ方で伝えるコーポレートサイトを制作。",
      en: "A corporate site conveying the trust of a specialty-vehicle outfitting and maintenance business through bold visuals and a clear track record.",
    },
    tags: {
      ja: ["コーポレートサイト", "ブランディング"],
      en: ["Corporate site", "Branding"],
    },
    thumb: "/paina/case-kittoku-poster.jpg",
    liveHero: true,
    href: "https://done-studio.vercel.app/preview/kittoku/v2",
  },
  {
    client: "OBANZAI bar 五条",
    reading: "Gojo, Yonago",
    summary: {
      ja: "夜の隠れ家のような世界観を、温かい暗色と縦書き、手書き風のあしらいで表現した飲食店サイトを制作。",
      en: "A restaurant site expressing a hidden, late-night atmosphere with warm dark tones, vertical typography, and hand-drawn touches.",
    },
    tags: {
      ja: ["店舗サイト", "ブランディング"],
      en: ["Restaurant site", "Branding"],
    },
    thumb: "/paina/case-gojo-poster.jpg",
    liveHero: true,
    href: "https://yonago-gojo-done.vercel.app",
  },
];

const DX_CASES: CaseItem[] = [
  {
    client: "スタイルアップ",
    reading: "Style Up",
    summary: {
      ja: "美容サロンの予約サイトへのスタイル投稿を自動化。手作業だった掲載運用を仕組みに変え、更新の手間を大きく削減。",
      en: "Automated style posting to a salon booking site. A manual posting workflow became a system, greatly cutting the update effort.",
    },
    tags: {
      ja: ["業務自動化", "ツール開発"],
      en: ["Automation", "Tool development"],
    },
    thumb: "/paina/case-styleup.jpg",
  },
  {
    client: "電管ナレッジ",
    reading: "Denkan Knowledge",
    summary: {
      ja: "電気主任技術者の現場知識を蓄積・検索できるナレッジ基盤を構築。属人化していた情報を、誰でも引ける形に整理。",
      en: "A knowledge base where chief electrical engineers' field know-how is accumulated and searchable. Siloed information, organized so anyone can find it.",
    },
    tags: {
      ja: ["ナレッジ基盤", "DX支援"],
      en: ["Knowledge base", "DX support"],
    },
    thumb: "/paina/case-denki.jpg",
  },
];

const T = {
  ja: {
    kicker: "About",
    title: "パイナについて",
    intro:
      "中心にあるのは、AIエージェント「Done（ダン）」の開発です。そこで培った技術と視点を、ホームページ制作とDX支援という形で、いまの事業者の課題解決にも還元しています。",
    doneBadge: "Product — Coming soon",
    doneTitle: "Done（ダン）の開発",
    doneBody:
      "「やっておいて」が、本当に終わっている。調べ、判断し、操作し、結果を確かめて直すまでを自分で完結する、自律的なAIエージェントです。いまはパイナ自身の事業運営に使いながら、毎日鍛えています。第三者への提供は現在準備中です。",
    doneFeatures: [
      ["自律実行", "提案で止まらず、実務を最後までやり切る。"],
      ["記憶と学習", "あなたの文脈を覚え、使うほど馴染む。"],
      ["安全な境界", "任せる範囲を設計し、安心して預けられる。"],
    ],
    waitlistLabel: "Waiting list",
    waitlistDesc: "提供開始の際に、先行してご案内します。下記よりご登録ください。",
    hpTitle: "ホームページ制作",
    hpIntro:
      "事業の世界観と信頼を、言葉とデザインで形にします。テンプレートに当てはめるのではなく、何を伝えたいかから設計します。",
    dxTitle: "ソフトウェア・ツールによるDX支援",
    dxIntro:
      "現場の手作業を、仕組みに変える。業務に合わせた道具をつくり、繰り返しの負担と属人化を減らします。",
    ctaTitle: "制作・DX支援のご相談はお気軽に。",
    ctaBody: "小さな自動化から、サイト制作まで。まずはお話を聞かせてください。",
    ctaButton: "問い合わせる",
    companyKicker: "Company",
    companyTitle: "会社概要",
    company: [
      ["会社名", "株式会社パイナ（PAINA Inc.）"],
      [
        "所在地",
        "〒651-0084 兵庫県神戸市中央区磯辺通1丁目1番18号 カサベラ国際プラザビル707号室",
      ],
      ["代表者", "代表取締役 本田 樹"],
      ["資本金", "100万円"],
      [
        "事業内容",
        "AIエージェント「Done（ダン）」の開発／インターネットを使ったサービスの提供",
      ],
      ["連絡先", "shub6923@gmail.com"],
    ] as [string, string][],
  },
  en: {
    kicker: "About",
    title: "About PAINA",
    intro:
      "At the center is the development of the AI agent “Done.” The technology and perspective built there are also returned to today's businesses through website production and DX support.",
    doneBadge: "Product — Coming soon",
    doneTitle: "Developing Done",
    doneBody:
      "What you asked to be taken care of is genuinely finished. An autonomous AI agent that looks things up, decides, operates, checks the result, and fixes it on its own. For now it is sharpened every day within PAINA's own operations. Availability to third parties is in preparation.",
    doneFeatures: [
      ["Autonomous", "Doesn't stop at suggestions — sees the work through."],
      ["Memory & learning", "Remembers your context and fits better with use."],
      ["Safe boundaries", "The scope of delegation is designed, so you hand off with confidence."],
    ],
    waitlistLabel: "Waiting list",
    waitlistDesc: "Be the first to know when it opens. Register below.",
    hpTitle: "Website production",
    hpIntro:
      "Giving shape to a business's world and trust through words and design. Not fitting into a template, but designing from what you want to convey.",
    dxTitle: "DX support with software & tools",
    dxIntro:
      "Turning manual field work into systems. Building tools tailored to the work to reduce repetitive burden and over-reliance on individuals.",
    ctaTitle: "Talk to me about a site or DX, anytime.",
    ctaBody:
      "From small automations to full sites — start by telling me what you need.",
    ctaButton: "Get in touch",
    companyKicker: "Company",
    companyTitle: "Company profile",
    company: [
      ["Company", "PAINA Inc. (株式会社パイナ)"],
      [
        "Address",
        "Room 707, Casabella Kokusai Plaza Bldg., 1-1-18 Isobedori, Chuo-ku, Kobe, Hyogo 651-0084, Japan",
      ],
      ["Representative", "Miki Honda, Representative Director"],
      ["Capital", "JPY 1,000,000"],
      [
        "Business",
        "Development of the AI agent “Done” / Internet-based services",
      ],
      ["Contact", "shub6923@gmail.com"],
    ] as [string, string][],
  },
};

/**
 * 実サイトのヒーローを生のまま埋め込んで動かす。録画ではなく本物の <iframe> を
 * デスクトップ幅でレンダリングし、カード幅に合わせて縮小表示する。操作は無効
 * （pointer-events:none）。読み込むまではポスター画像を表示する。
 */
function LiveHero({
  src,
  poster,
  title,
}: {
  src: string;
  poster: string;
  title: string;
}) {
  const boxRef = React.useRef<HTMLDivElement>(null);
  const [scale, setScale] = React.useState(0);
  const [show, setShow] = React.useState(false); // 画面に入ったらiframeを生成
  const [loaded, setLoaded] = React.useState(false);

  const BASE_W = 1366;
  const BASE_H = Math.round((BASE_W * 10) / 16); // 16:10

  React.useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      setScale(el.clientWidth / BASE_W);
    });
    ro.observe(el);
    setScale(el.clientWidth / BASE_W);

    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setShow(true);
          io.disconnect();
        }
      },
      { rootMargin: "200px" }
    );
    io.observe(el);

    return () => {
      ro.disconnect();
      io.disconnect();
    };
  }, []);

  return (
    <div
      ref={boxRef}
      className="absolute inset-0 overflow-hidden transition-transform duration-700 group-hover:scale-[1.03]"
    >
      <img
        src={poster}
        alt={title}
        aria-hidden
        className={`absolute inset-0 h-full w-full object-cover object-top transition-opacity duration-500 ${
          loaded ? "opacity-0" : "opacity-100"
        }`}
      />
      {show && scale > 0 && (
        <iframe
          src={src}
          title={title}
          tabIndex={-1}
          scrolling="no"
          loading="lazy"
          onLoad={() => setLoaded(true)}
          className="pointer-events-none absolute left-0 top-0 border-0"
          style={{
            width: BASE_W,
            height: BASE_H,
            transform: `scale(${scale})`,
            transformOrigin: "top left",
          }}
        />
      )}
    </div>
  );
}

function CaseCard({ c, index, lang }: { c: CaseItem; index: number; lang: Lang }) {
  const inner = (
    <div className="group flex h-full flex-col overflow-hidden rounded-2xl border border-[var(--paina-border)] bg-[var(--paina-bg)] transition-colors hover:border-[var(--paina-border-strong)]">
      <div className="relative aspect-[16/10] overflow-hidden border-b border-[var(--paina-border)] bg-[var(--paina-bg-soft)]">
        {c.liveHero && c.href ? (
          <LiveHero src={c.href} poster={c.thumb} title={c.client} />
        ) : (
          <img
            src={c.thumb}
            alt={`${c.client}`}
            loading="lazy"
            className="h-full w-full object-cover object-top transition-transform duration-700 group-hover:scale-[1.03]"
          />
        )}
        {c.href && (
          <span className="absolute right-3 top-3 flex h-8 w-8 items-center justify-center rounded-full bg-[var(--paina-bg)]/90 text-[var(--paina-fg)] shadow-sm backdrop-blur">
            <ArrowUpRight className="h-4 w-4" />
          </span>
        )}
      </div>

      <div className="flex flex-1 flex-col justify-between p-7 md:p-8">
        <div>
          <h4 className="font-serif-jp text-[1.35rem] leading-[1.5] text-[var(--paina-fg)]">
            {c.client}
          </h4>
          <p className="font-en mt-1 text-[13px] italic text-[var(--paina-faint)]">
            {c.reading}
          </p>
          <p className="lead mt-5 text-[15px] leading-[2]">{c.summary[lang]}</p>
        </div>
        <div className="mt-7 flex flex-wrap gap-2">
          {c.tags[lang].map((t) => (
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
        <a
          href={c.href}
          target="_blank"
          rel="noopener noreferrer"
          className="block h-full"
        >
          {inner}
        </a>
      ) : (
        inner
      )}
    </Reveal>
  );
}

export default function PainaBusiness() {
  const { lang } = useLang();
  const t = T[lang];

  return (
    <div>
      {/* Hero */}
      <section className="px-6 pb-16 pt-36 md:px-10 md:pb-20 md:pt-48">
        <div className="mx-auto max-w-[1180px]">
          <Reveal>
            <p className="kicker">{t.kicker}</p>
          </Reveal>
          <Reveal delay={120}>
            <h1 className="font-serif-jp mt-7 text-[1.55rem] leading-[1.4] text-[var(--paina-fg)] sm:text-[2.6rem]">
              {t.title}
            </h1>
          </Reveal>
          <Reveal delay={220}>
            <p className="lead mt-8 max-w-[54ch] text-[16px] md:text-[17px]">
              {t.intro}
            </p>
          </Reveal>
        </div>
      </section>

      {/* 01 Done */}
      <section id="done" className="scroll-mt-24 px-6 py-20 md:px-10 md:py-28">
        <div className="mx-auto max-w-[1180px]">
          <div className="overflow-hidden rounded-3xl bg-[var(--paina-fg)] px-8 py-14 text-[var(--paina-bg)] md:px-16 md:py-20">
            <Reveal>
              <div className="flex items-center gap-4">
                <span className="font-en text-[1.4rem] italic text-[var(--paina-gold)]">
                  01
                </span>
                <span className="font-label rounded-full border border-[var(--paina-gold-soft)]/40 px-3 py-1 text-[11px] uppercase tracking-[0.24em] text-[var(--paina-gold-soft)]">
                  {t.doneBadge}
                </span>
              </div>
              <h2 className="font-serif-jp mt-7 max-w-[20ch] text-[1.55rem] leading-[1.45] sm:text-[2.6rem]">
                {t.doneTitle}
              </h2>
              <p className="mt-7 max-w-[58ch] text-[16px] leading-[2.1] text-[var(--paina-bg)]/80">
                {t.doneBody}
              </p>
            </Reveal>

            <Reveal delay={120}>
              <div className="mt-10 grid gap-6 border-t border-[var(--paina-bg)]/15 pt-10 sm:grid-cols-3">
                {t.doneFeatures.map(([title, desc]) => (
                  <div key={title}>
                    <h3 className="font-serif-jp text-[1.1rem] text-[var(--paina-bg)]">
                      {title}
                    </h3>
                    <p className="mt-2 text-[14px] leading-[1.9] text-[var(--paina-bg)]/65">
                      {desc}
                    </p>
                  </div>
                ))}
              </div>
            </Reveal>

            <Reveal delay={200}>
              <div className="mt-12">
                <p className="font-label text-[12px] uppercase tracking-[0.24em] text-[var(--paina-gold-soft)]">
                  {t.waitlistLabel}
                </p>
                <p className="mt-4 max-w-[50ch] text-[15px] leading-[2] text-[var(--paina-bg)]/80">
                  {t.waitlistDesc}
                </p>
                <div className="mt-6 max-w-[640px]">
                  <WaitlistForm tone="dark" />
                </div>
              </div>
            </Reveal>
          </div>
        </div>
      </section>

      {/* 02 HP */}
      <section className="px-6 py-16 md:px-10 md:py-24">
        <div className="mx-auto max-w-[1180px]">
          <Reveal>
            <div className="flex items-center gap-4">
              <span className="font-en text-[1.4rem] italic text-[var(--paina-gold)]">
                02
              </span>
              <span className="font-label text-[11px] uppercase tracking-[0.24em] text-[var(--paina-gold)]">
                Service
              </span>
            </div>
            <h2 className="font-serif-jp mt-6 text-[1.55rem] leading-[1.5] text-[var(--paina-fg)] sm:text-[2.6rem]">
              {t.hpTitle}
            </h2>
            <p className="lead mt-6 max-w-[54ch] text-[16px]">{t.hpIntro}</p>
          </Reveal>

          <div className="mt-12 grid gap-6 md:grid-cols-2">
            {HP_CASES.map((c, i) => (
              <CaseCard key={c.client} c={c} index={i} lang={lang} />
            ))}
          </div>
        </div>
      </section>

      {/* 03 DX */}
      <section className="bg-[var(--paina-bg-soft)] px-6 py-16 md:px-10 md:py-24">
        <div className="mx-auto max-w-[1180px]">
          <Reveal>
            <div className="flex items-center gap-4">
              <span className="font-en text-[1.4rem] italic text-[var(--paina-gold)]">
                03
              </span>
              <span className="font-label text-[11px] uppercase tracking-[0.24em] text-[var(--paina-gold)]">
                Service
              </span>
            </div>
            <h2 className="font-serif-jp mt-6 text-[1.55rem] leading-[1.5] text-[var(--paina-fg)] sm:text-[2.6rem]">
              {t.dxTitle}
            </h2>
            <p className="lead mt-6 max-w-[54ch] text-[16px]">{t.dxIntro}</p>
          </Reveal>

          <div className="mt-12 grid gap-6 md:grid-cols-2">
            {DX_CASES.map((c, i) => (
              <CaseCard key={c.client} c={c} index={i} lang={lang} />
            ))}
          </div>
        </div>
      </section>

      {/* Company profile */}
      <section className="border-t border-[var(--paina-border)] px-6 py-20 md:px-10 md:py-28">
        <div className="mx-auto max-w-[1180px]">
          <Reveal>
            <p className="kicker">{t.companyKicker}</p>
            <h2 className="font-serif-jp mt-6 text-[1.55rem] leading-[1.5] text-[var(--paina-fg)] sm:text-[2.6rem]">
              {t.companyTitle}
            </h2>
          </Reveal>
          <Reveal delay={120}>
            <dl className="mt-12 border-t border-[var(--paina-border)]">
              {t.company.map(([k, v]) => (
                <div
                  key={k}
                  className="flex flex-col gap-1 border-b border-[var(--paina-border)] py-6 md:flex-row md:gap-10 md:py-7"
                >
                  <dt className="font-label w-full shrink-0 text-[12px] uppercase tracking-[0.18em] text-[var(--paina-muted)] md:w-[180px] md:pt-1">
                    {k}
                  </dt>
                  <dd className="text-[15px] leading-[2] text-[var(--paina-fg)]">
                    {v}
                  </dd>
                </div>
              ))}
            </dl>
          </Reveal>
        </div>
      </section>

      {/* Final CTA */}
      <section className="px-6 py-24 md:px-10 md:py-32">
        <div className="mx-auto max-w-[1180px] text-center">
          <Reveal>
            <h2 className="font-serif-jp text-[1.55rem] leading-[1.55] text-[var(--paina-fg)] sm:text-[2.6rem]">
              {t.ctaTitle}
            </h2>
            <p className="lead mx-auto mt-6 max-w-[48ch] text-[16px]">
              {t.ctaBody}
            </p>
            <Link
              href="/artifacts/paina/contact"
              className="font-label mt-10 inline-flex items-center gap-2 rounded-full bg-[var(--paina-fg)] px-8 py-3.5 text-[13px] tracking-wide text-[var(--paina-bg)] transition-opacity hover:opacity-90"
            >
              {t.ctaButton}
              <ArrowUpRight className="h-4 w-4" />
            </Link>
          </Reveal>
        </div>
      </section>
    </div>
  );
}
