import Link from "next/link";
import Image from "next/image";
import {
  ChevronRight,
  Wrench,
  GraduationCap,
  Briefcase,
  CheckCircle2,
  ArrowRight,
  ChevronDown,
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
    slug: "mechanic",
    icon: Wrench,
    label: "特装車 整備士",
    tagline: "経験者歓迎",
    salary: "月給 25万〜38万円",
    salaryNote: "経験・資格により優遇",
    appeal: [
      "主要メーカー指定工場で働く",
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
    slug: "trainee",
    icon: GraduationCap,
    label: "整備見習い",
    tagline: "未経験OK",
    salary: "月給 18万〜22万円",
    salaryNote: "3ヶ月試用期間は月給 17万円",
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
    slug: "office",
    icon: Briefcase,
    label: "事務・受付",
    tagline: "地域密着",
    salary: "月給 19万〜24万円",
    salaryNote: "経験により優遇・パート勤務も可",
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
  { slug: "insurance", title: "各種社会保険完備", body: "健康 / 厚生年金 / 雇用 / 労災" },
  { slug: "bonus", title: "賞与年2回", body: "業績連動（前年実績 2.5ヶ月分）" },
  { slug: "raise", title: "昇給年1回", body: "4月・業務評価による" },
  { slug: "uniform", title: "制服貸与", body: "作業着・安全靴・冬場の防寒着支給" },
  { slug: "qualification", title: "資格取得支援", body: "整備士資格の受験料・講習費用 全額会社負担" },
  { slug: "retirement", title: "退職金制度", body: "中小企業退職金共済に加入" },
  { slug: "commute", title: "家族手当・通勤手当", body: "通勤距離に応じて月 最大 25,000円" },
  { slug: "weekend", title: "週休2日", body: "日曜・祝日固定休 + 土曜は月1〜2回の交替休" },
  { slug: "vacation", title: "夏季・年末年始休暇", body: "各 5〜7日 / 年末年始は 12/30〜1/4" },
];

const VOICES = [
  {
    slug: "chief",
    role: "整備チーフ",
    name: "A.K.",
    years: "勤続22年 / 1級自動車整備士",
    photo: "/kikkawa/people/staff-chief.png",
    body: "新卒で入社してから、ずっと特装車ひとすじ。同じダンプでも車体年式や架装メーカーで構造が全然違う。毎日が勉強で飽きません。お客様の『助かった、ありがとう』の一言が、この仕事を続ける一番の理由です。",
    day: "朝イチの入庫車両の診断 → 午前中の作業計画 → 実作業 → 午後の電話相談対応 → 夕方の部品発注",
  },
  {
    slug: "mid",
    role: "整備士（中堅）",
    name: "T.M.",
    years: "勤続4年 / 2級自動車整備士",
    photo: "/kikkawa/people/staff-mid.png",
    body: "入社当時は油圧のゆの字も分からなかった自分が、今では若手に教える立場になりました。先輩が本当に丁寧に教えてくれるので、技術が身につくスピードが速い会社だと思います。特装車の奥深さを知ると、もう一般車の整備には戻れません。",
    day: "担当車両の定期点検 → 若手サポート → 研修参加 → メーカー技術情報のキャッチアップ",
  },
  {
    slug: "front",
    role: "フロント・事務",
    name: "H.S.",
    years: "勤続8年",
    photo: "/kikkawa/people/staff-front.png",
    body: "お客様からの電話を受けて、整備士に繋ぐ。単純に聞こえるかもしれませんが、車両情報を正しく聞き取って整理することで、修理のスピードが大きく変わります。自分の対応が、現場復帰の速さに直結する実感があります。",
    day: "問い合わせ電話・Webフォーム対応 → 見積作成 → 部品手配フォロー → 整備完了連絡",
  },
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
          <Link href="/artifacts/kittoku" className="hover:text-white">
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
        <h1 data-edit-id="kittoku-careers-hero-h1" className="font-headline text-4xl sm:text-5xl lg:text-6xl font-black leading-tight max-w-3xl">
          一緒に働く社員を、
          <br />
          募集中です。
        </h1>
        <p data-edit-id="kittoku-careers-hero-lead" className="text-white/80 mt-6 text-base leading-relaxed max-w-2xl">
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
        <h2 data-edit-id="kittoku-careers-positions-h2" className="font-headline text-3xl sm:text-4xl font-black text-[var(--yk-navy)] leading-tight">
          募集職種
        </h2>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {POSITIONS.map((p) => {
          const Icon = p.icon;
          return (
            <Card key={p.slug} className="rounded-sm border-border">
              <CardContent className="p-7 space-y-5">
                <div className="flex items-center justify-between">
                  <div className="h-12 w-12 rounded-sm bg-[var(--yk-navy)] text-white flex items-center justify-center">
                    <Icon className="h-6 w-6" />
                  </div>
                  <Badge data-edit-id={`kittoku-careers-positions-${p.slug}-tagline`} className="bg-[var(--yk-gold)] text-[var(--yk-navy-dark)] hover:bg-[var(--yk-gold)] rounded-sm font-mono-data text-[10px]">
                    {p.tagline}
                  </Badge>
                </div>
                <h3 data-edit-id={`kittoku-careers-positions-${p.slug}-h3`} className="font-headline text-xl font-black text-[var(--yk-navy)]">
                  {p.label}
                </h3>
                <div>
                  <div className="text-xs font-eyebrow text-[var(--yk-gold-dark)] mb-2">
                    応募条件
                  </div>
                  <ul className="space-y-1.5">
                    {p.requirements.map((r, idx) => (
                      <li
                        key={r}
                        className="flex items-start gap-2 text-sm text-[var(--yk-steel)]"
                      >
                        <span className="shrink-0 mt-1 h-1 w-1 rounded-full bg-[var(--yk-steel)]" />
                        <span data-edit-id={`kittoku-careers-positions-${p.slug}-requirements-${idx}`}>{r}</span>
                      </li>
                    ))}
                  </ul>
                </div>
                <div className="rounded-sm bg-[var(--yk-navy)]/5 border border-[var(--yk-navy)]/10 p-3 space-y-1">
                  <div className="text-[10px] font-eyebrow text-[var(--yk-gold-dark)]">
                    Salary
                  </div>
                  <div data-edit-id={`kittoku-careers-positions-${p.slug}-salary`} className="font-headline text-base font-black text-[var(--yk-navy)]">
                    {p.salary}
                  </div>
                  <div data-edit-id={`kittoku-careers-positions-${p.slug}-salary-note`} className="text-[11px] text-[var(--yk-steel)]">
                    {p.salaryNote}
                  </div>
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
        <h2 data-edit-id="kittoku-careers-benefits-h2" className="font-headline text-3xl sm:text-4xl font-black text-[var(--yk-navy)] leading-tight">
          福利厚生
        </h2>
      </div>
      <details className="group rounded-sm border border-border bg-white overflow-hidden">
        <summary className="cursor-pointer list-none flex items-center justify-between px-6 py-5 hover:bg-[var(--yk-navy)]/[0.02] transition-colors">
          <div className="flex items-center gap-3">
            <span className="font-headline font-bold text-[var(--yk-navy)]">
              福利厚生 全{BENEFITS.length}項目を見る
            </span>
            <span className="text-xs text-[var(--yk-steel)]">
              社会保険・賞与・休暇など
            </span>
          </div>
          <ChevronDown className="h-5 w-5 text-[var(--yk-navy)] group-open:rotate-180 transition-transform shrink-0" />
        </summary>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 p-6 pt-2 border-t border-border">
          {BENEFITS.map((b) => (
            <div
              key={b.slug}
              className="rounded-sm bg-[var(--yk-navy)]/[0.02] border border-border p-5 space-y-2"
            >
              <div data-edit-id={`kittoku-careers-benefits-${b.slug}-title`} className="font-headline font-bold text-[var(--yk-navy)]">
                {b.title}
              </div>
              <div data-edit-id={`kittoku-careers-benefits-${b.slug}-body`} className="text-sm text-[var(--yk-steel)]">{b.body}</div>
            </div>
          ))}
        </div>
      </details>
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
        <h2 data-edit-id="kittoku-careers-voices-h2" className="font-headline text-3xl sm:text-4xl font-black text-[var(--yk-navy)] leading-tight">
          現場スタッフの声
        </h2>
        <p data-edit-id="kittoku-careers-voices-lead" className="text-sm text-[var(--yk-steel)]">
          実際に働く整備士・事務スタッフがどんな気持ちで仕事に向き合っているか。
        </p>
      </div>
      <div className="flex md:grid md:grid-cols-3 overflow-x-auto md:overflow-visible snap-x snap-mandatory md:snap-none gap-4 md:gap-5 -mx-4 md:mx-0 px-[12.5%] md:px-0 pb-4 md:pb-0 scroll-smooth [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {VOICES.map((v) => (
          <Card key={v.slug} className="rounded-sm border-border overflow-hidden snap-center shrink-0 w-[85%] sm:w-[60%] md:w-auto md:shrink">
            <div className="aspect-[4/3] bg-[var(--yk-navy)]/5 relative">
              <Image
                data-edit-id={`kittoku-careers-voices-${v.slug}-photo`}
                src={v.photo}
                alt={`${v.role} ${v.name}`}
                fill
                className="object-cover"
                sizes="(max-width: 768px) 100vw, 33vw"
              />
            </div>
            <CardContent className="p-6 space-y-3">
              <div>
                <div data-edit-id={`kittoku-careers-voices-${v.slug}-role`} className="font-eyebrow text-[10px] text-[var(--yk-gold-dark)]">
                  {v.role}
                </div>
                <div data-edit-id={`kittoku-careers-voices-${v.slug}-name`} className="font-headline text-lg font-black text-[var(--yk-navy)]">
                  {v.name}
                </div>
                <div data-edit-id={`kittoku-careers-voices-${v.slug}-years`} className="text-xs text-[var(--yk-steel)] font-mono-data">
                  {v.years}
                </div>
              </div>
              <p data-edit-id={`kittoku-careers-voices-${v.slug}-body`} className="text-sm text-[var(--yk-navy-dark)] leading-relaxed">
                「{v.body}」
              </p>
              <div className="rounded-sm bg-[var(--yk-navy)]/5 p-3 text-xs">
                <div className="font-eyebrow text-[10px] text-[var(--yk-gold-dark)] mb-1">
                  A day in my work
                </div>
                <div data-edit-id={`kittoku-careers-voices-${v.slug}-day`} className="text-[var(--yk-navy-dark)] leading-relaxed">
                  {v.day}
                </div>
              </div>
            </CardContent>
          </Card>
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
        <h2 data-edit-id="kittoku-careers-apply-h2" className="font-headline text-3xl font-black text-[var(--yk-navy)] leading-tight">
          応募・お問い合わせ
        </h2>
        <p data-edit-id="kittoku-careers-apply-lead" className="text-sm text-[var(--yk-steel)] leading-relaxed">
          下記フォームよりお気軽にお問い合わせください。追って担当者よりご連絡いたします。
        </p>
      </div>
      <Card className="rounded-sm border-border">
        <CardContent className="p-6 sm:p-8">
          <InquiryForm
            scope="kittoku-careers"
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
          <Link data-edit-id="kittoku-careers-back-home" href="/artifacts/kittoku">
            ホームに戻る
            <ArrowRight className="h-4 w-4 ml-1.5" />
          </Link>
        </Button>
      </div>
    </Section>
  );
}
