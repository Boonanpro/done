import Link from "next/link";
import Image from "next/image";
import {
  ArrowRight,
  CheckCircle2,
  Wrench,
  FileSearch,
  PackageCheck,
  Truck,
  ChevronRight,
  Award,
} from "lucide-react";
import { LpShell } from "@/components/templates/lp-shell";
import { Section } from "@/components/templates/section";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { SiteNav } from "../components/site-nav";
import { SiteFooter } from "../components/site-footer";
import { DiagonalDivider } from "../components/diagonal-divider";
import { VEHICLES, type VehicleKey } from "../components/vehicle-icons";
import { ServiceVideoCard } from "../components/service-video-card";

const ACHIEVEMENTS = [
  {
    slug: "garbage",
    icon: Truck,
    illustration: "/kikkawa/cases/case1-garbage.png",
    badge: "緊急対応",
    client: "鳥取県内 清掃事業 A社",
    vehicle: "新明和製 塵芥車（パッカー車）",
    problem: "回転板の動作不良で収集業務が半日停止。緊急対応が必要。",
    solution:
      "当日中に現地訪問、油圧ポンプの交換とリミットスイッチ調整を実施。翌朝には業務復帰完了。",
    result: "収集業務の停止を1日のみに抑制",
  },
  {
    slug: "crane",
    icon: Wrench,
    illustration: "/kikkawa/cases/case2-crane.png",
    badge: "計画点検",
    client: "島根県内 建設業 B社",
    vehicle: "タダノ製 4tラフテレーンクレーン",
    problem: "年次点検が期日ギリギリ。繁忙期に重ならないタイミングで実施希望。",
    solution:
      "休日を活用した計画点検を提案。ブーム・ウインチ・旋回部の分解点検と、摩耗部品の先行交換まで実施。",
    result: "稼働ロスゼロで年次点検を完了",
  },
  {
    slug: "tailgate",
    icon: Award,
    illustration: "/kikkawa/cases/case3-tailgate.png",
    badge: "年間契約",
    client: "岡山県内 運送業 C社",
    vehicle: "三菱ふそう+新明和テールゲートリフタ搭載車 × 8台",
    problem: "車両増車でテールゲートリフタの定期点検コストが読めない。",
    solution:
      "全8台を対象にした年間メンテナンス契約を提案。月2台ペースでの分散点検プランで稼働影響を最小化。",
    result: "年間整備コストを15%削減・稼働停止はゼロ",
  },
];

const SERVICE_CATEGORIES = [
  {
    slug: "repair",
    icon: Wrench,
    video: "/kikkawa/services/repair.mp4",
    eyebrow: "Repair",
    title: "整備・修理",
    body: "油圧・電装・機械部品の故障診断から修理、架装ごとの専門修理まで。取扱メーカー各社の純正部品と指定工場としての整備ノウハウで対応します。",
    items: [
      "油圧シリンダ / ポンプ修理",
      "PTO・サブエンジン不調",
      "架装板金・溶接補修",
      "電装系トラブル診断",
    ],
  },
  {
    slug: "inspection",
    icon: FileSearch,
    video: "/kikkawa/services/inspection.mp4",
    eyebrow: "Inspection",
    title: "点検・検査",
    body: "法定点検・車検整備に加え、特装車特有の安全装置・リミットスイッチ・油圧系統の定期点検を実施します。",
    items: [
      "3ヶ月・6ヶ月・12ヶ月点検",
      "テールゲートリフタ定期点検",
      "高所作業車 年次点検",
      "クレーン年次点検・月次点検",
    ],
  },
  {
    slug: "parts",
    icon: PackageCheck,
    video: "/kikkawa/services/parts.mp4",
    eyebrow: "Parts",
    title: "純正部品の手配",
    body: "車台番号と型式から最適な部品を特定し、メーカー純正部品を迅速に手配。過去整備履歴もお伝えします。",
    items: [
      "取扱メーカー各社 純正部品",
      "極東開発工業 部品対応",
      "特装系消耗部品在庫",
      "型式照合・代替部品提案",
    ],
  },
  {
    slug: "retrofit",
    icon: Truck,
    video: "/kikkawa/services/retrofit.mp4" as string | undefined,
    eyebrow: "Retrofit",
    title: "架装・改造",
    body: "既存車両への追加架装や、用途変更に伴う改造も対応。構造変更申請まで一貫してサポートします。",
    items: [
      "テールゲート追加架装",
      "荷台・あおり交換",
      "ステンレスタンク架装修理",
      "改造申請サポート",
    ],
  },
];

export const metadata = {
  title: "事業・サービス | 吉川特装",
  description:
    "特装車の整備・修理・点検・架装・純正部品手配など、吉川特装の対応範囲をご紹介します。",
};

export default function ServicesPage() {
  return (
    <LpShell nav={<SiteNav />} footer={<SiteFooter />}>
      <PageHero />
      <CategoriesSection />
      <VehicleListSection />
      <AchievementsSection />
      <ComingSoonSection />
      <FlowReminderSection />
    </LpShell>
  );
}

function AchievementsSection() {
  return (
    <Section padding="xl" width="xl" className="bg-[var(--yk-navy)]/5">
      <div className="space-y-3 mb-12">
        <div className="flex items-center gap-3">
          <DiagonalDivider />
          <span className="font-eyebrow text-xs text-[var(--yk-gold-dark)]">
            Achievements
          </span>
        </div>
        <div className="flex flex-col lg:flex-row lg:items-end lg:justify-between gap-4">
          <h2 data-edit-id="kittoku-services-achievements-h2" className="font-headline text-3xl sm:text-4xl font-black text-[var(--yk-navy)] leading-tight">
            直近の整備実績
          </h2>
          <p data-edit-id="kittoku-services-achievements-lead" className="text-sm text-[var(--yk-steel)] max-w-md leading-relaxed">
            中国地方のお客様に、それぞれの事情に応じた整備でお応えしています。
          </p>
        </div>
      </div>
      <div className="flex lg:grid lg:grid-cols-3 overflow-x-auto lg:overflow-visible snap-x snap-mandatory lg:snap-none gap-4 lg:gap-5 -mx-4 lg:mx-0 px-[12.5%] lg:px-0 pb-4 lg:pb-0 scroll-smooth [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {ACHIEVEMENTS.map((a, i) => (
          <Card
            key={a.slug}
            className="rounded-sm border-border bg-white relative overflow-hidden snap-center shrink-0 w-[85%] sm:w-[60%] lg:w-auto lg:shrink"
          >
            <div className="relative aspect-[4/3] bg-[var(--yk-gold)]/10 overflow-hidden">
              <Image
                data-edit-id={`kittoku-services-achievements-${a.slug}-img`}
                src={a.illustration}
                alt={`${a.client} のケース`}
                fill
                className="object-contain p-4"
                sizes="(max-width: 1024px) 100vw, 33vw"
              />
              <Badge
                variant="outline"
                className="absolute top-3 right-3 rounded-sm text-[10px] border-[var(--yk-gold)]/60 text-[var(--yk-gold-dark)] font-mono-data bg-white/90"
              >
                CASE 0{i + 1}
              </Badge>
              <div data-edit-id={`kittoku-services-achievements-${a.slug}-badge`} className="absolute left-3 top-3 bg-[var(--yk-navy)] text-white rounded-sm px-2 py-0.5 text-[10px] font-bold">
                {a.badge}
              </div>
            </div>
            <CardContent className="p-6 space-y-4">
              <div className="space-y-1">
                <div data-edit-id={`kittoku-services-achievements-${a.slug}-client`} className="font-headline font-bold text-[var(--yk-navy)]">
                  {a.client}
                </div>
                <div data-edit-id={`kittoku-services-achievements-${a.slug}-vehicle`} className="text-xs text-[var(--yk-steel)]">
                  {a.vehicle}
                </div>
              </div>
              <div className="space-y-3 text-sm">
                <div>
                  <div className="font-eyebrow text-[10px] text-[var(--yk-gold-dark)] mb-1">
                    課題
                  </div>
                  <p data-edit-id={`kittoku-services-achievements-${a.slug}-problem`} className="text-[var(--yk-navy-dark)] leading-relaxed">
                    {a.problem}
                  </p>
                </div>
                <div>
                  <div className="font-eyebrow text-[10px] text-[var(--yk-gold-dark)] mb-1">
                    対応
                  </div>
                  <p data-edit-id={`kittoku-services-achievements-${a.slug}-solution`} className="text-[var(--yk-navy-dark)] leading-relaxed">
                    {a.solution}
                  </p>
                </div>
              </div>
              <div data-edit-id={`kittoku-services-achievements-${a.slug}-result`} className="rounded-sm bg-[var(--yk-navy)] text-white px-4 py-2.5 text-sm font-bold">
                → {a.result}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
      <div className="mt-6 text-xs text-[var(--yk-steel)]">
        ※ 守秘の観点から、企業名・車両番号はイニシャル表記としております。
      </div>
    </Section>
  );
}

function ComingSoonSection() {
  const PLANS = [
    {
      slug: "paint",
      eyebrow: "Coming Soon",
      tag: "2026年内 開始予定",
      title: "特装車 塗装サービス",
      lead: "働く車を、新車同様の艶へ。",
      body: "現場で酷使され、塗装の退色・傷・錆が目立つ特装車を、新車同様の美しい状態に蘇らせる塗装サービスを準備中です。\nブランドロゴや企業カラーのリペイントも承ります。",
      bullets: [
        "車体全塗装／部分リペイント",
        "ロゴ・社名・カラーリングの塗り替え",
        "防錆下地処理からクリアコートまで一貫対応",
      ],
      value: "古くなった車両イメージも、きれいな外観で企業の信頼感アップに",
    },
    {
      slug: "used-sales",
      eyebrow: "Coming Soon",
      tag: "仕入体制準備中",
      title: "中古特装車 販売",
      lead: "新品同様の特装車を、即納車。",
      body: "新車の納期が半年〜1年かかる特装車を、整備済みの良質な中古車として迅速に納車する販売サービスを準備中です。\n当社認定整備済みなので、納車後もそのまま安心してお使いいただけます。",
      bullets: [
        "納期1〜2週間での即納可能",
        "当社認定整備済み・保証付き",
        "旧車両の下取り同時対応",
      ],
      value: "急な車両更新や増車にも、即対応",
    },
  ];
  return (
    <Section padding="xl" width="xl" className="bg-background">
      <div className="space-y-3 mb-12">
        <div className="flex items-center gap-3">
          <DiagonalDivider />
          <span className="font-eyebrow text-xs text-[var(--yk-gold-dark)]">
            Upcoming Services
          </span>
        </div>
        <div className="flex flex-col lg:flex-row lg:items-end lg:justify-between gap-4">
          <h2 data-edit-id="kittoku-services-coming-h2" className="font-headline text-3xl sm:text-4xl font-black text-[var(--yk-navy)] leading-tight">
            これから始まる、
            <br className="sm:hidden" />
            新しいサービス。
          </h2>
          <p data-edit-id="kittoku-services-coming-lead" className="text-[var(--yk-steel)] max-w-md leading-relaxed text-sm">
            こちらのサービスは準備中です。
            <br />
            ご関心があるお客様はお問い合わせよりご一報ください。
          </p>
        </div>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {PLANS.map((p) => (
          <Card
            key={p.slug}
            className="rounded-sm border-[var(--yk-gold)]/40 border-2 overflow-hidden relative"
          >
            <div data-edit-id={`kittoku-services-coming-${p.slug}-tag`} className="absolute top-0 right-0 bg-[var(--yk-gold)] text-[var(--yk-navy-dark)] text-[10px] font-mono-data font-bold px-3 py-1 tracking-wider">
              {p.tag}
            </div>
            <CardContent className="p-8 space-y-5">
              <div className="space-y-2">
                <div data-edit-id={`kittoku-services-coming-${p.slug}-eyebrow`} className="font-eyebrow text-xs text-[var(--yk-gold-dark)]">
                  {p.eyebrow}
                </div>
                <h3 data-edit-id={`kittoku-services-coming-${p.slug}-h3`} className="font-headline text-2xl font-black text-[var(--yk-navy)] leading-tight">
                  {p.title}
                </h3>
                <div data-edit-id={`kittoku-services-coming-${p.slug}-lead`} className="text-sm font-headline font-bold text-[var(--yk-gold-dark)]">
                  {p.lead}
                </div>
              </div>
              <p data-edit-id={`kittoku-services-coming-${p.slug}-body`} className="text-sm text-[var(--yk-steel)] leading-relaxed whitespace-pre-line">
                {p.body}
              </p>
              <ul className="space-y-1.5">
                {p.bullets.map((b, idx) => (
                  <li
                    key={b}
                    className="flex items-start gap-2 text-sm text-[var(--yk-navy-dark)]"
                  >
                    <CheckCircle2 className="h-4 w-4 text-[var(--yk-gold)] shrink-0 mt-0.5" />
                    <span data-edit-id={`kittoku-services-coming-${p.slug}-bullets-${idx}`}>{b}</span>
                  </li>
                ))}
              </ul>
              <div className="rounded-sm bg-[var(--yk-navy)]/5 border border-[var(--yk-navy)]/10 px-4 py-3 text-sm">
                <span className="font-eyebrow text-[10px] text-[var(--yk-gold-dark)] block mb-1">
                  お客様への価値
                </span>
                <span data-edit-id={`kittoku-services-coming-${p.slug}-value`} className="text-[var(--yk-navy-dark)]">{p.value}</span>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </Section>
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
          <span className="text-white">事業・サービス</span>
        </div>
        <div className="flex items-center gap-3 mb-4">
          <DiagonalDivider color="var(--yk-gold)" />
          <span className="font-eyebrow text-xs text-[var(--yk-gold)]">
            Services
          </span>
        </div>
        <h1 data-edit-id="kittoku-services-hero-h1" className="font-headline text-4xl sm:text-5xl lg:text-6xl font-black leading-tight max-w-3xl">
          整備・修理・点検・架装。
          <br />
          すべてご対応します
        </h1>
        <p data-edit-id="kittoku-services-hero-lead" className="text-white/80 mt-6 text-base leading-relaxed max-w-2xl">
          特装車の整備は、一般乗用車の整備とは別物です。メーカーごとの構造理解、専用工具、純正部品の手配ルート。
          すべてが揃って初めて、お客様の業務車両をすぐに現場復帰させられます。
        </p>
      </div>
    </section>
  );
}

function CategoriesSection() {
  return (
    <Section padding="xl" width="xl" className="bg-background">
      <div className="space-y-3 mb-14">
        <div className="flex items-center gap-3">
          <DiagonalDivider />
          <span className="font-eyebrow text-xs text-[var(--yk-gold-dark)]">
            Category
          </span>
        </div>
        <h2 data-edit-id="kittoku-services-categories-h2" className="font-headline text-3xl sm:text-4xl font-black text-[var(--yk-navy)] leading-tight">
          対応する4つの領域
        </h2>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {SERVICE_CATEGORIES.map((cat) => {
          const Icon = cat.icon;
          const catSlug = cat.slug;
          return (
            <Card key={cat.title} className="border-border rounded-sm overflow-hidden flex flex-col">
              {cat.video ? (
                <ServiceVideoCard src={cat.video} alt={cat.title} />
              ) : (
                <div className="relative aspect-[16/9] bg-gradient-to-br from-[var(--yk-navy)]/10 to-[var(--yk-navy)]/[0.03] flex items-center justify-center">
                  <Icon className="h-16 w-16 text-[var(--yk-navy)]/30" />
                </div>
              )}
              <CardContent className="p-8 space-y-6 flex-1">
                <div className="flex items-start justify-between">
                  <div className="space-y-2">
                    <div data-edit-id={`kittoku-services-categories-${catSlug}-eyebrow`} className="font-eyebrow text-xs text-[var(--yk-gold-dark)]">
                      {cat.eyebrow}
                    </div>
                    <h3 data-edit-id={`kittoku-services-categories-${catSlug}-h3`} className="font-headline text-2xl font-black text-[var(--yk-navy)] leading-tight">
                      {cat.title}
                    </h3>
                  </div>
                  <div className="h-12 w-12 rounded-sm bg-[var(--yk-navy)] text-white flex items-center justify-center shrink-0">
                    <Icon className="h-6 w-6" />
                  </div>
                </div>
                <p data-edit-id={`kittoku-services-categories-${catSlug}-body`} className="text-sm text-[var(--yk-steel)] leading-relaxed">
                  {cat.body}
                </p>
                <ul className="space-y-2">
                  {cat.items.map((item, idx) => (
                    <li
                      key={item}
                      className="flex items-start gap-2 text-sm text-[var(--yk-navy-dark)]"
                    >
                      <CheckCircle2 className="h-4 w-4 text-[var(--yk-gold)] shrink-0 mt-0.5" />
                      <span data-edit-id={`kittoku-services-categories-${catSlug}-items-${idx}`}>{item}</span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </Section>
  );
}

function VehicleListSection() {
  const keys = Object.keys(VEHICLES) as VehicleKey[];
  return (
    <Section padding="xl" width="xl" className="bg-[var(--yk-navy)]/5">
      <div className="space-y-3 mb-12">
        <div className="flex items-center gap-3">
          <DiagonalDivider />
          <span className="font-eyebrow text-xs text-[var(--yk-gold-dark)]">
            Vehicles
          </span>
        </div>
        <h2 data-edit-id="kittoku-services-vehicles-h2" className="font-headline text-3xl sm:text-4xl font-black text-[var(--yk-navy)] leading-tight">
          対応できる車種
        </h2>
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-3 sm:gap-5">
        {keys.map((key) => {
          const v = VEHICLES[key];
          return (
            <div
              key={key}
              className="bg-white border border-border rounded-sm overflow-hidden"
            >
              <div className="aspect-[4/3] relative bg-[var(--yk-navy)]/[0.03]">
                <Image
                  data-edit-id={`kittoku-services-vehicles-${key}-img`}
                  src={v.image}
                  alt={v.label}
                  fill
                  className="object-cover"
                  sizes="(max-width: 640px) 100vw, (max-width: 1024px) 50vw, 33vw"
                />
              </div>
              <div className="p-5 space-y-2">
                <h3 data-edit-id={`kittoku-services-vehicles-${key}-title`} className="font-headline font-bold text-[var(--yk-navy)]">
                  {v.label}
                </h3>
                <p data-edit-id={`kittoku-services-vehicles-${key}-body`} className="text-xs text-[var(--yk-steel)] leading-relaxed">
                  {v.description}
                </p>
              </div>
            </div>
          );
        })}
      </div>
    </Section>
  );
}

function FlowReminderSection() {
  return (
    <Section padding="xl" width="xl" className="bg-background">
      <Card className="border-border rounded-sm overflow-hidden">
        <div className="grid grid-cols-1 lg:grid-cols-2">
          <div className="p-10 bg-[var(--yk-navy)] text-white space-y-5">
            <div className="flex items-center gap-3">
              <DiagonalDivider color="var(--yk-gold)" />
              <span className="font-eyebrow text-xs text-[var(--yk-gold)]">
                Before you call
              </span>
            </div>
            <h2 data-edit-id="kittoku-services-flow-h2" className="font-headline text-3xl font-black leading-tight">
              ご依頼は
              <br />
              お問い合わせください
            </h2>
            <p data-edit-id="kittoku-services-flow-lead" className="text-white/80 leading-relaxed">
              特装車の部品特定には、いくつか固有の情報が必要です。お手元にご用意いただくとスムーズにご案内できます。
            </p>
          </div>
          <div className="p-10 space-y-5">
            <ul className="space-y-4">
              {[
                {
                  slug: "shaken",
                  t: "車検証",
                  b: "車台番号 / 型式 / 類別区分番号 / 初度登録年月",
                },
                {
                  slug: "maker",
                  t: "架装メーカーと型式",
                  b: "車体後部や側面のメーカー銘板に記載",
                },
                {
                  slug: "media",
                  t: "破損箇所の画像・動画",
                  b: "遠景と近景を2〜3枚ずつ。音があれば動画で",
                },
              ].map((item, i) => (
                <li key={item.slug} className="flex items-start gap-4">
                  <span data-edit-id={`kittoku-services-flow-prep-${item.slug}-num`} className="font-mono-data text-2xl font-black text-[var(--yk-gold-dark)] tabular-nums min-w-[2.5rem]">
                    0{i + 1}
                  </span>
                  <div>
                    <div data-edit-id={`kittoku-services-flow-prep-${item.slug}-title`} className="font-headline font-bold text-[var(--yk-navy)]">
                      {item.t}
                    </div>
                    <div data-edit-id={`kittoku-services-flow-prep-${item.slug}-body`} className="text-sm text-[var(--yk-steel)]">
                      {item.b}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
            <Button
              asChild
              className="bg-[var(--yk-navy)] hover:bg-[var(--yk-navy-dark)] text-white rounded-sm"
            >
              <Link data-edit-id="kittoku-services-flow-cta" href="/artifacts/kittoku/contact">
                Webで問い合わせる
                <ArrowRight className="h-4 w-4 ml-1.5" />
              </Link>
            </Button>
          </div>
        </div>
      </Card>
    </Section>
  );
}
