import { ArtifactLink as Link } from "@/components/artifacts/artifact-link";
import { Phone, ArrowRight } from "lucide-react";
import { LpShell } from "@/components/templates/lp-shell";
import { Button } from "@/components/ui/button";
import { SiteNav } from "../components/site-nav";
import { SiteFooter } from "../components/site-footer";
import { HeroSplit } from "./hero-split";
import { PartsMarquee } from "./vehicle-carousel";
import { PerspectiveCarousel } from "./perspective-carousel";
import { V2ModeMarker } from "./v2-mode-marker";
import {
  StatsSection,
  ManufacturersSection,
  ServicesSummarySection,
  CareersCtaSection,
} from "../page";

const PARTS = [
  "cylinder", "brake-disc", "oil-filter", "v-belt", "pump",
  "tire", "headlight", "bolt-set", "valve", "muffler",
];

const ASSET_VERSION = process.env.NEXT_PUBLIC_ASSET_VERSION || "dev";
const HERO_VIDEO = `/kikkawa/hero-pc-v4.mp4?v=${ASSET_VERSION}`;
const HERO_VIDEO_MOBILE = `/kikkawa/hero-mobile-v4.mp4?v=${ASSET_VERSION}`;
const HERO_POSTER = `/kikkawa/hero-pc-poster-v3.jpg?v=${ASSET_VERSION}`;
const HERO_POSTER_MOBILE = `/kikkawa/hero-mobile-poster-v3.jpg?v=${ASSET_VERSION}`;

const VEHICLES = [
  "dump", "garbage", "tailgate", "crane", "tanker",
  "aerial", "mixer", "feed", "hook", "snowplow", "vacuum",
];

const VEHICLE_LABELS: Record<string, { en: string; ja: string }> = {
  dump: { en: "DUMP TRUCK", ja: "ダンプ" },
  garbage: { en: "GARBAGE TRUCK", ja: "塵芥車" },
  tailgate: { en: "TAILGATE LIFT", ja: "テールゲート" },
  crane: { en: "CRANE TRUCK", ja: "クレーン車" },
  tanker: { en: "TANKER TRUCK", ja: "タンク車" },
  aerial: { en: "AERIAL PLATFORM", ja: "高所作業車" },
  mixer: { en: "MIXER TRUCK", ja: "ミキサー車" },
  feed: { en: "FEED CARRIER", ja: "飼料運搬車" },
  hook: { en: "HOOK LOADER", ja: "脱着車" },
  snowplow: { en: "SNOW PLOW", ja: "除雪車" },
  vacuum: { en: "VACUUM TRUCK", ja: "バキューム車" },
};

const SCENE_CUT_POINTS = [5.54, 9.34, 12.91, 22.92];

export const metadata = {
  title: "吉川特装 v2 案 | 米子の特装車整備工場",
  description: "ゴミ収集車・ダンプ・クレーン車の修理・部品販売。鳥取県米子市の特装車整備工場。",
};

export default function YoshikawaV2HomePage() {
  return (
    <LpShell nav={<SiteNav homeHref="/artifacts/kittoku/v2" />} footer={<SiteFooter />} className="bg-background text-foreground">
      <V2ModeMarker />
      <HeroV2 />
      {/* 部品帯: section の外 (PC・スマホ共通でスクロールしないと見えない) */}
      <PartsBand />
      <StatsSection />
      <ManufacturersSection />
      <ServicesSummarySection />
      <VehiclesSectionV2 />
      <CareersCtaSection />
    </LpShell>
  );
}

function PartsBand({ className = "" }: { className?: string }) {
  return (
    <div className={`bg-[var(--yk-navy-dark)] py-2 sm:py-3 ${className}`}>
      <PartsMarquee
        items={PARTS}
        basePath="/kikkawa/v2/parts"
        assetVersion={ASSET_VERSION}
        size={60}
        speed={0}
        initialCenterIndex={PARTS.indexOf("bolt-set")}
      />
    </div>
  );
}

function HeroV2() {
  return (
    <section className="relative bg-[var(--yk-navy-dark)] text-white overflow-hidden flex flex-col h-[calc(100svh-56px)] sm:h-[calc(100vh-80px)] sm:min-h-[620px]">
      {/* ヒーロー本体 (動画+車+コピー) */}
      <div className="relative flex-1 overflow-hidden">
        {/* メインコピー (中央コンテナ max-w-7xl の左上、 車と左右の余白を揃える) */}
        <div className="absolute inset-0 pointer-events-none flex justify-center z-20">
          <div className="relative w-full max-w-7xl px-4 sm:px-8">
            <div className="absolute top-4 sm:top-10 left-4 sm:left-8 max-w-[68%] sm:max-w-[42%] pointer-events-auto">
              <h1
                data-edit-id="kittoku-v2-hero-h1"
                className="font-headline text-lg sm:text-3xl lg:text-5xl text-white font-bold tracking-tight leading-[1.25] drop-shadow-[0_2px_14px_rgba(0,0,0,0.9)]"
              >
                はたらく車を、
                <br />
                直す工場。
              </h1>
            </div>
          </div>
        </div>

        <HeroSplit
          videoSrc={HERO_VIDEO}
          videoPoster={HERO_POSTER}
          mobileVideoSrc={HERO_VIDEO_MOBILE}
          mobileVideoPoster={HERO_POSTER_MOBILE}
          vehicles={VEHICLES}
          vehiclesBasePath="/kikkawa/v2/vehicles"
          assetVersion={ASSET_VERSION}
          sceneCutPoints={SCENE_CUT_POINTS}
          vehicleLabels={VEHICLE_LABELS}
        />
      </div>

      {/* CTAバー + パーツマーキー帯 (連続した navy 背景) */}
      <div className="relative flex-shrink-0 bg-[var(--yk-navy-dark)]">
        <div>
          <div className="px-4 sm:px-10 py-3 sm:py-5 max-w-6xl mx-auto">
            <div className="grid grid-cols-2 gap-3 sm:gap-6 items-center">
              {/* 左: 電話番号 */}
              <a
                href="tel:0859-27-4885"
                className="flex items-center gap-2 sm:gap-3 text-white hover:text-[var(--yk-gold)] transition-colors"
              >
                <Phone className="h-4 w-4 sm:h-6 sm:w-6 shrink-0" />
                <div className="flex flex-col leading-none">
                  <span className="font-mono-data text-base sm:text-3xl lg:text-4xl font-bold tracking-tight whitespace-nowrap">
                    0859-27-4885
                  </span>
                  <span className="font-mono-data text-[9px] sm:text-xs text-white/45 mt-1 sm:mt-1.5 whitespace-nowrap">
                    月〜土 9:00〜17:00
                  </span>
                  <span className="font-mono-data text-[8px] sm:text-[10px] text-white/35 mt-0.5 whitespace-nowrap">
                    ※毎月第2土曜は定休日
                  </span>
                </div>
              </a>

              {/* 右: 注文ボタン */}
              <div className="flex justify-end">
                <Button
                  asChild
                  size="lg"
                  className="bg-[var(--yk-gold)] hover:bg-[var(--yk-gold-dark)] text-[var(--yk-navy-dark)] font-bold rounded-sm h-11 sm:h-14 px-3 sm:px-7 text-xs sm:text-base animate-kk-cta whitespace-nowrap"
                >
                  <Link data-edit-id="kittoku-v2-hero-cta" href="/artifacts/kittoku/contact">
                    部品注文はこちら
                    <ArrowRight className="h-3.5 w-3.5 sm:h-5 sm:w-5 ml-1 sm:ml-2" />
                  </Link>
                </Button>
              </div>
            </div>
          </div>
        </div>
      </div>

    </section>
  );
}

function VehiclesSectionV2() {
  return (
    <section className="relative overflow-hidden bg-[var(--yk-navy-dark)] text-white py-16 sm:py-24 lg:py-28">
      {/* 上下の細い金線 */}
      <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-[var(--yk-gold)]/40 to-transparent" />
      <div className="absolute bottom-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-[var(--yk-gold)]/40 to-transparent" />

      {/* 背景の極薄スポット */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background:
            "radial-gradient(ellipse 70% 55% at 50% 50%, rgba(212,175,89,0.06) 0%, transparent 75%)",
        }}
      />

      {/* 見出し */}
      <div className="relative max-w-7xl mx-auto px-4 sm:px-6 mb-10 sm:mb-14 lg:mb-16">
        <div className="space-y-3">
          <div className="flex items-center gap-3">
            <span className="h-px w-10 bg-[var(--yk-gold)]/60" />
            <span className="font-eyebrow text-[10px] sm:text-xs text-[var(--yk-gold)] tracking-[0.35em]">
              Vehicles
            </span>
          </div>
          <div className="flex flex-col lg:flex-row lg:items-end lg:justify-between gap-3 lg:gap-8">
            <h2 className="font-headline text-3xl sm:text-5xl lg:text-6xl font-black leading-[1.15] tracking-tight text-white">
              特装車なら、
              <br />
              何でもお任せください。
            </h2>
            <p className="text-white/55 max-w-md text-sm sm:text-base leading-relaxed">
              特装車・特殊車両なら全車種ご対応可能。指でスワイプして車種をご覧いただけます。
            </p>
          </div>
        </div>
      </div>

      <PerspectiveCarousel
        items={VEHICLES}
        labels={VEHICLE_LABELS}
        basePath="/kikkawa/v2/vehicles"
        assetVersion={ASSET_VERSION}
      />
    </section>
  );
}
