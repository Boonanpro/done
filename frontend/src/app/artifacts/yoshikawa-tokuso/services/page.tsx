import Link from "next/link";
import {
  ArrowRight,
  CheckCircle2,
  Wrench,
  FileSearch,
  PackageCheck,
  Truck,
  ChevronRight,
} from "lucide-react";
import { LpShell } from "@/components/templates/lp-shell";
import { Section } from "@/components/templates/section";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { SiteNav } from "../components/site-nav";
import { SiteFooter } from "../components/site-footer";
import { DiagonalDivider } from "../components/diagonal-divider";
import { VEHICLES, type VehicleKey } from "../components/vehicle-icons";

const SERVICE_CATEGORIES = [
  {
    icon: Wrench,
    eyebrow: "Repair",
    title: "整備・修理",
    body: "油圧・電装・機械部品の故障診断から修理、架装ごとの専門修理まで。新明和をはじめとする純正部品で対応します。",
    items: [
      "油圧シリンダ / ポンプ修理",
      "PTO・サブエンジン不調",
      "架装板金・溶接補修",
      "電装系トラブル診断",
    ],
  },
  {
    icon: FileSearch,
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
    icon: PackageCheck,
    eyebrow: "Parts",
    title: "純正部品の手配",
    body: "車台番号と型式から最適な部品を特定し、メーカー純正部品を迅速に手配。過去整備履歴もお伝えします。",
    items: [
      "新明和工業 純正部品",
      "極東開発工業 部品対応",
      "特装系消耗部品在庫",
      "型式照合・代替部品提案",
    ],
  },
  {
    icon: Truck,
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
      <FlowReminderSection />
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
          <span className="text-white">事業・サービス</span>
        </div>
        <div className="flex items-center gap-3 mb-4">
          <DiagonalDivider color="var(--yk-gold)" />
          <span className="font-eyebrow text-xs text-[var(--yk-gold)]">
            Services
          </span>
        </div>
        <h1 className="font-headline text-4xl sm:text-5xl lg:text-6xl font-black leading-tight max-w-3xl">
          整備・修理・点検・架装。
          <br />
          働く車のすべてを、一か所で。
        </h1>
        <p className="text-white/80 mt-6 text-base leading-relaxed max-w-2xl">
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
        <h2 className="font-headline text-3xl sm:text-4xl font-black text-[var(--yk-navy)] leading-tight">
          対応する4つの領域
        </h2>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {SERVICE_CATEGORIES.map((cat) => {
          const Icon = cat.icon;
          return (
            <Card key={cat.title} className="border-border rounded-sm">
              <CardContent className="p-8 space-y-6">
                <div className="flex items-start justify-between">
                  <div className="space-y-2">
                    <div className="font-eyebrow text-xs text-[var(--yk-gold-dark)]">
                      {cat.eyebrow}
                    </div>
                    <h3 className="font-headline text-2xl font-black text-[var(--yk-navy)] leading-tight">
                      {cat.title}
                    </h3>
                  </div>
                  <div className="h-12 w-12 rounded-sm bg-[var(--yk-navy)] text-white flex items-center justify-center shrink-0">
                    <Icon className="h-6 w-6" />
                  </div>
                </div>
                <p className="text-sm text-[var(--yk-steel)] leading-relaxed">
                  {cat.body}
                </p>
                <ul className="space-y-2">
                  {cat.items.map((item) => (
                    <li
                      key={item}
                      className="flex items-start gap-2 text-sm text-[var(--yk-navy-dark)]"
                    >
                      <CheckCircle2 className="h-4 w-4 text-[var(--yk-gold)] shrink-0 mt-0.5" />
                      <span>{item}</span>
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
        <h2 className="font-headline text-3xl sm:text-4xl font-black text-[var(--yk-navy)] leading-tight">
          対応できる車種
        </h2>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {keys.map((key) => {
          const v = VEHICLES[key];
          const Icon = v.icon;
          return (
            <div
              key={key}
              className="bg-white border border-border rounded-sm p-6 space-y-3"
            >
              <div className="flex items-center gap-3">
                <Icon className="h-5 w-5 text-[var(--yk-navy)]" />
                <h3 className="font-headline font-bold text-[var(--yk-navy)]">
                  {v.label}
                </h3>
              </div>
              <p className="text-xs text-[var(--yk-steel)] leading-relaxed pl-8">
                {v.description}
              </p>
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
            <h2 className="font-headline text-3xl font-black leading-tight">
              お問い合わせの前に、
              <br />
              ご準備いただきたいこと
            </h2>
            <p className="text-white/80 leading-relaxed">
              特装車の部品特定には、いくつか固有の情報が必要です。お手元にご用意いただくとスムーズにご案内できます。
            </p>
          </div>
          <div className="p-10 space-y-5">
            <ul className="space-y-4">
              {[
                {
                  t: "車検証",
                  b: "車台番号 / 型式 / 類別区分番号 / 初度登録年月",
                },
                {
                  t: "架装メーカーと型式",
                  b: "車体後部や側面のメーカー銘板に記載",
                },
                {
                  t: "破損箇所の画像・動画",
                  b: "遠景と近景を2〜3枚ずつ。音があれば動画で",
                },
              ].map((item, i) => (
                <li key={item.t} className="flex items-start gap-4">
                  <span className="font-mono-data text-2xl font-black text-[var(--yk-gold-dark)] tabular-nums min-w-[2.5rem]">
                    0{i + 1}
                  </span>
                  <div>
                    <div className="font-headline font-bold text-[var(--yk-navy)]">
                      {item.t}
                    </div>
                    <div className="text-sm text-[var(--yk-steel)]">
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
              <Link href="/demo/yoshikawa-tokuso/contact">
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
