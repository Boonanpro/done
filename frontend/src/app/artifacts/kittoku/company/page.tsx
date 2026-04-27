import Link from "next/link";
import Image from "next/image";
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
  { slug: "name", label: "商号", value: "有限会社 吉川特装自動車", icon: Building2 },
  { slug: "ceo", label: "代表者", value: "代表取締役 細田 かおり", icon: Users },
  { slug: "founded", label: "設立", value: "1988年7月25日", icon: Calendar },
  { slug: "corporate-number", label: "法人番号", value: "1270002007313", icon: FileText, mono: true },
  {
    slug: "address",
    label: "所在地",
    value: "〒689-3537 鳥取県米子市古豊千775-6",
    icon: MapPin,
  },
  { slug: "tel", label: "電話", value: "0859-27-4885", icon: Phone, mono: true },
  { slug: "hours", label: "営業時間", value: "平日 8:00〜17:00（土日祝休）", icon: Clock },
  {
    slug: "business",
    label: "事業内容",
    value: "特装車の整備・修理・架装、純正部品販売",
    icon: Building2,
  },
];

const HISTORY = [
  {
    year: "1988",
    title: "創業",
    body: "先代 吉川 誠一 が鳥取県米子市古豊千にて有限会社吉川特装自動車を設立。地域の建設・運送事業者向けの特装車整備を開始。「働く車を、止めない」を信条に事業をスタート。",
  },
  {
    year: "1995",
    title: "新明和工業 指定サービス工場 認定",
    body: "特装車大手メーカー・新明和工業株式会社の指定サービス工場として正式認定。純正部品の直接取扱いと正規整備体制を確立。",
  },
  {
    year: "2003",
    title: "整備工場設備を拡充",
    body: "大型車リフト・油圧試験装置を追加導入。大型ダンプ・タンクローリなど、より幅広い特装車への対応体制を整備。",
  },
  {
    year: "2010",
    title: "高所作業車・クレーン対応開始",
    body: "アイチコーポレーション・タダノなど主要メーカーの高所作業車・クレーン年次点検に対応。中国地方全域からの入庫受入れを開始。",
  },
  {
    year: "2013",
    title: "二代目 細田 かおり 代表取締役 就任",
    body: "創業者 吉川 誠一 の長女 細田 かおり が二代目代表取締役に就任。父の代から受け継いだ「現場を止めない整備」の文化をそのままに、社内体制の近代化に着手。",
  },
  {
    year: "2015",
    title: "出張整備サービス開始",
    body: "稼働が止められない清掃事業者向けの夜間・休日出張整備を開始。現場での応急修理と計画整備の両軸で対応。",
  },
  {
    year: "2020",
    title: "デジタル車両管理の試験運用",
    body: "整備履歴のデジタル化を試験導入。お客様ごとの車両台帳と過去整備記録を即時参照できる体制へ移行。",
  },
  {
    year: "2026",
    title: "Web問い合わせフォーム導入・新事業準備",
    body: "DXの一環としてWebからの車両情報・破損画像の一括受付を開始。あわせて特装車の塗装サービス・中古車販売の準備を進行中。",
  },
];

export default function CompanyPage() {
  return (
    <LpShell nav={<SiteNav />} footer={<SiteFooter />}>
      <PageHero />
      <GroupPhotoSection />
      <GreetingSection />
      <OverviewSection />
      <HistorySection />
      <AccessSection />
    </LpShell>
  );
}

function GroupPhotoSection() {
  return (
    <section className="bg-background">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 py-10 sm:py-16">
        <div className="relative rounded-sm overflow-hidden border border-border">
          <div className="aspect-[16/9] sm:aspect-[21/9] relative bg-[var(--yk-navy)]/5">
            <Image
              src="/kikkawa/people/group.png"
              alt="吉川特装自動車 社員一同"
              fill
              className="object-cover"
              sizes="(max-width: 1280px) 100vw, 1280px"
              priority
            />
          </div>
          <div className="absolute left-4 bottom-4 sm:left-6 sm:bottom-6 bg-white/90 backdrop-blur rounded-sm px-3 py-2 sm:px-4 sm:py-2.5 flex items-center gap-2">
            <Users className="h-4 w-4 text-[var(--yk-navy)]" />
            <span className="font-headline text-xs sm:text-sm font-bold text-[var(--yk-navy)]">
              吉川特装自動車 社員一同
            </span>
          </div>
        </div>
      </div>
    </section>
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
          <span className="text-white">会社情報</span>
        </div>
        <div className="flex items-center gap-3 mb-4">
          <DiagonalDivider color="var(--yk-gold)" />
          <span className="font-eyebrow text-xs text-[var(--yk-gold)]">
            Company
          </span>
        </div>
        <h1 data-edit-id="kittoku-company-hero-h1" className="font-headline text-4xl sm:text-5xl lg:text-6xl font-black leading-tight max-w-3xl">
          米子で、働く車を、30年。
        </h1>
      </div>
    </section>
  );
}

function GreetingSection() {
  return (
    <Section padding="xl" width="xl" className="bg-background">
      <div className="grid grid-cols-1 lg:grid-cols-[320px_1fr] gap-8 lg:gap-x-14 lg:gap-y-7">
        {/* ラベル + 見出し: スマホ1番目 / PC右上 */}
        <div className="space-y-3 lg:col-start-2 lg:row-start-1">
          <div className="flex items-center gap-3">
            <DiagonalDivider />
            <span className="font-eyebrow text-xs text-[var(--yk-gold-dark)]">
              Message
            </span>
          </div>
          <h2 data-edit-id="kittoku-company-greeting-h2" className="font-headline text-3xl font-black text-[var(--yk-navy)] leading-tight">
            代表挨拶
          </h2>
        </div>

        {/* 画像 + 肩書き: スマホ2番目 / PC左カラム(2行スパン) */}
        <div className="space-y-4 lg:col-start-1 lg:row-start-1 lg:row-span-2">
          <div className="rounded-sm overflow-hidden border border-border bg-[var(--yk-navy)]/5 relative aspect-[3/4] max-w-[260px]">
            <Image
              src="/kikkawa/people/daihyo.png"
              alt="代表取締役 細田 かおり"
              fill
              className="object-cover"
              sizes="260px"
            />
          </div>
          <div className="space-y-0.5 max-w-[260px]">
            <div className="font-eyebrow text-[10px] text-[var(--yk-gold-dark)]">
              Representative director
            </div>
            <div className="font-headline text-lg font-black text-[var(--yk-navy)]">
              細田 かおり
            </div>
            <div className="text-xs text-[var(--yk-steel)]">
              二代目 代表取締役（2013年〜）
            </div>
          </div>
        </div>

        {/* 本文: スマホ3番目 / PC右下 */}
        <div className="space-y-5 text-[var(--yk-navy-dark)] leading-relaxed lg:col-start-2 lg:row-start-2">
          <p data-edit-id="kittoku-company-greeting-body-1">
            有限会社吉川特装自動車のホームページをご覧いただき、誠にありがとうございます。
          </p>
          <p data-edit-id="kittoku-company-greeting-body-2">
            私たちは
            <span className="font-headline font-bold text-[var(--yk-navy)]">
              1988年に先代・吉川 誠一
            </span>
            が創業して以来、米子の地で特装車の整備・修理一筋に歩んでまいりました。
            新明和工業の認定修理工場として、働く車を支える皆様の事業を、一台一台、確実な技術でお守りすることが私たちの使命です。
          </p>
          <p data-edit-id="kittoku-company-greeting-body-3">
            特装車は、ごみ収集・建設・物流・清掃・農業など、社会のあらゆる現場を支える車両です。
            その車両が止まれば、その先にあるお客様の業務が止まってしまう。その重みを常に胸に刻み、
            私たちはいつでも最速で現場復帰できる整備を目指しています。
          </p>
          <p data-edit-id="kittoku-company-greeting-body-4">
            父が築いた「働く車を、止めない」という信条を、私たちは次の時代へ引き継ぎます。
            これからも、米子から山陰・中国地方の働く車を支え続けてまいります。
            どうぞよろしくお願い申し上げます。
          </p>
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
        <h2 data-edit-id="kittoku-company-overview-h2" className="font-headline text-3xl font-black text-[var(--yk-navy)] leading-tight">
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
                  key={info.slug}
                  className="grid grid-cols-1 sm:grid-cols-4 gap-3 px-6 sm:px-8 py-5"
                >
                  <dt data-edit-id={`kittoku-company-info-${info.slug}-label`} className="flex items-center gap-2 text-sm font-medium text-[var(--yk-steel)]">
                    <Icon className="h-4 w-4 text-[var(--yk-navy)]" />
                    {info.label}
                  </dt>
                  <dd
                    data-edit-id={`kittoku-company-info-${info.slug}-value`}
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
        <h2 data-edit-id="kittoku-company-history-h2" className="font-headline text-3xl font-black text-[var(--yk-navy)] leading-tight">
          沿革
        </h2>
      </div>
      <div className="relative">
        {/* 縦線: スマホは左端、PCは年カラムの右端 */}
        <div className="absolute left-3 sm:left-24 top-0 bottom-0 w-px bg-[var(--yk-navy)]/20" />
        <div className="space-y-5">
          {HISTORY.map((h) => (
            <div
              key={h.year}
              className="grid grid-cols-1 sm:grid-cols-[120px_1fr] gap-3 sm:gap-8 relative pl-8 sm:pl-0"
            >
              {/* スマホ用: 縦線上のドット */}
              <span
                className="sm:hidden absolute left-3 top-3 h-2 w-2 rounded-full bg-[var(--yk-gold)] -translate-x-1/2"
                aria-hidden
              />
              <div className="flex sm:flex-col items-baseline sm:items-end gap-2 sm:gap-0 sm:text-right">
                <div data-edit-id={`kittoku-company-history-${h.year}-year`} className="font-mono-data text-3xl font-black text-[var(--yk-gold-dark)]">
                  {h.year}
                </div>
                {/* PC用: 縦線上のドット */}
                <span className="hidden sm:block h-2 w-2 rounded-full bg-[var(--yk-gold)] ml-auto translate-x-[calc(50%+1rem)] relative -mt-1" aria-hidden />
              </div>
              <div className="rounded-sm border border-border bg-white p-6 space-y-2">
                <div data-edit-id={`kittoku-company-history-${h.year}-title`} className="font-headline font-bold text-[var(--yk-navy)]">
                  {h.title}
                </div>
                <p data-edit-id={`kittoku-company-history-${h.year}-body`} className="text-sm text-[var(--yk-navy-dark)] leading-relaxed">
                  {h.body}
                </p>
              </div>
            </div>
          ))}
        </div>
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
          <h2 data-edit-id="kittoku-company-access-h2" className="font-headline text-3xl font-black text-[var(--yk-navy)] leading-tight">
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
