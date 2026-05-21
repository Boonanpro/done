import Link from "next/link";
import { ChevronRight, Phone, MessageCircle, Clock, MapPin } from "lucide-react";
import { LpShell } from "@/components/templates/lp-shell";
import { Section } from "@/components/templates/section";
import { SiteNav } from "../components/site-nav";
import { SiteFooter } from "../components/site-footer";
import { DiagonalDivider } from "../components/diagonal-divider";
import { MultiStepInquiry } from "../components/multi-step-inquiry";

export const metadata = {
  title: "お問い合わせ | 吉川特装",
  description:
    "特装車の修理・整備のお問い合わせフォーム。LINE・お電話に加えて、車検証写真や故障画像を添付できる詳細フォームもご利用いただけます。",
};

export default function ContactPage() {
  return (
    <LpShell nav={<SiteNav />} footer={<SiteFooter />}>
      <PageHero />
      <Section padding="xl" width="lg" className="bg-background">
        <div className="space-y-10">
          <div className="text-center">
            <p className="text-[var(--yk-steel)] leading-relaxed">
              修理・点検・部品のご相談は、LINEまたはお電話でお気軽にお問い合わせください。
              <br className="hidden sm:inline" />
              メーカー・型式・症状の3点が分かるとスムーズにご案内できます。
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* LINE */}
            <a
              href="https://line.me/R/ti/p/@kittoku"
              target="_blank"
              rel="noreferrer noopener"
              className="group relative block bg-white border border-border rounded-sm overflow-hidden hover:border-[#06c755] transition-colors"
            >
              <div className="p-8 sm:p-10 space-y-5">
                <div className="h-14 w-14 rounded-sm bg-[#06c755] text-white flex items-center justify-center">
                  <MessageCircle className="h-7 w-7" />
                </div>
                <div className="space-y-2">
                  <div className="font-eyebrow text-xs text-[var(--yk-gold-dark)]">LINE</div>
                  <h2 className="font-headline text-2xl sm:text-3xl font-black text-[var(--yk-navy)] leading-tight">
                    LINEで問い合わせ
                  </h2>
                  <p className="text-sm text-[var(--yk-steel)] leading-relaxed">
                    画像や動画もまとめて送れます。スマートフォンから最も手軽にご相談いただけます。
                  </p>
                </div>
                <div className="inline-flex items-center gap-2 text-[#06c755] font-bold text-sm group-hover:gap-3 transition-all">
                  友だち追加して問い合わせる
                  <ChevronRight className="h-4 w-4" />
                </div>
              </div>
            </a>

            {/* TEL */}
            <a
              href="tel:0859-27-4885"
              className="group relative block bg-white border border-border rounded-sm overflow-hidden hover:border-[var(--yk-gold)] transition-colors"
            >
              <div className="p-8 sm:p-10 space-y-5">
                <div className="h-14 w-14 rounded-sm bg-[var(--yk-gold)] text-[var(--yk-navy-dark)] flex items-center justify-center">
                  <Phone className="h-7 w-7" />
                </div>
                <div className="space-y-2">
                  <div className="font-eyebrow text-xs text-[var(--yk-gold-dark)]">TEL</div>
                  <div className="font-mono-data text-3xl sm:text-4xl font-black text-[var(--yk-navy)] tracking-tight">
                    0859-27-4885
                  </div>
                  <p className="text-sm text-[var(--yk-steel)] leading-relaxed">
                    急な故障や緊急対応はお電話が確実です。担当者が直接お話を伺います。
                  </p>
                </div>
                <div className="inline-flex items-center gap-2 text-[var(--yk-gold-dark)] font-bold text-sm group-hover:gap-3 transition-all">
                  電話をかける
                  <ChevronRight className="h-4 w-4" />
                </div>
              </div>
            </a>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-4 border-t border-border">
            <div className="flex items-start gap-3 text-sm">
              <Clock className="h-4 w-4 text-[var(--yk-navy)] shrink-0 mt-0.5" />
              <div>
                <div className="font-eyebrow text-[10px] text-[var(--yk-gold-dark)] mb-1">営業時間</div>
                <div className="text-[var(--yk-navy-dark)]">月〜土 9:00〜17:00</div>
                <div className="text-xs text-[var(--yk-steel)]">日祝休</div>
              </div>
            </div>
            <div className="flex items-start gap-3 text-sm">
              <MapPin className="h-4 w-4 text-[var(--yk-navy)] shrink-0 mt-0.5" />
              <div>
                <div className="font-eyebrow text-[10px] text-[var(--yk-gold-dark)] mb-1">所在地</div>
                <div className="text-[var(--yk-navy-dark)]">鳥取県米子市古豊千775-6</div>
                <div className="text-xs text-[var(--yk-steel)]">〒689-3537</div>
              </div>
            </div>
          </div>
        </div>
      </Section>

      <Section padding="xl" width="lg" className="bg-muted/30 border-t border-border">
        <div className="space-y-6">
          <div className="text-center space-y-2">
            <div className="flex items-center justify-center gap-3">
              <DiagonalDivider color="var(--yk-gold)" />
              <span className="font-eyebrow text-xs text-[var(--yk-gold-dark)]">Inquiry Form</span>
              <DiagonalDivider color="var(--yk-gold)" />
            </div>
            <h2 className="font-headline text-2xl sm:text-3xl font-black text-[var(--yk-navy)]">
              詳細フォームでお問い合わせ
            </h2>
            <p className="text-sm text-[var(--yk-steel)] leading-relaxed max-w-2xl mx-auto">
              車検証や故障画像を添付したい方、メールでのやりとりを希望される方はこちらからどうぞ。
            </p>
          </div>
          <MultiStepInquiry />
        </div>
      </Section>
    </LpShell>
  );
}

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
      <div className="relative mx-auto max-w-4xl px-4 sm:px-6 py-16 sm:py-20">
        <div className="flex items-center gap-2 text-xs text-white/70 mb-6">
          <Link href="/artifacts/kittoku" className="hover:text-white">
            ホーム
          </Link>
          <ChevronRight className="h-3 w-3" />
          <span className="text-white">お問い合わせ</span>
        </div>
        <div className="flex items-center gap-3 mb-4">
          <DiagonalDivider color="var(--yk-gold)" />
          <span className="font-eyebrow text-xs text-[var(--yk-gold)]">Contact</span>
        </div>
        <h1
          data-edit-id="kittoku-contact-hero-h1"
          className="font-headline text-3xl sm:text-4xl lg:text-5xl font-black leading-tight"
        >
          LINE または お電話で
          <br />
          お問い合わせください
        </h1>
      </div>
    </section>
  );
}
