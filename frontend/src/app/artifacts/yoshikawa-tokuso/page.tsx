import Link from "next/link";
import {
  Phone,
  ArrowRight,
  Award,
  MapPin,
  Clock,
  Zap,
  Shield,
  Wrench,
  Building2,
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
import { FlowDiagram } from "./components/flow-diagram";
import { DiagonalDivider } from "./components/diagonal-divider";
import { VEHICLES, type VehicleKey } from "./components/vehicle-icons";

const HERO_IMAGE = "/yoshikawa/hero.png";

const STATS = [
  { label: "創業", value: "1988", unit: "年", hint: "35年以上の整備実績" },
  { label: "対応車種", value: "9", unit: "機種", hint: "特装車全機種カバー" },
  { label: "対応エリア", value: "中国", unit: "5県", hint: "山陰から広域に即応" },
  { label: "認定工場", value: "新明和", unit: "認定", hint: "指定サービス工場" },
];

const STRENGTHS = [
  {
    icon: Award,
    title: "新明和工業 認定修理工場",
    body: "特装車のリーディングメーカー、新明和工業の指定サービス工場としてメーカー純正部品と正規の整備ノウハウで対応します。",
  },
  {
    icon: Wrench,
    title: "特装車 全機種に対応",
    body: "塵芥車・ダンプ・クレーン・テールゲートリフタ・ローリ・高所作業車・ミキサ・飼料運搬車・脱着車まで、働く車のすべてを。",
  },
  {
    icon: Zap,
    title: "山陰から中国地方へ最短対応",
    body: "米子を拠点に鳥取・島根・岡山・広島・山口へ出張整備も可能。止まっては困る業務車両を最短で現場復帰させます。",
  },
];

const MANUFACTURERS = [
  { name: "新明和工業", accent: true },
  { name: "極東開発工業" },
  { name: "東邦車輛" },
  { name: "アイチコーポレーション" },
  { name: "タダノ" },
  { name: "古河ユニック" },
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
      <VehiclesSection />
      <FlowSection />
      <StrengthsSection />
      <ManufacturersSection />
      <CompanyBriefSection />
      <CareersCtaSection />
    </LpShell>
  );
}

/* ───────────────────────── Sections ───────────────────────── */

function HeroSection() {
  return (
    <section className="relative overflow-hidden">
      <div
        className="absolute inset-0"
        style={{
          backgroundImage: `url(${HERO_IMAGE})`,
          backgroundSize: "cover",
          backgroundPosition: "center",
          filter: "brightness(0.45) saturate(1.1)",
        }}
      />
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
          <h1 className="font-headline text-white text-4xl sm:text-5xl lg:text-6xl font-black leading-[1.1]">
            働く車を、
            <br />
            <span className="text-[var(--yk-gold)]">止めない。</span>
          </h1>
          <p className="text-white/85 text-base sm:text-lg leading-relaxed max-w-2xl">
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
              <Link href="/demo/yoshikawa-tokuso/contact">
                修理・整備の依頼
                <ArrowRight className="h-4 w-4 ml-1.5" />
              </Link>
            </Button>
            <a
              href="tel:0859-27-4885"
              className="flex items-center gap-3 text-white hover:text-[var(--yk-gold)] transition-colors"
            >
              <Phone className="h-5 w-5" />
              <div className="flex flex-col leading-tight">
                <span className="font-mono-data text-2xl font-bold">
                  0859-27-4885
                </span>
                <span className="text-xs text-white/60">平日 8:00〜17:00</span>
              </div>
            </a>
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
      <div className="mx-auto max-w-7xl px-4 sm:px-6">
        <div className="grid grid-cols-2 lg:grid-cols-4 divide-x divide-border">
          {STATS.map((s) => (
            <div key={s.label} className="px-6 py-8 space-y-2">
              <div className="font-eyebrow text-xs text-[var(--yk-gold-dark)]">
                {s.label}
              </div>
              <div className="flex items-baseline gap-1.5">
                <span className="font-headline text-4xl sm:text-5xl font-black text-[var(--yk-navy)] font-mono-data">
                  {s.value}
                </span>
                <span className="text-sm font-bold text-[var(--yk-steel)]">
                  {s.unit}
                </span>
              </div>
              <div className="text-xs text-[var(--yk-steel)]">{s.hint}</div>
            </div>
          ))}
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
          <h2 className="font-headline text-3xl sm:text-4xl lg:text-5xl font-black text-[var(--yk-navy)] tracking-tight leading-tight">
            特装車 全機種、
            <br className="sm:hidden" />
            お任せください。
          </h2>
          <p className="text-[var(--yk-steel)] max-w-md leading-relaxed">
            新明和の認定工場として蓄積した専門知識で、
            メーカー純正部品の手配から点検・整備・修理・架装までワンストップで対応します。
          </p>
        </div>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {keys.map((key) => {
          const v = VEHICLES[key];
          const Icon = v.icon;
          return (
            <Link
              key={key}
              href="/demo/yoshikawa-tokuso/services"
              className="group relative bg-white border border-border rounded-sm p-6 hover:border-[var(--yk-navy)] hover:-translate-y-0.5 transition-all duration-200"
            >
              <div className="flex items-start gap-4">
                <div className="shrink-0 h-12 w-12 rounded-sm bg-[var(--yk-navy)]/5 text-[var(--yk-navy)] flex items-center justify-center group-hover:bg-[var(--yk-navy)] group-hover:text-white transition-colors">
                  <Icon className="h-6 w-6" />
                </div>
                <div className="space-y-1.5 flex-1">
                  <h3 className="font-headline font-bold text-[var(--yk-navy)]">
                    {v.label}
                  </h3>
                  <p className="text-xs text-[var(--yk-steel)] leading-relaxed">
                    {v.description}
                  </p>
                </div>
                <ChevronRight className="h-4 w-4 text-[var(--yk-steel)] group-hover:text-[var(--yk-navy)] group-hover:translate-x-0.5 transition-all" />
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
            <h2 className="font-headline text-3xl sm:text-4xl lg:text-5xl font-black leading-tight">
              電話だけの問い合わせ、
              <br className="sm:hidden" />
              もう終わりにしませんか。
            </h2>
            <p className="text-white/80 max-w-md leading-relaxed">
              特装車の部品手配・修理には
              <span className="font-mono-data font-bold text-[var(--yk-gold)]">
                車台番号・型式
              </span>
              などが必須です。Webフォームなら必要な情報を一度に整理してお送りいただけます。
            </p>
          </div>
        </div>
        <div className="text-foreground">
          <FlowDiagram />
        </div>
        <div className="flex flex-col sm:flex-row items-start sm:items-center gap-4 pt-12">
          <Button
            asChild
            size="lg"
            className="bg-[var(--yk-gold)] hover:bg-[var(--yk-gold-dark)] text-[var(--yk-navy-dark)] font-bold rounded-sm h-12 px-6"
          >
            <Link href="/demo/yoshikawa-tokuso/contact">
              Webフォームで問い合わせ
              <ArrowRight className="h-4 w-4 ml-1.5" />
            </Link>
          </Button>
          <div className="text-white/70 text-sm">
            入力の途中で分からない項目があっても、そのまま送信OK。折り返しご連絡します。
          </div>
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
        <h2 className="font-headline text-3xl sm:text-4xl lg:text-5xl font-black text-[var(--yk-navy)] tracking-tight">
          選ばれる、3つの理由。
        </h2>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {STRENGTHS.map((s, i) => {
          const Icon = s.icon;
          return (
            <Card
              key={s.title}
              className="border-border bg-white rounded-sm overflow-hidden"
            >
              <CardContent className="p-8 space-y-5">
                <div className="flex items-center justify-between">
                  <span className="font-eyebrow text-sm text-[var(--yk-gold-dark)] font-mono-data">
                    0{i + 1}
                  </span>
                  <Icon className="h-6 w-6 text-[var(--yk-navy)]" />
                </div>
                <h3 className="font-headline text-xl font-bold text-[var(--yk-navy)] leading-snug">
                  {s.title}
                </h3>
                <p className="text-sm text-[var(--yk-steel)] leading-relaxed">
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
          <h2 className="font-headline text-2xl sm:text-3xl font-black text-[var(--yk-navy)] leading-tight">
            取扱メーカー
          </h2>
          <p className="text-sm text-[var(--yk-steel)] leading-relaxed">
            新明和工業の認定工場であることに加え、主要架装メーカーの整備実績があります。
          </p>
        </div>
        <div className="lg:col-span-2 grid grid-cols-2 sm:grid-cols-3 gap-3">
          {MANUFACTURERS.map((m) => (
            <div
              key={m.name}
              className={`bg-white border rounded-sm p-5 flex items-center justify-between ${
                m.accent
                  ? "border-[var(--yk-gold)] border-2"
                  : "border-border"
              }`}
            >
              <div className="space-y-1">
                {m.accent && (
                  <Badge className="bg-[var(--yk-gold)] text-[var(--yk-navy-dark)] hover:bg-[var(--yk-gold)] rounded-sm text-[10px] font-mono-data">
                    AUTHORIZED
                  </Badge>
                )}
                <div className="font-headline font-bold text-[var(--yk-navy)]">
                  {m.name}
                </div>
              </div>
              {m.accent && (
                <Award className="h-5 w-5 text-[var(--yk-gold)]" />
              )}
            </div>
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
          <h2 className="font-headline text-3xl sm:text-4xl font-black text-[var(--yk-navy)] leading-tight">
            米子の地で、
            <br />
            30年以上。
          </h2>
          <p className="text-[var(--yk-steel)] leading-relaxed">
            有限会社吉川特装自動車は、1988年の創業以来、鳥取県米子市から山陰地域の働く車を支え続けてきました。
            新明和工業の指定サービス工場としての知識と経験をもとに、お客様の大切な業務車両を、
            確かな技術で最短復帰させることを使命としています。
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
              <Link href="/demo/yoshikawa-tokuso/company">
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
    <section className="relative overflow-hidden">
      <div
        className="absolute inset-0 bg-[var(--yk-navy-dark)]"
        style={{
          backgroundImage:
            "linear-gradient(135deg, var(--yk-navy-dark) 0%, var(--yk-navy) 100%)",
        }}
      />
      <div
        className="absolute inset-0 opacity-[0.06]"
        style={{
          backgroundImage:
            "repeating-linear-gradient(-45deg, var(--yk-gold) 0 1px, transparent 1px 12px)",
        }}
      />
      <div className="relative mx-auto max-w-7xl px-4 sm:px-6 py-20 sm:py-28">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 items-center">
          <div className="lg:col-span-2 space-y-5">
            <div className="flex items-center gap-3">
              <DiagonalDivider color="var(--yk-gold)" />
              <span className="font-eyebrow text-xs text-[var(--yk-gold)]">
                Careers
              </span>
            </div>
            <h2 className="font-headline text-3xl sm:text-4xl lg:text-5xl font-black text-white leading-tight">
              働く車を支える、
              <br />
              私たちの仕事を、一緒に。
            </h2>
            <p className="text-white/80 leading-relaxed max-w-2xl">
              特装車の整備は、普通の自動車整備では経験できない奥深い世界です。
              油圧、電装、機構。ひとつひとつの工程にクライアントの事業が乗っている。
              そんな誇りを持って働ける仲間を募集しています。
            </p>
          </div>
          <div className="flex flex-col gap-3">
            <Button
              asChild
              size="lg"
              className="bg-[var(--yk-gold)] hover:bg-[var(--yk-gold-dark)] text-[var(--yk-navy-dark)] font-bold rounded-sm h-12"
            >
              <Link href="/demo/yoshikawa-tokuso/careers">
                採用情報を見る
                <ArrowRight className="h-4 w-4 ml-1.5" />
              </Link>
            </Button>
            <Button
              asChild
              variant="outline"
              size="lg"
              className="border-white/40 text-white bg-transparent hover:bg-white/10 hover:text-white rounded-sm h-12"
            >
              <Link href="/demo/yoshikawa-tokuso/contact">
                お問い合わせ
                <ArrowRight className="h-4 w-4 ml-1.5" />
              </Link>
            </Button>
          </div>
        </div>
      </div>
    </section>
  );
}
