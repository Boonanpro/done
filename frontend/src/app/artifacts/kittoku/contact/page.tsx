import { ArtifactLink as Link } from "@/components/artifacts/artifact-link";
import {
  ChevronRight,
  Phone,
  MessageCircle,
  Clock,
  Wrench,
  Send,
} from "lucide-react";
import { LpShell } from "@/components/templates/lp-shell";
import { Section } from "@/components/templates/section";
import { SiteNav } from "../components/site-nav";
import { SiteFooter } from "../components/site-footer";
import { DiagonalDivider } from "../components/diagonal-divider";
import { LineInquiryMockup } from "../components/line-inquiry-mockup";
import { PartsOrderForm } from "./contact-form";

export const metadata = {
  title: "お問い合わせ | 吉川特装",
  description: "吉川特装へのお問い合わせ。 修理・整備はお電話、 部品注文は WEB フォームをご利用ください。公式 LINE は開設準備中です。",
};

export default function ContactPage() {
  return (
    <LpShell nav={<SiteNav />} footer={<SiteFooter />}>
      <PageHero />
      <PartsGuideSection />
      <ContactArea />
      <LineMockupSection />
      <HoursNote />
    </LpShell>
  );
}

/* ───────────────────────── お問い合わせ前にご覧ください (案内動画) ───────────────────────── */

function PartsGuideSection() {
  return (
    <Section padding="lg" width="lg" className="bg-background">
      <div className="text-center mb-6 sm:mb-8 space-y-3">
        <div className="flex items-center justify-center gap-3">
          <DiagonalDivider color="var(--yk-gold)" />
          <span className="font-eyebrow text-[10px] sm:text-xs text-[var(--yk-gold-dark)] tracking-[0.25em]">
            Watch First
          </span>
        </div>
        <h2 className="font-headline text-2xl sm:text-3xl lg:text-4xl font-black text-[var(--yk-navy)] leading-tight">
          お問い合わせ前に
          <br className="sm:hidden" />
          こちらをご覧ください
        </h2>
        <p className="text-sm sm:text-base text-[var(--yk-steel)] leading-relaxed max-w-xl mx-auto">
          部品注文の流れと、 スムーズにご案内するために必要な情報を短くまとめました。
        </p>
      </div>
      <div className="relative aspect-video rounded-sm overflow-hidden bg-black border border-border shadow-xl max-w-4xl mx-auto">
        <video
          src="/kikkawa/parts-guide.mp4"
          poster="/kikkawa/parts-guide-poster.jpg"
          controls
          playsInline
          preload="metadata"
          className="absolute inset-0 w-full h-full object-cover"
          aria-label="部品注文のご案内"
        />
      </div>
    </Section>
  );
}

/* ───────────────────────── 極薄ヒーロー (breadcrumb + h1 のみ) ───────────────────────── */

function PageHero() {
  return (
    <section className="relative bg-[var(--yk-navy)] text-white overflow-hidden">
      <div
        className="absolute inset-0 opacity-[0.08]"
        style={{
          backgroundImage:
            "repeating-linear-gradient(-45deg, var(--yk-gold) 0 1px, transparent 1px 14px)",
        }}
      />
      <div className="relative mx-auto max-w-7xl px-4 sm:px-6 py-5 sm:py-7">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div className="flex items-center gap-3">
            <DiagonalDivider color="var(--yk-gold)" />
            <span className="font-eyebrow text-[10px] sm:text-xs text-[var(--yk-gold)]">Contact</span>
            <h1
              data-edit-id="kittoku-contact-hero-h1"
              className="font-headline text-xl sm:text-2xl lg:text-3xl font-black leading-none"
            >
              お問い合わせ
            </h1>
          </div>
          <div className="flex items-center gap-2 text-xs text-white/70">
            <Link href="/artifacts/kittoku" className="hover:text-white">ホーム</Link>
            <ChevronRight className="h-3 w-3" />
            <span className="text-white">お問い合わせ</span>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ───────────────────────── バナー2個 + フォーム を1ビューに ───────────────────────── */

function ContactArea() {
  return (
    <Section padding="md" width="xl" className="bg-background">
      {/* バナー2個 (PCで2列、 スマホで1列) */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 sm:gap-5 mb-6 sm:mb-8">
        <UrgentRepairBanner />
        <LineOrderBanner />
      </div>

      {/* WEB フォーム */}
      <div className="rounded-sm border border-border bg-white p-5 sm:p-8 lg:p-10">
        <div className="flex items-center gap-3 mb-6 sm:mb-8">
          <div className="h-10 w-10 sm:h-11 sm:w-11 rounded-sm bg-[var(--yk-navy)] text-white flex items-center justify-center shrink-0">
            <Send className="h-5 w-5 sm:h-6 sm:w-6" />
          </div>
          <div>
            <div className="font-eyebrow text-[10px] sm:text-xs text-[var(--yk-gold-dark)] tracking-[0.25em]">
              Web Form
            </div>
            <div className="font-headline text-lg sm:text-xl font-black text-[var(--yk-navy)] leading-tight">
              WEB フォームでお問い合わせ
            </div>
          </div>
        </div>
        <PartsOrderForm />
      </div>
    </Section>
  );
}

/* ───────────────────────── バナー: 修理・整備=電話 ───────────────────────── */

function UrgentRepairBanner() {
  return (
    <div className="rounded-sm border border-[var(--yk-gold)]/40 bg-[var(--yk-navy)] text-white overflow-hidden flex flex-col">
      <div className="flex items-center gap-3 px-5 py-4 bg-[var(--yk-navy-dark)]">
        <div className="h-10 w-10 rounded-sm bg-[var(--yk-gold)] text-[var(--yk-navy-dark)] flex items-center justify-center shrink-0">
          <Wrench className="h-5 w-5" />
        </div>
        <div>
          <div className="font-eyebrow text-[10px] text-[var(--yk-gold)] tracking-[0.25em]">
            For Repair
          </div>
          <div className="font-headline text-base sm:text-lg font-black leading-tight">
            修理・整備のご相談
          </div>
        </div>
      </div>
      <a
        href="tel:0859-27-4885"
        className="group flex-1 flex items-center justify-center gap-3 px-6 py-5 sm:py-6 bg-[var(--yk-gold)] hover:bg-[var(--yk-gold-dark)] text-[var(--yk-navy-dark)] transition-colors"
        aria-label="電話する 0859-27-4885"
      >
        <Phone className="h-5 w-5 sm:h-6 sm:w-6 shrink-0" />
        <div className="flex flex-col items-start leading-none">
          <span className="font-eyebrow text-[9px] sm:text-[10px] tracking-[0.3em] mb-1">
            Call Now
          </span>
          <span className="font-mono-data text-xl sm:text-2xl lg:text-3xl font-black tracking-tight whitespace-nowrap">
            0859-27-4885
          </span>
        </div>
      </a>
    </div>
  );
}

/* ───────────────────────── バナー: LINE で部品注文 ───────────────────────── */

function LineOrderBanner() {
  return (
    <div className="rounded-sm border border-[#06c755]/30 bg-white overflow-hidden flex flex-col">
      <div className="flex items-center gap-3 px-5 py-4 bg-[#06c755]/[0.07]">
        <div className="h-10 w-10 rounded-sm bg-[#06c755] text-white flex items-center justify-center shrink-0">
          <MessageCircle className="h-5 w-5" />
        </div>
        <div>
          <div className="font-eyebrow text-[10px] text-[#06c755] tracking-[0.25em]">
            Coming Soon
          </div>
          <div className="font-headline text-base sm:text-lg font-black text-[var(--yk-navy)] leading-tight">
            LINE で部品注文（準備中）
          </div>
        </div>
      </div>
      <div
        aria-disabled="true"
        className="flex-1 flex items-center justify-center gap-3 px-6 py-5 sm:py-6 bg-[#06c755]/60 text-white cursor-not-allowed select-none"
      >
        <MessageCircle className="h-5 w-5 sm:h-6 sm:w-6 shrink-0" />
        <div className="flex flex-col items-start leading-none">
          <span className="font-eyebrow text-[9px] sm:text-[10px] tracking-[0.3em] mb-1">
            Coming Soon
          </span>
          <span className="font-headline text-lg sm:text-xl lg:text-2xl font-black tracking-tight">
            開設準備中・お電話でお願いします
          </span>
        </div>
      </div>
    </div>
  );
}

/* ───────────────────────── 公式LINE はじめました セクション ───────────────────────── */

function LineMark({ className = "" }: { className?: string }) {
  return (
    <span className={`inline-flex items-center justify-center bg-[#06c755] rounded-2xl shadow-md ${className}`}>
      <svg viewBox="0 0 24 24" className="w-3/5 h-3/5 fill-white" aria-hidden="true">
        <path d="M19.95 11.2c0-3.55-3.56-6.44-7.94-6.44s-7.94 2.89-7.94 6.44c0 3.18 2.82 5.85 6.63 6.35.26.06.61.17.7.39.08.2.05.51.03.71 0 0-.09.55-.11.67-.04.2-.16.78.68.43.85-.36 4.58-2.7 6.25-4.62 1.15-1.27 1.7-2.55 1.7-3.93zM9.21 13.31H7.62c-.1 0-.17-.08-.17-.17V10.0c0-.1.08-.17.17-.17h.4c.1 0 .17.08.17.17v2.55h1.02c.1 0 .17.08.17.17v.4c0 .1-.08.17-.17.17zm.97 0h-.4a.17.17 0 0 1-.17-.17V10.0c0-.1.08-.17.17-.17h.4c.1 0 .17.08.17.17v3.14c0 .1-.08.17-.17.17zm3.52 0h-.4a.17.17 0 0 1-.13-.07l-1.42-1.93v1.83c0 .1-.08.17-.17.17h-.4a.17.17 0 0 1-.17-.17V10.0c0-.1.08-.17.17-.17h.4c.05 0 .1.03.13.07l1.42 1.92V10c0-.1.08-.17.17-.17h.4c.1 0 .17.08.17.17v3.14c0 .1-.08.17-.17.17zm2.55 0h-1.59a.17.17 0 0 1-.17-.17V10.0c0-.1.08-.17.17-.17h1.59c.1 0 .17.08.17.17v.4c0 .1-.08.17-.17.17H15.0v.55h1.25c.1 0 .17.08.17.17v.4c0 .1-.08.17-.17.17H15.0v.55h1.25c.1 0 .17.08.17.17v.4c0 .1-.08.17-.17.17z"/>
      </svg>
    </span>
  );
}

function LineMockupSection() {
  return (
    <Section padding="xl" width="xl" className="bg-[#06c755]/[0.04]">
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_auto] gap-8 sm:gap-12 lg:gap-16 items-center max-w-6xl mx-auto">
        {/* 左: メッセージ */}
        <div className="space-y-5 sm:space-y-6 text-center lg:text-left order-2 lg:order-1">
          <div className="flex items-center gap-3 justify-center lg:justify-start">
            <LineMark className="w-14 h-14 sm:w-16 sm:h-16" />
            <div className="font-eyebrow text-[10px] sm:text-xs text-[#06c755] tracking-[0.25em]">
              Coming Soon
            </div>
          </div>
          <h2 className="font-headline text-2xl sm:text-3xl lg:text-4xl font-black text-[var(--yk-navy)] leading-tight tracking-tight">
            公式 LINE 開設準備中
          </h2>
          <p className="text-sm sm:text-base text-[var(--yk-steel)] leading-relaxed">
            修理箇所の<strong className="text-[var(--yk-navy)]">写真や動画</strong>、 メーカー名・型式・架装番号などを{" "}
            <strong className="text-[var(--yk-navy)]">まとめて1回で送れる</strong>のが LINE 問い合わせのメリット。
            <br className="hidden sm:inline" />
            電話より気軽に、 メールより速く、 部品手配や修理相談がスムーズに進みます。
          </p>
          <ul className="space-y-1.5 text-sm text-[var(--yk-navy-dark)] inline-block text-left">
            <li className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-[#06c755]" />
              画像・動画を添付してそのまま送信
            </li>
            <li className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-[#06c755]" />
              空き時間でやりとりできる
            </li>
            <li className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-[#06c755]" />
              過去のトーク履歴ですぐ呼び出し
            </li>
          </ul>
          <p className="text-sm text-[var(--yk-navy)] font-bold pt-1">
            LINEをご利用の方は、 ぜひ友だち追加してください。
          </p>
          <div className="flex justify-center lg:justify-start">
            <a
              href="https://line.me/R/ti/p/@kittoku"
              target="_blank"
              rel="noreferrer noopener"
              className="inline-flex items-center gap-2.5 h-12 sm:h-14 px-6 sm:px-7 rounded-sm bg-[#06c755] hover:bg-[#05a648] text-white font-bold text-sm sm:text-base shadow-md hover:shadow-lg transition-all"
            >
              <LineMark className="w-7 h-7 sm:w-8 sm:h-8 !bg-white !shadow-none [&_path]:fill-[#06c755]" />
              友だち追加する
              <ChevronRight className="h-4 w-4 sm:h-5 sm:w-5" />
            </a>
          </div>
        </div>

        {/* 右: モックアップ */}
        <div className="flex justify-center order-1 lg:order-2 shrink-0">
          <div className="scale-[0.85] sm:scale-100 origin-center">
            <LineInquiryMockup />
          </div>
        </div>
      </div>
    </Section>
  );
}

/* ───────────────────────── 営業時間 (返信時間として) ───────────────────────── */

function HoursNote() {
  return (
    <Section padding="lg" width="lg" className="bg-background">
      <div className="flex items-start gap-3 max-w-2xl mx-auto">
        <div className="h-10 w-10 rounded-sm bg-[var(--yk-navy)] text-white flex items-center justify-center shrink-0">
          <Clock className="h-5 w-5" />
        </div>
        <div>
          <div className="font-eyebrow text-[10px] text-[var(--yk-gold-dark)] tracking-[0.25em] mb-1">
            Reply Hours
          </div>
          <div className="font-headline text-base font-bold text-[var(--yk-navy)]">
            営業時間内に返信します
          </div>
          <div className="text-sm text-[var(--yk-navy-dark)] mt-1">月〜土 9:00〜17:00</div>
          <div className="text-xs text-[var(--yk-steel)]">定休日：日祝・毎月第2土曜</div>
        </div>
      </div>
    </Section>
  );
}
