import Link from "next/link";
import { ChevronRight, MapPin, Phone, Users, Building2, Calendar, Clock, FileText } from "lucide-react";
import { LpShell } from "@/components/templates/lp-shell";
import { Section } from "@/components/templates/section";
import { Card, CardContent } from "@/components/ui/card";
import { LocationMap } from "@/components/templates/location-map";
import { SiteNav } from "../components/site-nav";
import { SiteFooter } from "../components/site-footer";
import { DiagonalDivider } from "../components/diagonal-divider";

export const metadata = {
  title: "会社情報 | 吉川特装",
  description:
    "有限会社吉川特装自動車の会社概要・沿革・アクセス情報。鳥取県米子市で特装車整備を手掛ける新明和工業認定修理工場。",
};

const COMPANY_INFO = [
  { label: "商号", value: "有限会社 吉川特装自動車", icon: Building2 },
  { label: "代表者", value: "代表取締役 細田 かおり", icon: Users },
  { label: "設立", value: "1988年7月25日", icon: Calendar },
  { label: "法人番号", value: "1270002007313", icon: FileText, mono: true },
  {
    label: "所在地",
    value: "〒689-3537 鳥取県米子市古豊千775-6",
    icon: MapPin,
  },
  { label: "電話", value: "0859-27-4885", icon: Phone, mono: true },
  { label: "営業時間", value: "平日 8:00〜17:00（土日祝休）", icon: Clock },
  {
    label: "事業内容",
    value: "特装車の整備・修理・架装、純正部品販売",
    icon: Building2,
  },
];

const HISTORY = [
  {
    year: "1988",
    body: "鳥取県米子市にて有限会社吉川特装自動車を設立。特装車整備事業をスタート。",
  },
  {
    year: "1990s",
    body: "新明和工業 指定サービス工場として認定。塵芥車・ダンプ・テールゲートリフタの整備体制を確立。",
  },
  {
    year: "2000s",
    body: "山陰地域の特装車整備ニーズ拡大に対応し、整備工場設備を拡充。",
  },
  {
    year: "2010s",
    body: "中国地方5県へのサービス範囲を拡大。高所作業車・クレーン・ミキサなど全特装機種への対応を確立。",
  },
  {
    year: "2020s",
    body: "DX推進の一環としてWeb問い合わせフォームを導入。顧客対応のさらなる効率化を推進。",
  },
];

export default function CompanyPage() {
  return (
    <LpShell nav={<SiteNav />} footer={<SiteFooter />}>
      <PageHero />
      <GreetingSection />
      <OverviewSection />
      <HistorySection />
      <AccessSection />
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
          <span className="text-white">会社情報</span>
        </div>
        <div className="flex items-center gap-3 mb-4">
          <DiagonalDivider color="var(--yk-gold)" />
          <span className="font-eyebrow text-xs text-[var(--yk-gold)]">
            Company
          </span>
        </div>
        <h1 className="font-headline text-4xl sm:text-5xl lg:text-6xl font-black leading-tight max-w-3xl">
          米子の地で、
          <br />
          働く車を、30年以上。
        </h1>
      </div>
    </section>
  );
}

function GreetingSection() {
  return (
    <Section padding="xl" width="lg" className="bg-background">
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-12">
        <div className="space-y-3">
          <div className="flex items-center gap-3">
            <DiagonalDivider />
            <span className="font-eyebrow text-xs text-[var(--yk-gold-dark)]">
              Message
            </span>
          </div>
          <h2 className="font-headline text-3xl font-black text-[var(--yk-navy)] leading-tight">
            代表挨拶
          </h2>
        </div>
        <div className="lg:col-span-2 space-y-5 text-[var(--yk-navy-dark)] leading-relaxed">
          <p>
            有限会社吉川特装自動車のホームページをご覧いただき、誠にありがとうございます。
          </p>
          <p>
            私たちは1988年の創業以来、米子の地で特装車の整備・修理一筋に歩んでまいりました。
            新明和工業の認定修理工場として、働く車を支える皆様の事業を、一台一台、確実な技術でお守りすることが私たちの使命です。
          </p>
          <p>
            特装車は、ごみ収集・建設・物流・清掃・農業など、社会のあらゆる現場を支える車両です。
            その車両が止まれば、その先にあるお客様の業務が止まってしまう。その重みを常に胸に刻み、
            私たちはいつでも最速で現場復帰できる整備を目指しています。
          </p>
          <p>
            これからも、米子から山陰・中国地方の働く車を支え続けてまいります。
            どうぞよろしくお願い申し上げます。
          </p>
          <div className="pt-4 text-sm text-[var(--yk-steel)]">
            代表取締役 <span className="font-headline font-bold text-base text-[var(--yk-navy)]">細田 かおり</span>
          </div>
        </div>
      </div>
    </Section>
  );
}

function OverviewSection() {
  return (
    <Section padding="xl" width="lg" className="bg-[var(--yk-navy)]/5">
      <div className="space-y-3 mb-10">
        <div className="flex items-center gap-3">
          <DiagonalDivider />
          <span className="font-eyebrow text-xs text-[var(--yk-gold-dark)]">
            Overview
          </span>
        </div>
        <h2 className="font-headline text-3xl font-black text-[var(--yk-navy)] leading-tight">
          会社概要
        </h2>
      </div>
      <Card className="rounded-sm border-border">
        <CardContent className="p-0">
          <dl className="divide-y divide-border">
            {COMPANY_INFO.map((info) => {
              const Icon = info.icon;
              return (
                <div
                  key={info.label}
                  className="grid grid-cols-1 sm:grid-cols-4 gap-3 px-6 sm:px-8 py-5"
                >
                  <dt className="flex items-center gap-2 text-sm font-medium text-[var(--yk-steel)]">
                    <Icon className="h-4 w-4 text-[var(--yk-navy)]" />
                    {info.label}
                  </dt>
                  <dd
                    className={`sm:col-span-3 text-[var(--yk-navy-dark)] ${
                      info.mono ? "font-mono-data" : ""
                    }`}
                  >
                    {info.value}
                  </dd>
                </div>
              );
            })}
          </dl>
        </CardContent>
      </Card>
    </Section>
  );
}

function HistorySection() {
  return (
    <Section padding="xl" width="lg" className="bg-background">
      <div className="space-y-3 mb-10">
        <div className="flex items-center gap-3">
          <DiagonalDivider />
          <span className="font-eyebrow text-xs text-[var(--yk-gold-dark)]">
            History
          </span>
        </div>
        <h2 className="font-headline text-3xl font-black text-[var(--yk-navy)] leading-tight">
          沿革
        </h2>
      </div>
      <div className="space-y-4">
        {HISTORY.map((h) => (
          <div
            key={h.year}
            className="grid grid-cols-1 sm:grid-cols-5 gap-4 rounded-sm border border-border bg-white p-6"
          >
            <div className="font-mono-data text-3xl font-black text-[var(--yk-gold-dark)]">
              {h.year}
            </div>
            <div className="sm:col-span-4 text-[var(--yk-navy-dark)] leading-relaxed">
              {h.body}
            </div>
          </div>
        ))}
      </div>
    </Section>
  );
}

function AccessSection() {
  return (
    <Section padding="xl" width="xl" className="bg-[var(--yk-navy)]/5">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 items-start">
        <div className="space-y-5">
          <div className="flex items-center gap-3">
            <DiagonalDivider />
            <span className="font-eyebrow text-xs text-[var(--yk-gold-dark)]">
              Access
            </span>
          </div>
          <h2 className="font-headline text-3xl font-black text-[var(--yk-navy)] leading-tight">
            アクセス
          </h2>
          <div className="space-y-4 text-[var(--yk-navy-dark)]">
            <div className="flex items-start gap-3">
              <MapPin className="h-5 w-5 text-[var(--yk-navy)] shrink-0 mt-0.5" />
              <div>
                <div className="font-mono-data text-xs text-[var(--yk-steel)]">
                  〒689-3537
                </div>
                <div className="font-bold">鳥取県米子市古豊千775-6</div>
              </div>
            </div>
            <div className="flex items-start gap-3">
              <Phone className="h-5 w-5 text-[var(--yk-navy)] shrink-0 mt-0.5" />
              <a
                href="tel:0859-27-4885"
                className="font-mono-data text-2xl font-bold text-[var(--yk-navy)]"
              >
                0859-27-4885
              </a>
            </div>
            <div className="flex items-start gap-3">
              <Clock className="h-5 w-5 text-[var(--yk-navy)] shrink-0 mt-0.5" />
              <div>
                <div>平日 8:00〜17:00</div>
                <div className="text-sm text-[var(--yk-steel)]">土日祝休</div>
              </div>
            </div>
          </div>
          <div className="pt-3 space-y-1.5 text-sm text-[var(--yk-steel)]">
            <div>JR米子駅より車で約10分</div>
            <div>山陰道 米子ICより約5分</div>
          </div>
        </div>
        <LocationMap
          src="https://www.google.com/maps?q=%E9%B3%A5%E5%8F%96%E7%9C%8C%E7%B1%B3%E5%AD%90%E5%B8%82%E5%8F%A4%E8%B1%8A%E5%8D%83775-6&output=embed"
          address="鳥取県米子市古豊千775-6"
          aspectRatio="4/3"
        />
      </div>
    </Section>
  );
}
