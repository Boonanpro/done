import Link from "next/link";
import Image from "next/image";
import {
  Phone,
  ArrowRight,
  Award,
  MapPin,
  Clock,
  Zap,
  Wrench,
  Users,
  ChevronRight,
} from "lucide-react";
import { LpShell } from "@/components/templates/lp-shell";
import { Section } from "@/components/templates/section";
import { LocationMap } from "@/components/templates/location-map";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { SiteNav } from "./components/site-nav";
import { SiteFooter } from "./components/site-footer";
import { Logo } from "./components/logo";
import { CertifiedBadge } from "./components/certified-badge";
import { DiagonalDivider } from "./components/diagonal-divider";
import { HeroVideo } from "./components/hero-video";
import { VEHICLES, type VehicleKey } from "./components/vehicle-icons";

// 動画/画像にバージョンクエリを付けて、ブラウザ強キャッシュを破棄する。
// next.config.ts で git commit SHA から build-time に注入される。
const ASSET_VERSION = process.env.NEXT_PUBLIC_ASSET_VERSION || "dev";
const HERO_VIDEO = `/kikkawa/hero.mp4?v=${ASSET_VERSION}`;
// poster は動画の1フレーム目を使う。元の hero.png（整備士のクローズアップ静止画）を出すと
// 動画ロード前に「全く違う絵」がチラ見えする問題が起きるため。
const HERO_POSTER = `/kikkawa/hero-poster.jpg?v=${ASSET_VERSION}`;

const STATS = [
  { slug: "founded", label: "創業", value: "1988", unit: "年", hint: "37年以上の整備実績" },
  { slug: "vehicles", label: "対応車種", value: "9", unit: "機種", hint: "特装車全機種カバー" },
  { slug: "certified", label: "認定工場", value: "新明和", unit: "認定", hint: "指定サービス工場" },
];

const STRENGTHS = [
  {
    slug: "shinmeiwa",
    icon: Award,
    title: "新明和工業 認定修理工場",
    body: "特装車のリーディングメーカー、新明和工業の指定サービス工場としてメーカー純正部品と正規の整備ノウハウで対応します。",
  },
  {
    slug: "all-models",
    icon: Wrench,
    title: "特装車 全機種に対応",
    body: "塵芥車・ダンプ・クレーン・テールゲートリフタ・ローリ・高所作業車・ミキサ・飼料運搬車・脱着車まで、働く車のすべてを。",
  },
  {
    slug: "fast-response",
    icon: Zap,
    title: "山陰から中国地方へ最短対応",
    body: "米子を拠点に鳥取・島根・岡山・広島・山口へ出張整備も可能。止まっては困る業務車両を最短で現場復帰させます。",
  },
];

const MANUFACTURERS: {
  slug: string;
  name: string;
  en: string;
  logo?: string;
  siteUrl?: string;
  accent?: boolean;
  logoStyle?: React.CSSProperties;
}[] = [
  {
    slug: "shinmaywa",
    name: "新明和工業",
    en: "SHINMAYWA INDUSTRIES",
    logo: "/kikkawa/manufacturers/shinmaywa.svg",
    siteUrl: "https://www.shinmaywa.co.jp/",
    accent: true,
    logoStyle: { width: "146px", height: "auto", objectPosition: "69.9% 35.1%" },
  },
  {
    slug: "iwasaki",
    name: "岩崎工業",
    en: "IWASAKI KOGYO",
    logo: "/kikkawa/manufacturers/iwasaki-kogyo.svg",
    siteUrl: "https://www.iwasaki-kogyo.co.jp/",
    logoStyle: { width: "180px", height: "auto" },
  },
  {
    slug: "fujita",
    name: "フジタ自動車工業",
    en: "FUJITA AUTOBODY",
    logo: "/kikkawa/manufacturers/fujita.png",
    siteUrl: "https://fujitabody.co.jp/",
    logoStyle: { width: "190px", height: "auto" },
  },
  {
    slug: "toyo-sharyo",
    name: "東洋車輌",
    en: "TOYO SHARYO",
    logo: "/kikkawa/manufacturers/toyo-sharyo.png",
    siteUrl: "https://toyosyaryo.com/",
    logoStyle: { width: "180px", height: "auto" },
  },
  {
    slug: "y-eng",
    name: "ワイ・エンジニアリング",
    en: "Y ENGINEERING",
    logo: "/kikkawa/manufacturers/y-eng.png",
    siteUrl: "http://www.yeng.co.jp/",
    logoStyle: { width: "190px", height: "auto" },
  },
  {
    slug: "furukawa-unic",
    name: "古河ユニック",
    en: "FURUKAWA UNIC",
    logo: "/kikkawa/manufacturers/furukawa-unic.png",
    siteUrl: "https://www.furukawaunic.co.jp/",
    logoStyle: { width: "142px", height: "auto" },
  },
  {
    slug: "pabco",
    name: "パブコ",
    en: "PABCO",
    logo: "/kikkawa/manufacturers/pabco.png",
    siteUrl: "https://www.pabco.co.jp/",
    logoStyle: { width: "150px", height: "auto" },
  },
  {
    slug: "cargotec",
    name: "カーゴテック・ジャパン",
    en: "CARGOTEC JAPAN (HIAB)",
    logo: "/kikkawa/manufacturers/hiab-japan.svg",
    siteUrl: "https://www.hiab.com/ja/",
    logoStyle: { width: "auto", height: "75px", maxHeight: "75px" },
  },
  {
    slug: "maeda",
    name: "前田製作所",
    en: "MAEDA SEISAKUSHO",
    logo: "/kikkawa/manufacturers/maeda.png",
    siteUrl: "https://www.maesei.co.jp/",
    logoStyle: { width: "180px", height: "auto" },
  },
  {
    slug: "nihon-fruehauf",
    name: "日本フルハーフ",
    en: "NIHON FRUEHAUF",
    logo: "/kikkawa/manufacturers/nihon-fruehauf.png",
    siteUrl: "https://www.fruehauf.co.jp/",
    logoStyle: { width: "180px", height: "auto" },
  },
  {
    slug: "kanematsu-eng",
    name: "兼松エンジニアリング",
    en: "KANEMATSU ENGINEERING",
    logo: "/kikkawa/manufacturers/kanematsu-eng.png",
    siteUrl: "https://www.kanematsu-eng.jp/",
    logoStyle: { width: "200px", height: "auto" },
  },
  {
    slug: "snow-systems",
    name: "スノーシステムズ",
    en: "SNOW SYSTEMS",
    logo: "/kikkawa/manufacturers/snow-systems.svg",
    siteUrl: "http://www.snowsystems.co.jp/",
    logoStyle: { width: "180px", height: "auto" },
  },
  {
    slug: "nippon-trex",
    name: "日本トレクス",
    en: "NIPPON TREX",
    logo: "/kikkawa/manufacturers/nippon-trex.png",
    siteUrl: "https://www.trex.co.jp/",
    logoStyle: { width: "180px", height: "auto" },
  },
  {
    slug: "miller-japan",
    name: "ミラージャパン",
    en: "MILLER JAPAN",
    logo: "/kikkawa/manufacturers/miller-japan.png",
    siteUrl: "https://www.millerjapan.com/",
    logoStyle: { width: "180px", height: "auto" },
  },
  {
    slug: "toho-sharyo",
    name: "東邦車輛",
    en: "TOHO SHARYO",
    logo: "/kikkawa/manufacturers/toho-sharyo.png",
    siteUrl: "https://www.shinmaywa.co.jp/toho/",
    logoStyle: { width: "200px", height: "auto" },
  },
  {
    slug: "morita-econos",
    name: "モリタエコノス",
    en: "MORITA ECONOS",
    logo: "/kikkawa/manufacturers/morita-econos.png",
    siteUrl: "https://www.morita-econos.com/",
    logoStyle: { width: "180px", height: "auto" },
  },
];

export const metadata = {
  title: "吉川特装 | 新明和工業 認定修理工場（米子）",
  description:
    "鳥取県米子市の特装車専門整備工場。新明和工業の認定修理工場としてダンプ・塵芥車・テールゲートリフタ・クレーン・ローリ・高所作業車などの整備・修理・点検に対応。",
};

export default function YoshikawaHomePage() {
  return (
    <LpShell
      nav={<SiteNav />}
      footer={<SiteFooter />}
      className="bg-background text-foreground"
    >
      <HeroSection />
      <StatsSection />
      <ManufacturersSection />
      <VehiclesSection />
      <FlowSection />
      <CareersCtaSection />
    </LpShell>
  );
}

/* ───────────────────────── Sections ───────────────────────── */

function HeroSection() {
  return (
    <section className="relative overflow-hidden">
      <HeroVideo src={HERO_VIDEO} poster={HERO_POSTER} />
      <div
        className="absolute inset-0"
        style={{
          background:
            "linear-gradient(115deg, var(--yk-navy-dark) 0%, var(--yk-navy)/70 45%, transparent 80%)",
          opacity: 0.9,
        }}
      />
      <div className="relative mx-auto max-w-7xl px-4 sm:px-6 py-24 sm:py-36 lg:py-44">
        <div className="max-w-3xl space-y-7">
          <div className="flex flex-wrap items-center gap-3">
            <CertifiedBadge variant="dark" size="md" />
            <span className="font-eyebrow text-xs text-[var(--yk-gold)]">
              SINCE 1988
            </span>
          </div>
          <h1 data-edit-id="kittoku-top-hero-h1" className="font-headline text-white text-4xl sm:text-5xl lg:text-6xl font-black leading-[1.1]">
            働く車を、
            <br />
            <span className="text-[var(--yk-gold)]">止めない。</span>
          </h1>
          <p data-edit-id="kittoku-top-hero-tagline" className="text-white/85 text-base sm:text-lg leading-relaxed max-w-2xl">
            鳥取・米子の特装車専門整備工場。
            <br className="hidden sm:inline" />
            ダンプ・塵芥車・テールゲートリフタ・クレーンまで、
            新明和工業の認定修理工場として正規の技術でお応えします。
          </p>
          <div className="flex flex-col sm:flex-row items-start sm:items-center gap-4 pt-2">
            <Button
              asChild
              size="lg"
              className="bg-[var(--yk-gold)] hover:bg-[var(--yk-gold-dark)] text-[var(--yk-navy-dark)] font-bold rounded-sm h-12 px-6"
            >
              <Link data-edit-id="kittoku-top-hero-cta-primary" href="/artifacts/kittoku/contact">
                修理・整備の依頼
                <ArrowRight className="h-4 w-4 ml-1.5" />
              </Link>
            </Button>
            <div
              data-edit-id="kittoku-top-hero-hours"
              className="flex items-center gap-3 text-white"
            >
              <Clock className="h-5 w-5" />
              <div className="flex flex-col leading-tight">
                <span data-edit-id="kittoku-top-hero-hours-label" className="text-xs text-white/60">営業時間</span>
                <span data-edit-id="kittoku-top-hero-hours-value" className="font-mono-data text-lg font-bold">
                  月〜土 9:00〜17:00
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
      {/* 下端の黄色いアクセント帯 */}
      <div className="absolute bottom-0 left-0 right-0 h-1 bg-[var(--yk-gold)]" />
    </section>
  );
}

function StatsSection() {
  return (
    <div className="bg-white border-b border-border">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 py-8 sm:py-10">
        <div className="flex flex-row items-center justify-center gap-6 sm:gap-10">
          <div className="space-y-1.5 text-[var(--yk-steel)] font-headline">
            <p data-edit-id="kittoku-top-stats-line1" className="text-sm sm:text-base leading-relaxed">
              1988年創業
            </p>
            <p data-edit-id="kittoku-top-stats-line2" className="text-sm sm:text-base leading-relaxed">
              山陰地方を中心に、
              <br className="sm:hidden" />
              中国地方の働く車を支えています。
            </p>
          </div>
          <div className="shrink-0 w-[180px] sm:w-[260px]">
            <div className="relative w-full">
              <Image
                src="/kikkawa/chugoku-map-v3.png"
                alt="中国地方マップ - 吉川特装は鳥取県米子市"
                width={1024}
                height={1024}
                className="w-full h-auto"
                sizes="(max-width: 640px) 180px, 260px"
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function VehiclesSection() {
  const keys = Object.keys(VEHICLES) as VehicleKey[];
  return (
    <Section padding="xl" width="xl" className="bg-background">
      <div className="space-y-3 mb-12">
        <div className="flex items-center gap-3">
          <DiagonalDivider />
          <span className="font-eyebrow text-xs text-[var(--yk-gold-dark)]">
            Services
          </span>
        </div>
        <div className="flex flex-col lg:flex-row lg:items-end lg:justify-between gap-4">
          <h2 data-edit-id="kittoku-top-vehicles-h2" className="font-headline text-3xl sm:text-4xl lg:text-5xl font-black text-[var(--yk-navy)] tracking-tight leading-tight">
            特装車 全機種、
            <br className="sm:hidden" />
            お任せください。
          </h2>
          <p data-edit-id="kittoku-top-vehicles-lead" className="text-[var(--yk-steel)] max-w-md leading-relaxed">
            新明和の認定工場として蓄積した専門知識で、
            メーカー純正部品の手配から点検・整備・修理・架装までワンストップで対応します。
          </p>
        </div>
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-3 sm:gap-5">
        {keys.map((key) => {
          const v = VEHICLES[key];
          return (
            <Link
              key={key}
              href="/artifacts/kittoku/services"
              className="group relative bg-white border border-border rounded-sm overflow-hidden hover:border-[var(--yk-navy)] hover:-translate-y-0.5 transition-all duration-200"
            >
              <div className="aspect-[4/3] relative bg-white overflow-hidden">
                <Image
                  data-edit-id={`kittoku-top-vehicles-${key}-img`}
                  src={v.image}
                  alt={v.label}
                  fill
                  className="object-contain p-3 group-hover:scale-[1.03] transition-transform duration-300"
                  sizes="(max-width: 640px) 100vw, (max-width: 1024px) 50vw, 33vw"
                />
              </div>
              <div className="p-5 space-y-1.5">
                <div className="flex items-center justify-between gap-2">
                  <h3 data-edit-id={`kittoku-top-vehicles-${key}-title`} className="font-headline font-bold text-[var(--yk-navy)]">
                    {v.label}
                  </h3>
                  <ChevronRight className="h-4 w-4 text-[var(--yk-steel)] group-hover:text-[var(--yk-navy)] group-hover:translate-x-0.5 transition-all shrink-0" />
                </div>
                <p data-edit-id={`kittoku-top-vehicles-${key}-body`} className="text-xs text-[var(--yk-steel)] leading-relaxed">
                  {v.description}
                </p>
              </div>
            </Link>
          );
        })}
      </div>
    </Section>
  );
}

function FlowSection() {
  return (
    <section className="bg-[var(--yk-navy)] text-white">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 py-20 sm:py-28">
        <div className="space-y-3 mb-12">
          <div className="flex items-center gap-3">
            <DiagonalDivider color="var(--yk-gold)" />
            <span className="font-eyebrow text-xs text-[var(--yk-gold)]">
              Inquiry flow
            </span>
          </div>
          <div className="flex flex-col lg:flex-row lg:items-end lg:justify-between gap-4">
            <h2 data-edit-id="kittoku-top-flow-h2" className="font-headline text-3xl sm:text-4xl lg:text-5xl font-black leading-tight">
              修理・部品交換など
              <br />
              ぜひお問い合わせください
            </h2>
            <p data-edit-id="kittoku-top-flow-lead" className="text-white/80 max-w-[344px] leading-relaxed">
              便利な「Webフォーム」か「お電話」で
              <br />
              お問い合わせいただけます
            </p>
          </div>
        </div>
        <div className="flex flex-col sm:flex-row items-start sm:items-center gap-4 pt-8">
          <Button
            asChild
            size="lg"
            className="bg-[var(--yk-gold)] hover:bg-[var(--yk-gold-dark)] text-[var(--yk-navy-dark)] font-bold rounded-sm h-12 px-6"
          >
            <Link data-edit-id="kittoku-top-flow-cta" href="/artifacts/kittoku/contact">
              WEB問い合わせ
              <ArrowRight className="h-4 w-4 ml-1.5" />
            </Link>
          </Button>
        </div>
      </div>
    </section>
  );
}

function StrengthsSection() {
  return (
    <Section padding="xl" width="xl" className="bg-background">
      <div className="space-y-3 mb-12">
        <div className="flex items-center gap-3">
          <DiagonalDivider />
          <span className="font-eyebrow text-xs text-[var(--yk-gold-dark)]">
            Why yoshikawa
          </span>
        </div>
        <h2 data-edit-id="kittoku-top-strengths-h2" className="font-headline text-3xl sm:text-4xl lg:text-5xl font-black text-[var(--yk-navy)] tracking-tight">
          選ばれる、3つの理由。
        </h2>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {STRENGTHS.map((s, i) => {
          const Icon = s.icon;
          return (
            <Card
              key={s.slug}
              className="border-border bg-white rounded-sm overflow-hidden"
            >
              <CardContent className="p-8 space-y-5">
                <div className="flex items-center justify-between">
                  <span data-edit-id={`kittoku-top-strengths-${s.slug}-num`} className="font-eyebrow text-sm text-[var(--yk-gold-dark)] font-mono-data">
                    0{i + 1}
                  </span>
                  <Icon className="h-6 w-6 text-[var(--yk-navy)]" />
                </div>
                <h3 data-edit-id={`kittoku-top-strengths-${s.slug}-h3`} className="font-headline text-xl font-bold text-[var(--yk-navy)] leading-snug">
                  {s.title}
                </h3>
                <p data-edit-id={`kittoku-top-strengths-${s.slug}-body`} className="text-sm text-[var(--yk-steel)] leading-relaxed">
                  {s.body}
                </p>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </Section>
  );
}

function ManufacturersSection() {
  return (
    <Section padding="lg" width="xl" className="bg-[var(--yk-navy)]/5">
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-10 items-start">
        <div className="space-y-3">
          <div className="flex items-center gap-3">
            <DiagonalDivider />
            <span className="font-eyebrow text-xs text-[var(--yk-gold-dark)]">
              Manufacturers
            </span>
          </div>
          <h2 data-edit-id="kittoku-top-manufacturers-h2" className="font-headline text-2xl sm:text-3xl font-black text-[var(--yk-navy)] leading-tight">
            取扱メーカー
          </h2>
          <p data-edit-id="kittoku-top-manufacturers-lead" className="text-sm text-[var(--yk-steel)] leading-relaxed">
            新明和工業の認定工場であることに加え、主要架装メーカーの整備実績があります。
          </p>
        </div>
        <div className="lg:col-span-2 grid grid-cols-2 sm:grid-cols-3 gap-3">
          {MANUFACTURERS.map((m) => (
            <a
              key={m.slug}
              data-edit-id={`kittoku-top-manufacturers-${m.slug}-link`}
              href={m.siteUrl}
              target="_blank"
              rel="noreferrer noopener"
              className={`group relative bg-white border rounded-sm overflow-hidden transition-all flex items-center justify-center h-[120px] p-5 ${
                m.accent
                  ? "border-[var(--yk-gold)] border-2"
                  : "border-border hover:border-[var(--yk-navy)]/40"
              }`}
            >
              {m.logo ? (
                <Image
                  data-edit-id={`kittoku-top-manufacturers-${m.slug}-img`}
                  src={m.logo}
                  alt={m.name}
                  width={200}
                  height={64}
                  className="max-h-[56px] w-auto object-contain"
                  style={m.logoStyle ?? { height: "auto" }}
                />
              ) : (
                <div className="text-center space-y-1">
                  <div data-edit-id={`kittoku-top-manufacturers-${m.slug}-name`} className="font-headline font-black text-[var(--yk-navy)] text-xl sm:text-2xl leading-tight tracking-tight">
                    {m.name}
                  </div>
                  <div data-edit-id={`kittoku-top-manufacturers-${m.slug}-en`} className="font-eyebrow text-[10px] text-[var(--yk-steel)] tracking-wider">
                    {m.en}
                  </div>
                </div>
              )}
              {m.accent && (
                <div
                  className="absolute -top-px -right-px flex items-center gap-1 bg-[var(--yk-gold)] text-[var(--yk-navy-dark)] px-2 py-1 rounded-bl-sm shadow-sm"
                  title="新明和工業 認定修理工場"
                >
                  <Award className="h-3 w-3" />
                  <span className="font-headline font-bold text-[10px] tracking-wide">
                    認定工場
                  </span>
                </div>
              )}
            </a>
          ))}
        </div>
      </div>
    </Section>
  );
}

function CompanyBriefSection() {
  return (
    <Section padding="xl" width="xl" className="bg-background">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 items-start">
        <div className="space-y-6">
          <div className="flex items-center gap-3">
            <DiagonalDivider />
            <span className="font-eyebrow text-xs text-[var(--yk-gold-dark)]">
              Company
            </span>
          </div>
          <h2 data-edit-id="kittoku-top-company-h2" className="font-headline text-3xl sm:text-4xl font-black text-[var(--yk-navy)] leading-tight">
            米子で30年以上。
          </h2>
          <p data-edit-id="kittoku-top-company-body" className="text-[var(--yk-steel)] leading-relaxed">
            有限会社吉川特装自動車は、1988年の創業以来、鳥取県米子市から山陰地域の働く車を支え続けてきました。
            お客様の大切な業務車両を、確かな技術で最短復帰させることを使命としています。
          </p>
          <div className="grid grid-cols-2 gap-6 pt-2">
            <InfoRow label="所在地">
              <MapPin className="h-4 w-4 text-[var(--yk-navy)] shrink-0 mt-0.5" />
              <div className="space-y-0.5">
                <div className="text-xs text-[var(--yk-steel)] font-mono-data">
                  〒689-3537
                </div>
                <div className="text-sm">鳥取県米子市古豊千775-6</div>
              </div>
            </InfoRow>
            <InfoRow label="営業時間">
              <Clock className="h-4 w-4 text-[var(--yk-navy)] shrink-0 mt-0.5" />
              <div className="space-y-0.5">
                <div className="text-sm">平日 8:00〜17:00</div>
                <div className="text-xs text-[var(--yk-steel)]">土日祝休</div>
              </div>
            </InfoRow>
            <InfoRow label="代表電話">
              <Phone className="h-4 w-4 text-[var(--yk-navy)] shrink-0 mt-0.5" />
              <a
                href="tel:0859-27-4885"
                className="font-mono-data text-base font-bold text-[var(--yk-navy)]"
              >
                0859-27-4885
              </a>
            </InfoRow>
            <InfoRow label="代表者">
              <Users className="h-4 w-4 text-[var(--yk-navy)] shrink-0 mt-0.5" />
              <div className="text-sm">代表取締役 細田 かおり</div>
            </InfoRow>
          </div>
          <div className="pt-2">
            <Button
              asChild
              variant="outline"
              className="border-[var(--yk-navy)] text-[var(--yk-navy)] hover:bg-[var(--yk-navy)] hover:text-white rounded-sm"
            >
              <Link data-edit-id="kittoku-top-company-cta" href="/artifacts/kittoku/company">
                会社情報を見る
                <ArrowRight className="h-4 w-4 ml-1.5" />
              </Link>
            </Button>
          </div>
        </div>
        <div className="lg:pl-6">
          <LocationMap
            src="https://www.google.com/maps?q=%E9%B3%A5%E5%8F%96%E7%9C%8C%E7%B1%B3%E5%AD%90%E5%B8%82%E5%8F%A4%E8%B1%8A%E5%8D%83775-6&output=embed"
            address="鳥取県米子市古豊千775-6"
            caption="JR米子駅より車で約10分 / 山陰道 米子ICより約5分"
            aspectRatio="4/3"
          />
        </div>
      </div>
    </Section>
  );
}

function InfoRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-2">
      <div className="font-eyebrow text-[10px] text-[var(--yk-gold-dark)]">
        {label}
      </div>
      <div className="flex items-start gap-2 text-[var(--yk-navy-dark)]">
        {children}
      </div>
    </div>
  );
}

function CareersCtaSection() {
  return (
    <Section padding="xl" width="xl" className="bg-background">
      <Link
        data-edit-id="kittoku-top-careers-card"
        href="/artifacts/kittoku/careers"
        className="group relative block overflow-hidden rounded-sm border border-border bg-[var(--yk-navy-dark)] aspect-[16/7] sm:aspect-[16/5] transition-all hover:shadow-2xl"
      >
        <Image
          src="/kikkawa/careers-cta.jpg"
          alt="吉川特装で働く社員"
          fill
          sizes="(max-width: 1024px) 100vw, 1280px"
          className="object-cover opacity-70 transition-transform duration-500 group-hover:scale-105"
        />
        <div className="absolute inset-0 bg-gradient-to-t from-[var(--yk-navy-dark)]/85 via-[var(--yk-navy-dark)]/40 to-transparent" />
        <div className="absolute inset-0 p-6 sm:p-10 flex flex-col justify-end">
          <div className="flex items-center gap-3 mb-3">
            <DiagonalDivider color="var(--yk-gold)" />
            <span className="font-eyebrow text-xs text-[var(--yk-gold)]">
              Careers
            </span>
          </div>
          <h2
            data-edit-id="kittoku-top-careers-h2"
            className="font-headline text-2xl sm:text-3xl lg:text-4xl font-black text-white leading-tight"
          >
            一緒に働く仲間を、募集しています。
          </h2>
          <div className="inline-flex items-center gap-2 text-[var(--yk-gold)] font-bold text-sm sm:text-base mt-3 group-hover:gap-3 transition-all">
            採用情報を見る
            <ArrowRight className="h-4 w-4" />
          </div>
        </div>
      </Link>
    </Section>
  );
}
