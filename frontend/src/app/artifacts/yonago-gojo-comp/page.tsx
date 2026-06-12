"use client";

import * as React from "react";
import Image from "next/image";
import {
  Instagram,
  MapPin,
  Clock,
  CalendarOff,
  CreditCard,
  Car,
  ArrowUpRight,
  ChevronDown,
} from "lucide-react";
import { LocationMap } from "@/components/templates/location-map";
import { Button } from "@/components/ui/button";
import { FadeIn } from "@/components/motion";
import { CompNav } from "./components/comp-nav";

const INSTAGRAM_URL = "https://www.instagram.com/yonago_gojo/";
const ADDRESS = "鳥取県米子市富士見町2丁目8番 新英会館1F";
const MAP_SRC = `https://maps.google.com/maps?q=${encodeURIComponent(
  "鳥取県米子市富士見町2丁目8番 新英会館",
)}&z=16&output=embed`;

const FACTS = [
  { label: "営業時間", value: "18:00 – 23:00", en: "hours" },
  { label: "定休日", value: "火曜・水曜", en: "closed" },
  { label: "席数", value: "カウンター6 / テーブル2", en: "seats" },
  { label: "お酒", value: "店主セレクトの国産酒", en: "sake" },
];

const SIGNATURE = [
  {
    src: "/yonago-gojo-comp/dish-obanzai.jpg",
    name: "おばんざい3種盛り合わせ",
    price: "800",
    note: "その日の旬を一皿に",
    big: true,
  },
  {
    src: "/yonago-gojo-comp/dish-chawanmushi.jpg",
    name: "冷製茶碗蒸し",
    price: "500",
    note: "つるりと滑らかな口あたり",
  },
  {
    src: "/yonago-gojo-comp/dish-sujikomi.jpg",
    name: "牛すじ煮込み",
    price: "800",
    note: "じっくり炊いた一杯の肴",
  },
  {
    src: "/yonago-gojo-comp/sake-pour.jpg",
    name: "店主が選ぶ国産酒",
    price: "",
    note: "おばんざいに合わせて一献",
  },
];

const STAPLE_MENU = [
  { name: "おばんざい3種盛り合わせ", price: "800" },
  { name: "冷製茶碗蒸し", price: "500" },
  { name: "冷トマトおでん", price: "500" },
  { name: "牛すじ煮込み", price: "800" },
  { name: "大山豚の角煮", price: "950" },
];

const SEASONAL_MENU = [
  { name: "岩牡蠣の昆布締め", note: "隠岐島産・期間限定" },
  { name: "岩牡蠣のアヒージョ", note: "隠岐島産・期間限定" },
  { name: "銀鮭の黒焼き", note: "境港・季節で魚が変わります" },
];

export default function GojoCompPage() {
  return (
    <>
      <CompNav />
      <span id="top" />

      <main className="pb-14 md:pb-0">
        {/* ============ HERO ============ */}
        <section className="relative min-h-[100svh] w-full overflow-hidden">
          <Image
            src="/yonago-gojo-comp/hero-comp.jpg"
            alt="夜のカウンターに並ぶおばんざいと国産酒"
            fill
            priority
            className="object-cover"
            style={{ filter: "brightness(0.62)" }}
            sizes="100vw"
          />
          <div className="absolute inset-0 bg-gradient-to-t from-[var(--gojoc-sumi)] via-[var(--gojoc-sumi)]/25 to-[var(--gojoc-sumi)]/55" />
          <div className="absolute inset-0 bg-gradient-to-r from-[var(--gojoc-sumi)]/75 via-transparent to-transparent" />

          <div className="absolute inset-x-0 bottom-0 z-10">
            <div className="mx-auto w-full max-w-7xl px-6 pb-20 sm:px-8 sm:pb-24">
              <div className="animate-in fade-in slide-in-from-bottom-4 duration-700">
                <div
                  className="font-label text-xs tracking-[0.28em] text-primary sm:text-sm"
                  data-edit-id="gojoc-hero-eyebrow"
                >
                  鳥取・米子　／　おばんざいと国産酒
                </div>
                <h1
                  className="mt-5 font-headline text-[2.9rem] font-bold leading-[1.12] text-white drop-shadow sm:text-6xl lg:text-[5rem] lg:leading-[1.08]"
                  data-edit-id="gojoc-hero-title"
                >
                  旬を肴に、
                  <br />
                  夜をゆっくり。
                </h1>
                <p
                  className="mt-6 max-w-md text-[15px] leading-relaxed text-white/85 sm:text-base"
                  data-edit-id="gojoc-hero-desc"
                >
                  カウンター6席の、小さな隠れ家。店主が選ぶ国産酒と、土からこだわる旬のおばんざいを。
                </p>
                <div className="mt-8 flex flex-wrap items-center gap-3">
                  <Button
                    asChild
                    size="lg"
                    className="rounded-full bg-primary px-7 text-primary-foreground hover:bg-primary/90"
                  >
                    <a href={INSTAGRAM_URL} target="_blank" rel="noopener noreferrer" data-edit-id="gojoc-hero-cta-ig">
                      <Instagram className="mr-2 h-4 w-4" />
                      ご予約・お問い合わせ
                    </a>
                  </Button>
                  <Button
                    asChild
                    size="lg"
                    variant="outline"
                    className="rounded-full border-white/40 bg-white/5 px-7 text-white hover:bg-white/15 hover:text-white"
                  >
                    <a href="#menu" data-edit-id="gojoc-hero-cta-menu">
                      お品書きを見る
                    </a>
                  </Button>
                </div>
              </div>
            </div>
          </div>

          <div className="absolute bottom-5 left-1/2 z-10 hidden -translate-x-1/2 flex-col items-center gap-1 text-white/60 sm:flex">
            <span className="font-en text-[10px] uppercase tracking-[0.3em]">scroll</span>
            <ChevronDown className="h-4 w-4 animate-bounce" />
          </div>
        </section>

        {/* ============ FACTS 帯 ============ */}
        <div className="w-full border-y border-border/50 bg-card/40">
          <div className="mx-auto grid max-w-7xl grid-cols-2 divide-x divide-y divide-border/40 sm:grid-cols-4 sm:divide-y-0">
            {FACTS.map((f) => (
              <div key={f.label} className="px-5 py-6 sm:px-7 sm:py-8">
                <div className="font-en text-[10px] uppercase tracking-[0.22em] text-primary/80">
                  {f.en}
                </div>
                <div className="mt-2 font-label text-[11px] tracking-wider text-muted-foreground">
                  {f.label}
                </div>
                <div className="mt-1 font-headline text-base text-foreground sm:text-lg">
                  {f.value}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* ============ ABOUT ============ */}
        <section id="about" className="mx-auto max-w-7xl px-6 py-24 sm:px-8 sm:py-32">
          <div className="grid grid-cols-1 gap-12 lg:grid-cols-12 lg:gap-16">
            <div className="lg:col-span-5">
              <FadeIn>
                <div className="relative aspect-[3/4] overflow-hidden rounded-sm border border-border/50">
                  <Image
                    src="/yonago-gojo-comp/exterior-noren.jpg"
                    alt="夜の五条の入り口、暖簾と提灯"
                    fill
                    className="object-cover"
                    sizes="(max-width: 1024px) 100vw, 40vw"
                    data-edit-id="gojoc-about-img"
                  />
                </div>
              </FadeIn>
            </div>
            <div className="flex flex-col justify-center lg:col-span-7">
              <div className="font-en text-xs uppercase tracking-[0.3em] text-primary">about</div>
              <FadeIn>
                <h2
                  className="mt-4 font-headline text-3xl leading-[1.5] text-foreground sm:text-[2.6rem]"
                  data-edit-id="gojoc-about-h2"
                >
                  店名は、一匹の猫から。
                </h2>
              </FadeIn>
              <div className="mt-7 space-y-5 text-[15px] leading-[1.95] text-muted-foreground">
                <p data-edit-id="gojoc-about-p1">
                  「五条」という名前は、店主が飼う愛猫「ゴジョー」から。人と人との&ldquo;ご縁&rdquo;をつなぐ存在になりたい——そんな願いが込められています。
                </p>
                <p data-edit-id="gojoc-about-p2">
                  カウンター6席とテーブル2席だけの、小さなお店。店主との会話を肴に、気づけば何度も足を運びたくなる。そんな居心地のよさを大切にしています。
                </p>
                <p data-edit-id="gojoc-about-p3">
                  派手さはなくても、素材とお酒、そして一杯の時間に正直に。米子の夜に、ふらりと寄れる場所であり続けたい。
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* ============ 名物（画像主導メニュー） ============ */}
        <section id="menu" className="w-full bg-card/30 py-24 sm:py-32">
          <div className="mx-auto max-w-7xl px-6 sm:px-8">
            <div className="text-center">
              <div className="font-en text-xs uppercase tracking-[0.3em] text-primary">signature</div>
              <h2
                className="mt-3 font-headline text-3xl text-foreground sm:text-[2.6rem]"
                data-edit-id="gojoc-menu-h2"
              >
                五条の、名物。
              </h2>
              <p
                className="mx-auto mt-4 max-w-xl text-[15px] leading-relaxed text-muted-foreground"
                data-edit-id="gojoc-menu-lead"
              >
                その日の仕入れで内容は変わります。ここに載せきれない一品も、ぜひカウンターで。
              </p>
            </div>

            <div className="mt-14 grid grid-cols-2 gap-4 sm:gap-5 lg:grid-cols-4">
              {SIGNATURE.map((d) => (
                <FadeIn key={d.name}>
                  <div className="group relative aspect-[3/4] overflow-hidden rounded-sm border border-border/50">
                    <Image
                      src={d.src}
                      alt={d.name}
                      fill
                      className="object-cover transition-transform duration-700 group-hover:scale-105"
                      sizes="(max-width: 640px) 50vw, (max-width: 1024px) 50vw, 25vw"
                    />
                    <div className="absolute inset-0 bg-gradient-to-t from-black/85 via-black/15 to-transparent" />
                    <div className="absolute inset-x-0 bottom-0 flex items-end justify-between gap-2 p-4 sm:p-5">
                      <div>
                        <div className="font-headline text-base text-white sm:text-lg">{d.name}</div>
                        <div className="mt-1 text-[11px] text-white/70 sm:text-xs">{d.note}</div>
                      </div>
                      {d.price && (
                        <div className="font-en shrink-0 text-base text-primary sm:text-lg">¥{d.price}</div>
                      )}
                    </div>
                  </div>
                </FadeIn>
              ))}
            </div>

            {/* お品書き（DOMテキスト・完全版） */}
            <div className="mt-16 grid grid-cols-1 gap-12 border-t border-border/40 pt-14 md:grid-cols-2 md:gap-16">
              <div>
                <h3 className="flex items-baseline gap-3 font-headline text-xl text-foreground" data-edit-id="gojoc-staple-h">
                  定番のおばんざい
                  <span className="font-en text-[11px] uppercase tracking-[0.2em] text-primary">staple</span>
                </h3>
                <ul className="mt-6 space-y-1">
                  {STAPLE_MENU.map((m) => (
                    <li key={m.name} className="flex items-baseline gap-2 py-2.5">
                      <span className="text-[15px] text-foreground">{m.name}</span>
                      <span className="mx-1 flex-1 translate-y-[-3px] border-b border-dotted border-border" />
                      <span className="font-en shrink-0 text-base text-primary">¥{m.price}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <h3 className="flex items-baseline gap-3 font-headline text-xl text-foreground" data-edit-id="gojoc-seasonal-h">
                  季節の一品
                  <span className="font-en text-[11px] uppercase tracking-[0.2em] text-primary">seasonal</span>
                </h3>
                <ul className="mt-6 space-y-5">
                  {SEASONAL_MENU.map((m) => (
                    <li key={m.name} className="border-b border-border/50 pb-4">
                      <div className="text-[15px] text-foreground">{m.name}</div>
                      <div className="mt-1 text-xs text-muted-foreground">{m.note}</div>
                    </li>
                  ))}
                </ul>
                <a
                  href={INSTAGRAM_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-6 inline-flex items-center gap-2 text-sm text-primary transition-opacity hover:opacity-70"
                >
                  <Instagram className="h-4 w-4" />
                  本日の一品はInstagramで
                  <ArrowUpRight className="h-3.5 w-3.5" />
                </a>
              </div>
            </div>
            <p className="mt-10 text-center text-xs text-muted-foreground">
              ※ 価格は税込です。仕入れにより内容・価格が変わる場合があります。
            </p>
          </div>
        </section>

        {/* ============ 店内フィーチャー（全画面） ============ */}
        <section id="interior" className="relative isolate w-full overflow-hidden">
          <Image
            src="/yonago-gojo-comp/interior-counter.jpg"
            alt="五条の店内、6席のカウンター"
            fill
            className="-z-20 object-cover"
            sizes="100vw"
          />
          <div className="absolute inset-0 -z-10 bg-gradient-to-r from-[var(--gojoc-sumi)]/92 via-[var(--gojoc-sumi)]/55 to-[var(--gojoc-sumi)]/20" />
          <div className="mx-auto max-w-7xl px-6 py-32 sm:px-8 sm:py-44">
            <FadeIn>
              <div className="max-w-xl">
                <div className="font-en text-xs uppercase tracking-[0.3em] text-primary">interior</div>
                <h2
                  className="mt-4 font-headline text-3xl leading-snug text-white sm:text-[2.8rem]"
                  data-edit-id="gojoc-interior-h2"
                >
                  カウンター6席の、
                  <br />
                  小さな隠れ家。
                </h2>
                <p className="mt-5 text-base leading-relaxed text-white/80" data-edit-id="gojoc-interior-p">
                  店主との会話を肴に、気づけば何度も足を運びたくなる。米子の夜に、ふらりと寄れる場所です。
                </p>
              </div>
            </FadeIn>
          </div>
        </section>

        {/* ============ ACCESS ============ */}
        <section id="access" className="mx-auto max-w-7xl px-6 py-24 sm:px-8 sm:py-32">
          <div className="grid grid-cols-1 gap-12 lg:grid-cols-2 lg:gap-16">
            <div>
              <div className="font-en text-xs uppercase tracking-[0.3em] text-primary">access</div>
              <h2
                className="mt-3 font-headline text-3xl text-foreground sm:text-[2.6rem]"
                data-edit-id="gojoc-access-h2"
              >
                お越しの際は
              </h2>
              <dl className="mt-9 space-y-6">
                {[
                  { icon: MapPin, label: "住所", value: ADDRESS },
                  { icon: Clock, label: "営業時間", value: "18:00 – 23:00" },
                  { icon: CalendarOff, label: "定休日", value: "火曜・水曜" },
                  { icon: CreditCard, label: "お支払い", value: "現金・各種カード・PayPay" },
                  { icon: Car, label: "駐車場", value: "専用駐車場なし（近隣に有料駐車場あり）" },
                ].map((row) => (
                  <div key={row.label} className="flex gap-4 border-b border-border/40 pb-5">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary/15 text-primary">
                      <row.icon className="h-4 w-4" />
                    </span>
                    <div>
                      <dt className="font-label text-[11px] uppercase tracking-wider text-muted-foreground">
                        {row.label}
                      </dt>
                      <dd className="mt-1 text-[15px] text-foreground">{row.value}</dd>
                    </div>
                  </div>
                ))}
              </dl>
              <Button
                asChild
                size="lg"
                className="mt-9 rounded-full bg-primary px-7 text-primary-foreground hover:bg-primary/90"
              >
                <a href={INSTAGRAM_URL} target="_blank" rel="noopener noreferrer">
                  <Instagram className="mr-2 h-4 w-4" />
                  ご予約・お問い合わせはDMで
                </a>
              </Button>
            </div>
            <div>
              <LocationMap
                src={MAP_SRC}
                address={ADDRESS}
                caption="JR米子駅から徒歩圏・富士見町 新英会館1F"
                aspectRatio="4/3"
              />
            </div>
          </div>
        </section>

        {/* ============ CTA ============ */}
        <section className="relative isolate w-full overflow-hidden">
          <Image
            src="/yonago-gojo-comp/plating.jpg"
            alt=""
            fill
            aria-hidden
            className="-z-20 object-cover"
            sizes="100vw"
          />
          <div className="absolute inset-0 -z-10 bg-gradient-to-r from-[var(--gojoc-sumi)]/95 via-[var(--gojoc-sumi)]/80 to-[var(--gojoc-sumi)]/45" />
          <div className="mx-auto max-w-7xl px-6 py-28 sm:px-8 sm:py-36">
            <FadeIn>
              <div className="max-w-xl">
                <div className="font-en text-xs uppercase tracking-[0.3em] text-primary">tonight at gojo</div>
                <h2
                  className="mt-4 font-headline text-4xl leading-tight text-white sm:text-6xl"
                  data-edit-id="gojoc-cta-h2"
                >
                  今夜、五条で。
                </h2>
                <p className="mt-5 text-base leading-relaxed text-white/80">
                  旬のおばんざいと、店主の一杯を。ご予約・お問い合わせはInstagramのDMからどうぞ。
                </p>
                <Button
                  asChild
                  size="lg"
                  className="mt-8 rounded-full bg-primary px-7 text-primary-foreground hover:bg-primary/90"
                >
                  <a href={INSTAGRAM_URL} target="_blank" rel="noopener noreferrer">
                    <Instagram className="mr-2 h-4 w-4" />
                    Instagramを見る・予約する
                  </a>
                </Button>
              </div>
            </FadeIn>
          </div>
        </section>

        {/* ============ FOOTER ============ */}
        <footer className="w-full border-t border-border/50 bg-background">
          <div className="mx-auto max-w-7xl px-6 py-12 sm:px-8">
            <div className="flex flex-col gap-8 sm:flex-row sm:items-end sm:justify-between">
              <div className="flex items-center gap-4">
                <span className="relative h-12 w-12 overflow-hidden rounded-full bg-white/90 ring-1 ring-border">
                  <Image
                    src="/yonago-gojo/logo.jpg"
                    alt="OBANZAI bar 五条 ロゴ"
                    fill
                    className="object-cover"
                    sizes="48px"
                  />
                </span>
                <div>
                  <div className="font-headline text-lg text-foreground">おばんざいバー 五条</div>
                  <div className="mt-1 text-sm text-muted-foreground">{ADDRESS}</div>
                  <div className="text-sm text-muted-foreground">18:00–23:00 / 定休 火・水</div>
                </div>
              </div>
              <a
                href={INSTAGRAM_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 text-sm text-muted-foreground transition-colors hover:text-foreground"
              >
                <Instagram className="h-4 w-4" />
                @yonago_gojo
              </a>
            </div>
            <div className="mt-8 border-t border-border/50 pt-6 font-en text-xs tracking-wider text-muted-foreground">
              © {new Date().getFullYear()} OBANZAI bar 五条 · 米子 · 富士見町
            </div>
          </div>
        </footer>
      </main>
    </>
  );
}
