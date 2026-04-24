import Link from "next/link";
import {
  ChevronRight,
  Wrench,
  GraduationCap,
  Briefcase,
  CheckCircle2,
  ArrowRight,
} from "lucide-react";
import { LpShell } from "@/components/templates/lp-shell";
import { Section } from "@/components/templates/section";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { InquiryForm } from "@/components/templates/inquiry-form";
import { SiteNav } from "../components/site-nav";
import { SiteFooter } from "../components/site-footer";
import { DiagonalDivider } from "../components/diagonal-divider";

export const metadata = {
  title: "採用情報 | 吉川特装",
  description:
    "吉川特装の採用情報。特装車整備士・整備見習い・事務スタッフを募集しています。",
};

const POSITIONS = [
  {
    icon: Wrench,
    label: "特装車 整備士",
    tagline: "経験者歓迎",
    appeal: [
      "新明和工業 認定修理工場で働く",
      "特装車特有の油圧・機構を学べる",
      "中国地方の働く車を守る、やりがい",
    ],
    requirements: [
      "自動車整備士資格（3級以上）",
      "大型車整備の実務経験",
      "普通自動車免許（中型以上あれば尚可）",
    ],
  },
  {
    icon: GraduationCap,
    label: "整備見習い",
    tagline: "未経験OK",
    appeal: [
      "資格取得サポート制度",
      "先輩と二人三脚での現場OJT",
      "幅広い車種で技術を磨ける",
    ],
    requirements: [
      "18歳以上（高校卒業程度）",
      "車・機械への興味",
      "普通自動車免許（取得予定可）",
    ],
  },
  {
    icon: Briefcase,
    label: "事務・受付",
    tagline: "地域密着",
    appeal: [
      "お客様対応と社内サポート",
      "整備士と連携しながらの業務",
      "米子市内通勤可能な方向け",
    ],
    requirements: [
      "基本的なPC操作",
      "接客 or 電話応対の経験",
      "普通自動車免許",
    ],
  },
];

const BENEFITS = [
  { title: "各種社会保険完備", body: "健康 / 厚生年金 / 雇用 / 労災" },
  { title: "賞与年2回", body: "業績に応じて" },
  { title: "制服貸与", body: "作業着・安全靴を支給" },
  { title: "資格取得支援", body: "整備士資格の取得費用をサポート" },
  { title: "退職金制度", body: "中小企業退職金共済" },
  { title: "家族手当・通勤手当", body: "規定に基づき支給" },
];

export default function CareersPage() {
  return (
    <LpShell nav={<SiteNav />} footer={<SiteFooter />}>
      <PageHero />
      <PositionsSection />
      <BenefitsSection />
      <VoicesSection />
      <ApplyFormSection />
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
      <div className="relative mx-auto max-w-7xl px-4 sm:px-6 py-20 sm:py-28">
        <div className="flex items-center gap-2 text-xs text-white/70 mb-6">
          <Link href="/demo/yoshikawa-tokuso" className="hover:text-white">
            ホーム
          </Link>
          <ChevronRight className="h-3 w-3" />
          <span className="text-white">採用情報</span>
        </div>
        <div className="flex items-center gap-3 mb-4">
          <DiagonalDivider color="var(--yk-gold)" />
          <span className="font-eyebrow text-xs text-[var(--yk-gold)]">
            Careers
          </span>
        </div>
        <h1 className="font-headline text-4xl sm:text-5xl lg:text-6xl font-black leading-tight max-w-3xl">
          働く車を支える、
          <br />
          誇れる仕事を、一緒に。
        </h1>
        <p className="text-white/80 mt-6 text-base leading-relaxed max-w-2xl">
          特装車整備は奥深い技術の世界。油圧・電装・機構。一つひとつの工程にクライアントの事業が乗っています。
          その責任を喜びに変えられる仲間を募集しています。
        </p>
      </div>
    </section>
  );
}

function PositionsSection() {
  return (
    <Section padding="xl" width="xl" className="bg-background">
      <div className="space-y-3 mb-12">
        <div className="flex items-center gap-3">
          <DiagonalDivider />
          <span className="font-eyebrow text-xs text-[var(--yk-gold-dark)]">
            Positions
          </span>
        </div>
        <h2 className="font-headline text-3xl sm:text-4xl font-black text-[var(--yk-navy)] leading-tight">
          募集職種
        </h2>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {POSITIONS.map((p) => {
          const Icon = p.icon;
          return (
            <Card key={p.label} className="rounded-sm border-border">
              <CardContent className="p-7 space-y-5">
                <div className="flex items-center justify-between">
                  <div className="h-12 w-12 rounded-sm bg-[var(--yk-navy)] text-white flex items-center justify-center">
                    <Icon className="h-6 w-6" />
                  </div>
                  <Badge className="bg-[var(--yk-gold)] text-[var(--yk-navy-dark)] hover:bg-[var(--yk-gold)] rounded-sm font-mono-data text-[10px]">
                    {p.tagline}
                  </Badge>
                </div>
                <h3 className="font-headline text-xl font-black text-[var(--yk-navy)]">
                  {p.label}
                </h3>
                <div>
                  <div className="text-xs font-eyebrow text-[var(--yk-gold-dark)] mb-2">
                    仕事の魅力
                  </div>
                  <ul className="space-y-1.5">
                    {p.appeal.map((a) => (
                      <li
                        key={a}
                        className="flex items-start gap-2 text-sm text-[var(--yk-navy-dark)]"
                      >
                        <CheckCircle2 className="h-4 w-4 text-[var(--yk-gold)] shrink-0 mt-0.5" />
                        <span>{a}</span>
                      </li>
                    ))}
                  </ul>
                </div>
                <div>
                  <div className="text-xs font-eyebrow text-[var(--yk-gold-dark)] mb-2">
                    応募条件
                  </div>
                  <ul className="space-y-1.5">
                    {p.requirements.map((r) => (
                      <li
                        key={r}
                        className="flex items-start gap-2 text-sm text-[var(--yk-steel)]"
                      >
                        <span className="shrink-0 mt-1 h-1 w-1 rounded-full bg-[var(--yk-steel)]" />
                        <span>{r}</span>
                      </li>
                    ))}
                  </ul>
                </div>
                <div className="text-xs text-[var(--yk-steel)] bg-[var(--yk-navy)]/5 rounded-sm px-3 py-2">
                  給与・手当はご経験に応じて相談。下記フォームよりお気軽にお問い合わせください。
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </Section>
  );
}

function BenefitsSection() {
  return (
    <Section padding="xl" width="xl" className="bg-[var(--yk-navy)]/5">
      <div className="space-y-3 mb-10">
        <div className="flex items-center gap-3">
          <DiagonalDivider />
          <span className="font-eyebrow text-xs text-[var(--yk-gold-dark)]">
            Benefits
          </span>
        </div>
        <h2 className="font-headline text-3xl sm:text-4xl font-black text-[var(--yk-navy)] leading-tight">
          福利厚生
        </h2>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {BENEFITS.map((b) => (
          <div
            key={b.title}
            className="rounded-sm bg-white border border-border p-5 space-y-2"
          >
            <div className="font-headline font-bold text-[var(--yk-navy)]">
              {b.title}
            </div>
            <div className="text-sm text-[var(--yk-steel)]">{b.body}</div>
          </div>
        ))}
      </div>
    </Section>
  );
}

function VoicesSection() {
  return (
    <Section padding="xl" width="xl" className="bg-background">
      <div className="space-y-3 mb-10">
        <div className="flex items-center gap-3">
          <DiagonalDivider />
          <span className="font-eyebrow text-xs text-[var(--yk-gold-dark)]">
            Voices
          </span>
        </div>
        <h2 className="font-headline text-3xl sm:text-4xl font-black text-[var(--yk-navy)] leading-tight">
          社員の声（準備中）
        </h2>
        <p className="text-sm text-[var(--yk-steel)]">
          現場の整備士・事務スタッフのインタビューを順次公開予定です。
        </p>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {["整備士 A", "整備士 B", "事務 C"].map((name) => (
          <div
            key={name}
            className="rounded-sm border border-border bg-white p-7 space-y-3"
          >
            <div className="h-16 w-16 rounded-sm bg-[var(--yk-navy)]/10" />
            <div className="text-xs font-eyebrow text-[var(--yk-gold-dark)]">
              Coming soon
            </div>
            <div className="font-headline font-bold text-[var(--yk-navy)]">
              {name}
            </div>
            <p className="text-sm text-[var(--yk-steel)] leading-relaxed">
              現場の声を準備しています。働くイメージがより具体的になるよう近日公開予定です。
            </p>
          </div>
        ))}
      </div>
    </Section>
  );
}

function ApplyFormSection() {
  return (
    <Section padding="xl" width="md" className="bg-[var(--yk-navy)]/5">
      <div className="space-y-3 mb-8">
        <div className="flex items-center gap-3">
          <DiagonalDivider />
          <span className="font-eyebrow text-xs text-[var(--yk-gold-dark)]">
            Apply
          </span>
        </div>
        <h2 className="font-headline text-3xl font-black text-[var(--yk-navy)] leading-tight">
          応募・お問い合わせ
        </h2>
        <p className="text-sm text-[var(--yk-steel)] leading-relaxed">
          下記フォームよりお気軽にお問い合わせください。追って担当者よりご連絡いたします。
        </p>
      </div>
      <Card className="rounded-sm border-border">
        <CardContent className="p-6 sm:p-8">
          <InquiryForm
            scope="yoshikawa-tokuso-careers"
            fields={["name", "company", "email", "phone", "message"]}
            labels={{
              company: "現在のお勤め先（ある方のみ）",
              message: "ご希望職種・ご質問など",
            }}
            submitLabel="応募・問い合わせを送信"
            successMessage="ご応募を受け付けました。担当者より折り返しご連絡いたします。"
          />
        </CardContent>
      </Card>
      <div className="text-center mt-8">
        <Button
          asChild
          variant="outline"
          className="rounded-sm border-[var(--yk-navy)] text-[var(--yk-navy)]"
        >
          <Link href="/demo/yoshikawa-tokuso">
            ホームに戻る
            <ArrowRight className="h-4 w-4 ml-1.5" />
          </Link>
        </Button>
      </div>
    </Section>
  );
}
