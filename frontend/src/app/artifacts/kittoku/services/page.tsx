import { ArtifactLink as Link } from "@/components/artifacts/artifact-link";
import Image from "next/image";
import {
  ArrowRight,
  CheckCircle2,
  Wrench,
  ChevronRight,
  Award,
  Truck,
  Phone,
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

const ASSET_VERSION = process.env.NEXT_PUBLIC_ASSET_VERSION || "dev";

function versionedAsset(src: string): string {
  if (!ASSET_VERSION || !src.startsWith("/kikkawa/")) return src;
  const separator = src.includes("?") ? "&" : "?";
  return `${src}${separator}v=${ASSET_VERSION}`;
}

type ServiceItem = {
  slug: string;
  label: string;
  en: string;
  image: string;
  body: string;
  bullets?: string[];
  comingSoon?: boolean;
};

const SERVICES_PRIMARY: ServiceItem[] = [
  {
    slug: "repair",
    label: "整備・修理",
    en: "Maintenance & Repair",
    image: "/kikkawa/services-img/repair.jpg",
    body: "油圧・電装・機械部品の故障診断から修理まで。新明和工業をはじめ各メーカーの純正部品で確実に対応します。",
    bullets: [
      "油圧シリンダ・ポンプ修理",
      "PTO・サブエンジン不調",
      "架装板金・溶接補修",
      "電装系トラブル診断",
    ],
  },
  {
    slug: "parts",
    label: "正規部品販売",
    en: "Parts Sales",
    image: "/kikkawa/services-img/parts.jpg",
    body: "メーカー純正部品の特定・手配を一手に。車台番号と型式から最適な部品を素早くお探しします。",
    bullets: [
      "新明和工業 純正部品",
      "極東開発工業 部品対応",
      "特装系消耗部品在庫",
      "型式照合・代替部品提案",
    ],
  },
];

const SERVICES_SECONDARY: ServiceItem[] = [
  {
    slug: "lease",
    label: "リース",
    en: "Lease",
    image: "/kikkawa/services-img/lease.jpg",
    body: "業務車両のリース対応。短期から長期まで柔軟にご相談ください。",
  },
  {
    slug: "inspection",
    label: "点検",
    en: "Inspection",
    image: "/kikkawa/services-img/inspection.jpg",
    body: "法定点検・車検整備に加え、特装車特有の安全装置・油圧系統の定期点検を実施。",
  },
  {
    slug: "bodywork",
    label: "板金",
    en: "Bodywork",
    image: "/kikkawa/services-img/bodywork.jpg",
    body: "事故修理から日常的な凹み・傷の補修まで。架装板金・溶接補修にも対応します。",
  },
  {
    slug: "retrofit",
    label: "架装・改造",
    en: "Retrofit & Custom",
    image: "/kikkawa/services-img/retrofit.jpg",
    body: "パワーゲート架装、載せ替え工事、用途変更に伴う改造、構造変更申請まで一貫対応。",
  },
  {
    slug: "paint",
    label: "塗装",
    en: "Paint",
    image: "/kikkawa/services-img/paint.jpg",
    body: "車体全塗装・部分リペイント・ロゴリペイント・防錆処理を準備中です。",
    comingSoon: true,
  },
  {
    slug: "sales",
    label: "新車・中古車販売",
    en: "Vehicle Sales",
    image: "/kikkawa/services-img/sales.jpg",
    body: "整備済み中古特装車を最短1〜2週間で即納。新車納期にお困りの方へ。",
    comingSoon: true,
  },
  {
    slug: "tow",
    label: "レッカー",
    en: "Tow",
    image: "/kikkawa/services-img/tow.jpg",
    body: "現場での緊急対応として、レッカー牽引・搬送サービスを準備中です。",
    comingSoon: true,
  },
];

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

export const metadata = {
  title: "事業・サービス | 吉川特装",
  description:
    "特装車の整備・修理・点検・板金・架装・改造・部品販売など、吉川特装の事業内容と対応範囲をご紹介します。",
};

export default function ServicesPage() {
  return (
    <LpShell nav={<SiteNav />} footer={<SiteFooter />}>
      <PageHero />
      <ServicesGridSection />
      <VehicleListSection />
      <AchievementsSection />
      <ContactCtaSection />
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
          <span className="text-white">事業・サービス</span>
        </div>
        <div className="flex items-center gap-3 mb-4">
          <DiagonalDivider color="var(--yk-gold)" />
          <span className="font-eyebrow text-xs text-[var(--yk-gold)]">
            Services
          </span>
        </div>
        <h1
          data-edit-id="kittoku-services-hero-h1"
          className="font-headline text-4xl sm:text-5xl lg:text-6xl font-black leading-tight max-w-3xl"
        >故障しても大丈夫
すぐに現場復帰させます</h1>
        <p
          data-edit-id="kittoku-services-hero-lead"
          className="text-white/80 mt-6 text-base leading-relaxed max-w-2xl"
        >
          特装車の整備は、一般乗用車の整備とは別物です。メーカーごとの構造理解、専用工具、純正部品の手配ルート。
          すべてが揃って初めて、お客様の業務車両をすぐに現場復帰させられます。
        </p>
      </div>
    </section>
  );
}

function ServicesGridSection() {
  return (
    <Section padding="xl" width="xl" className="bg-[var(--yk-navy)]/[0.03]">
      <div className="space-y-3 mb-10">
        <div className="flex items-center gap-3">
          <DiagonalDivider />
          <span className="font-eyebrow text-xs text-[var(--yk-gold-dark)]">
            Services
          </span>
        </div>
        <h2 className="font-headline text-3xl sm:text-4xl lg:text-5xl font-black text-[var(--yk-navy)] tracking-tight leading-tight">
          事業内容
        </h2>
      </div>

      {/* メイン2 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">
        {SERVICES_PRIMARY.map((s) => (
          <ServiceDetailCard key={s.slug} item={s} large />
        ))}
      </div>

      {/* サブ7 */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {SERVICES_SECONDARY.map((s) => (
          <ServiceDetailCard key={s.slug} item={s} large={false} />
        ))}
      </div>
    </Section>
  );
}

function ServiceDetailCard({ item, large }: { item: ServiceItem; large: boolean }) {
  return (
    <div
      className={`relative bg-white border border-border rounded-sm overflow-hidden flex flex-col ${
        item.comingSoon ? "" : ""
      }`}
    >
      <div
        className={`relative ${large ? "aspect-[16/8]" : "aspect-[16/9]"} bg-[var(--yk-navy)]/5 overflow-hidden`}
      >
        <Image
          data-edit-id={`kittoku-services-card-${item.slug}-img`}
          src={versionedAsset(item.image)}
          alt={item.label}
          fill
          sizes={large ? "(max-width: 1024px) 100vw, 50vw" : "(max-width: 640px) 100vw, 33vw"}
          className={`object-cover ${item.comingSoon ? "opacity-60" : ""}`}
        />
        {item.comingSoon && (
          <span className="absolute top-3 right-3 bg-[var(--yk-gold)] text-[var(--yk-navy-dark)] text-[10px] font-mono-data font-bold px-2 py-0.5 rounded-sm tracking-wider">
            準備中
          </span>
        )}
      </div>
      <div className={`flex-1 ${large ? "p-7 sm:p-8" : "p-5 sm:p-6"} space-y-3`}>
        <div className="space-y-1">
          <div
            data-edit-id={`kittoku-services-card-${item.slug}-en`}
            className="font-eyebrow text-[10px] text-[var(--yk-gold-dark)]"
          >
            {item.en}
          </div>
          <h3
            data-edit-id={`kittoku-services-card-${item.slug}-label`}
            className={`font-headline font-black text-[var(--yk-navy)] leading-tight ${
              large ? "text-2xl sm:text-3xl" : "text-xl"
            }`}
          >
            {item.label}
          </h3>
        </div>
        <p
          data-edit-id={`kittoku-services-card-${item.slug}-body`}
          className={`text-[var(--yk-steel)] leading-relaxed ${large ? "text-sm sm:text-base" : "text-sm"}`}
        >
          {item.body}
        </p>
        {large && item.bullets && (
          <ul className="space-y-1.5 pt-1">
            {item.bullets.map((b) => (
              <li
                key={b}
                className="flex items-start gap-2 text-sm text-[var(--yk-navy-dark)]"
              >
                <CheckCircle2 className="h-4 w-4 text-[var(--yk-gold)] shrink-0 mt-0.5" />
                <span>{b}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function VehicleListSection() {
  const keys = Object.keys(VEHICLES) as VehicleKey[];
  return (
    <Section padding="xl" width="xl" className="bg-background">
      <div className="space-y-3 mb-12">
        <div className="flex items-center gap-3">
          <DiagonalDivider />
          <span className="font-eyebrow text-xs text-[var(--yk-gold-dark)]">
            Vehicles
          </span>
        </div>
        <h2 className="font-headline text-3xl sm:text-4xl font-black text-[var(--yk-navy)] leading-tight">
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
              <div className="aspect-[4/3] relative bg-[var(--yk-navy)]/[0.03] overflow-hidden">
                <Image
                  src={v.image}
                  alt={v.label}
                  fill
                  className="object-cover"
                  sizes="(max-width: 640px) 50vw, 33vw"
                />
              </div>
              <div className="p-5 space-y-2">
                <h3 className="font-headline font-bold text-[var(--yk-navy)]">
                  {v.label}
                </h3>
                <p className="text-xs text-[var(--yk-steel)] leading-relaxed">
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
          <h2 className="font-headline text-3xl sm:text-4xl font-black text-[var(--yk-navy)] leading-tight">
            直近の整備実績
          </h2>
          <p className="text-sm text-[var(--yk-steel)] max-w-md leading-relaxed">
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
              <div className="absolute left-3 top-3 bg-[var(--yk-navy)] text-white rounded-sm px-2 py-0.5 text-[10px] font-bold">
                {a.badge}
              </div>
            </div>
            <CardContent className="p-6 space-y-4">
              <div className="space-y-1">
                <div className="font-headline font-bold text-[var(--yk-navy)]">
                  {a.client}
                </div>
                <div className="text-xs text-[var(--yk-steel)]">
                  {a.vehicle}
                </div>
              </div>
              <div className="space-y-3 text-sm">
                <div>
                  <div className="font-eyebrow text-[10px] text-[var(--yk-gold-dark)] mb-1">
                    課題
                  </div>
                  <p className="text-[var(--yk-navy-dark)] leading-relaxed">
                    {a.problem}
                  </p>
                </div>
                <div>
                  <div className="font-eyebrow text-[10px] text-[var(--yk-gold-dark)] mb-1">
                    対応
                  </div>
                  <p className="text-[var(--yk-navy-dark)] leading-relaxed">
                    {a.solution}
                  </p>
                </div>
              </div>
              <div className="rounded-sm bg-[var(--yk-navy)] text-white px-4 py-2.5 text-sm font-bold">
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

function ContactCtaSection() {
  return (
    <section className="relative overflow-hidden bg-[var(--yk-navy)] text-white">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_78%_35%,rgba(255,196,0,0.16),transparent_30%)]" />
      <div className="relative mx-auto max-w-5xl px-4 sm:px-6 py-16 sm:py-24 text-center">
        <div className="flex items-center justify-center gap-3 mb-4">
          <DiagonalDivider color="var(--yk-gold)" />
          <span className="font-eyebrow text-xs text-[var(--yk-gold)]">Contact</span>
        </div>
        <h2
          data-edit-id="kittoku-services-contact-h2"
          className="font-headline text-3xl sm:text-4xl lg:text-5xl font-black leading-tight"
        >
          お問い合わせ
        </h2>
        <p className="text-white/80 mt-5 max-w-2xl mx-auto text-sm sm:text-base leading-relaxed">
          修理・整備で急ぎの方はお電話、 部品注文は LINE か WEB フォームが便利です。
        </p>
        <div className="mt-8 flex flex-col sm:flex-row gap-3 justify-center">
          <Button
            asChild
            size="lg"
            className="bg-[var(--yk-gold)] hover:bg-[var(--yk-gold-dark)] text-[var(--yk-navy-dark)] font-bold rounded-sm h-12 px-6"
          >
            <Link href="/artifacts/kittoku/contact">
              お問い合わせはこちら
              <ArrowRight className="h-5 w-5 ml-2" />
            </Link>
          </Button>
          <Button
            asChild
            size="lg"
            variant="outline"
            className="border-white/40 hover:border-white text-white hover:bg-white/10 hover:text-white font-bold rounded-sm h-12 px-6 bg-transparent"
          >
            <a href="tel:0859-27-4885">
              <Phone className="h-5 w-5 mr-2" />
              0859-27-4885
            </a>
          </Button>
        </div>
      </div>
    </section>
  );
}
