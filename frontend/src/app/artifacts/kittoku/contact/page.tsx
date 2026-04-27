import Link from "next/link";
import { ChevronRight, Info } from "lucide-react";
import { LpShell } from "@/components/templates/lp-shell";
import { Section } from "@/components/templates/section";
import { SiteNav } from "../components/site-nav";
import { SiteFooter } from "../components/site-footer";
import { DiagonalDivider } from "../components/diagonal-divider";
import { MultiStepInquiry } from "../components/multi-step-inquiry";

export const metadata = {
  title: "お問い合わせ | 吉川特装",
  description:
    "特装車の修理・整備のお問い合わせフォーム。車検証写真や故障画像を添付して一度にお送りいただけます。",
};

export default function ContactPage() {
  return (
    <LpShell nav={<SiteNav />} footer={<SiteFooter />}>
      <PageHero />
      <Section padding="xl" width="lg" className="bg-background">
        <MultiStepInquiry />
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
          <span className="font-eyebrow text-xs text-[var(--yk-gold)]">
            Inquiry
          </span>
        </div>
        <h1 data-edit-id="kittoku-contact-hero-h1" className="font-headline text-3xl sm:text-4xl lg:text-5xl font-black leading-tight">
          車両情報・画像をまとめて送信いただけます
        </h1>
        <div className="mt-6 rounded-sm bg-white/10 border border-white/20 p-5 flex gap-3 max-w-2xl">
          <Info className="h-5 w-5 text-[var(--yk-gold)] shrink-0 mt-0.5" />
          <p data-edit-id="kittoku-contact-hero-info" className="text-sm text-white/85 leading-relaxed">
            特装車の部品発注には
            <span className="font-mono-data font-bold text-[var(--yk-gold)]">
              {" "}
              車台番号 / 型式 / 類別区分番号{" "}
            </span>
            が必要です。本フォームなら一度で必要な情報と画像をお送りいただけるので、折り返しとご対応が格段に早くなります。
          </p>
        </div>
      </div>
    </section>
  );
}
