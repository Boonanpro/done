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
  Wine,
  Soup,
  Leaf,
  ArrowRight,
} from "lucide-react";
import { LpShell } from "@/components/templates/lp-shell";
import { FullBleedVideoHero } from "@/components/templates/full-bleed-video-hero";
import { Section } from "@/components/templates/section";
import { LocationMap } from "@/components/templates/location-map";
import { Button } from "@/components/ui/button";

const INSTAGRAM_URL = "https://www.instagram.com/yonago_gojo/";
const ADDRESS = "鳥取県米子市富士見町2丁目8番 新英会館1F";
const MAP_SRC = `https://maps.google.com/maps?q=${encodeURIComponent(
  "鳥取県米子市富士見町2丁目8番 新英会館",
)}&z=16&output=embed`;

const NAV = [
  { label: "五条について", href: "#about" },
  { label: "こだわり", href: "#craft" },
  { label: "お品書き", href: "#menu" },
  { label: "アクセス", href: "#access" },
];

const FACTS = [
  { icon: Clock, label: "営業時間", value: "18:00 – 23:00" },
  { icon: CalendarOff, label: "定休日", value: "火曜・水曜" },
  { icon: MapPin, label: "席数", value: "カウンター6 / テーブル2" },
  { icon: Wine, label: "お酒", value: "店主セレクトの国産酒" },
];

const CRAFT = [
  {
    icon: Soup,
    title: "旬のおばんざい",
    body: "家庭の味を一品ずつ、ていねいに。冷製茶碗蒸しや牛すじ煮込みなど、その日の仕入れで顔ぶれが変わります。",
  },
  {
    icon: Leaf,
    title: "土からこだわる野菜",
    body: "野菜は土作りからこだわるグリーンファーム清水のもの。素材そのものの力を、シンプルに味わってもらいます。",
  },
  {
    icon: Wine,
    title: "店主が選ぶ国産酒",
    body: "全国から選んだ日本酒を、その日のおばんざいに合わせて。カウンター越しに、好みを聞きながら一杯を。",
  },
];

const STAPLE = [
  { name: "おばんざい3種盛り合わせ", price: "800" },
  { name: "冷製茶碗蒸し", price: "500" },
  { name: "冷トマトおでん", price: "500" },
  { name: "牛すじ煮込み", price: "800" },
  { name: "大山豚の角煮", price: "950" },
];

const SEASONAL = [
  { name: "岩牡蠣の昆布締め", note: "隠岐島産・期間限定" },
  { name: "岩牡蠣のアヒージョ", note: "隠岐島産・期間限定" },
  { name: "銀鮭の黒焼き", note: "境港・季節で魚が変わります" },
];

const GALLERY = [
  { src: "/yonago-gojo/g1.jpg", alt: "カウンターで仕込みをする店主" },
  { src: "/yonago-gojo/g4.jpg", alt: "白身魚を捌くようす" },
  { src: "/yonago-gojo/g2.jpg", alt: "板場のようす" },
  { src: "/yonago-gojo/dish-poster.jpg", alt: "まな板の上の鮮魚" },
  { src: "/yonago-gojo/g3.jpg", alt: "厨房の手元" },
  { src: "/yonago-gojo/g5.jpg", alt: "盛り付け前の魚" },
];

const ACCESS = [
  { icon: MapPin, label: "住所", value: ADDRESS },
  { icon: Clock, label: "営業時間", value: "18:00 – 23:00" },
  { icon: CalendarOff, label: "定休日", value: "火曜・水曜" },
  { icon: CreditCard, label: "お支払い", value: "現金・各種カード・PayPay" },
  { icon: Car, label: "駐車場", value: "専用駐車場なし（近隣に有料駐車場あり）" },
];

export default function Page() {
  return (
    <LpShell
      nav={
        <nav className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3 sm:px-6">
          <a href="#top" className="flex items-center gap-3">
            <span className="relative h-10 w-10 overflow-hidden rounded-full bg-white/90 ring-1 ring-border">
              <Image
                src="/yonago-gojo/logo.jpg"
                alt="OBANZAI bar 五条 ロゴ"
                fill
                className="object-cover"
                sizes="40px"
              />
            </span>
            <span className="leading-tight">
              <span className="block font-headline text-base text-foreground">
                おばんざいバー 五条
              </span>
              <span className="font-en block text-[11px] tracking-widest text-muted-foreground">
                OBANZAI bar GOJO ・ 米子
              </span>
            </span>
          </a>
          <div className="hidden items-center gap-7 md:flex">
            {NAV.map((item) => (
              <a
                key={item.href}
                href={item.href}
                className="font-label text-sm text-muted-foreground transition-colors hover:text-foreground"
              >
                {item.label}
              </a>
            ))}
          </div>
          <Button
            asChild
            size="sm"
            className="rounded-full bg-primary text-primary-foreground hover:bg-primary/90"
          >
            <a href={INSTAGRAM_URL} target="_blank" rel="noopener noreferrer">
              <Instagram className="mr-1.5 h-4 w-4" />
              Instagram
            </a>
          </Button>
        </nav>
      }
      footer={
        <div className="mx-auto max-w-7xl px-4 py-12 sm:px-6">
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
                <div className="font-headline text-lg text-foreground">
                  おばんざいバー 五条
                </div>
                <div className="mt-1 text-sm text-muted-foreground">{ADDRESS}</div>
                <div className="text-sm text-muted-foreground">
                  18:00–23:00 / 定休 火・水
                </div>
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
          <div className="mt-8 border-t border-border/60 pt-6 text-xs text-muted-foreground">
            © {new Date().getFullYear()} OBANZAI bar 五条 / 米子・富士見町
          </div>
        </div>
      }
    >
      <span id="top" />

      <FullBleedVideoHero
        src="/yonago-gojo/hero-pc.mp4"
        mobileSrc="/yonago-gojo/hero-mobile.mp4"
        poster="/yonago-gojo/hero-poster.jpg"
        darken={46}
        minHeightClass="min-h-[92vh]"
        align="left"
        contentWidth="lg"
        videoLabel="五条の板場のようす"
        eyebrow={
          <span className="font-label">
            鳥取・米子 富士見町 ／ おばんざいと国産酒
          </span>
        }
        title={
          <span>
            おばんざいと、
            <br className="hidden sm:block" />
            ご縁の集まる夜。
          </span>
        }
        description={
          <span>
            カウンター6席の、小さな隠れ家。店主が選ぶ国産酒と、土からこだわる旬のおばんざいを、ゆっくりと。
          </span>
        }
        actions={
          <>
            <Button
              asChild
              size="lg"
              className="rounded-full bg-primary text-primary-foreground hover:bg-primary/90"
            >
              <a href="#access">
                <MapPin className="mr-2 h-4 w-4" />
                お店の場所を見る
              </a>
            </Button>
            <Button
              asChild
              size="lg"
              variant="outline"
              className="rounded-full border-white/40 bg-white/5 text-white hover:bg-white/15"
            >
              <a href={INSTAGRAM_URL} target="_blank" rel="noopener noreferrer">
                <Instagram className="mr-2 h-4 w-4" />
                Instagramで見る
              </a>
            </Button>
          </>
        }
      />

      {/* FACTS 帯 */}
      <div className="w-full border-y border-border/60 bg-card/40">
        <div className="mx-auto grid max-w-7xl grid-cols-2 divide-x divide-border/50 sm:grid-cols-4">
          {FACTS.map((fact) => {
            const Icon = fact.icon;
            return (
              <div
                key={fact.label}
                className="flex flex-col gap-1 px-4 py-6 sm:px-6 sm:py-7"
              >
                <Icon className="h-4 w-4 text-primary" />
                <div className="mt-1 font-label text-[11px] uppercase tracking-wider text-muted-foreground">
                  {fact.label}
                </div>
                <div className="font-headline text-base text-foreground sm:text-lg">
                  {fact.value}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* About */}
      <Section id="about" width="xl" padding="lg">
        <div className="grid grid-cols-1 items-center gap-10 lg:grid-cols-2 lg:gap-16">
          <div className="order-2 lg:order-1">
            <div className="font-label text-xs uppercase tracking-[0.18em] text-primary">
              About
            </div>
            <h2 className="mt-4 text-3xl leading-snug sm:text-4xl">
              店名は、一匹の猫から。
            </h2>
            <div className="mt-6 space-y-5 text-[15px] leading-relaxed text-muted-foreground">
              <p>
                「五条」という名前は、店主が飼う愛猫「ゴジョー」から。人と人との“ご縁”をつなぐ存在になりたい——そんな願いが込められています。
              </p>
              <p>
                カウンター6席とテーブル2席だけの、小さなお店。店主との会話を肴に、気づけば何度も足を運びたくなる。そんな居心地のよさを大切にしています。
              </p>
              <p>
                派手さはなくても、素材とお酒、そして一杯の時間に正直に。米子の夜に、ふらりと寄れる場所であり続けたい。
              </p>
            </div>
          </div>
          <div className="order-1 overflow-hidden rounded-xl border border-border/60 lg:order-2">
            <Image
              src="/yonago-gojo/g1.jpg"
              alt="カウンターで仕込みをする店主"
              width={1280}
              height={720}
              className="h-full w-full object-cover"
            />
          </div>
        </div>
      </Section>

      {/* Craft */}
      <div id="craft" className="w-full bg-card/40 py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <div className="max-w-2xl">
            <div className="font-label text-xs uppercase tracking-[0.18em] text-primary">
              Craft
            </div>
            <h2 className="mt-4 text-3xl sm:text-4xl">一品一品に、手をかけて。</h2>
            <p className="mt-4 text-[15px] leading-relaxed text-muted-foreground">
              その日の魚を捌き、旬の野菜を炊く。仕込みの風景そのものが、五条の味わいです。
            </p>
          </div>
          <div className="mt-12 grid grid-cols-1 gap-8 lg:grid-cols-2 lg:items-center lg:gap-14">
            <div className="overflow-hidden rounded-xl border border-border/60 shadow-lg shadow-black/30">
              <video
                src="/yonago-gojo/dish.mp4"
                poster="/yonago-gojo/dish-poster.jpg"
                autoPlay
                loop
                muted
                playsInline
                preload="metadata"
                aria-label="魚を捌く店主の手元"
                className="aspect-video h-full w-full object-cover"
              />
            </div>
            <div className="grid grid-cols-1 gap-6">
              {CRAFT.map((item) => {
                const Icon = item.icon;
                return (
                  <div
                    key={item.title}
                    className="flex gap-4 rounded-lg border border-border/50 bg-background/40 p-5"
                  >
                    <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-primary/15 text-primary">
                      <Icon className="h-5 w-5" />
                    </span>
                    <div>
                      <h3 className="text-lg">{item.title}</h3>
                      <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
                        {item.body}
                      </p>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>

      {/* Menu */}
      <Section id="menu" width="lg" padding="lg">
        <div className="text-center">
          <div className="font-label text-xs uppercase tracking-[0.18em] text-primary">
            Menu
          </div>
          <h2 className="mt-4 text-3xl sm:text-4xl">お品書き</h2>
          <p className="mx-auto mt-4 max-w-xl text-[15px] leading-relaxed text-muted-foreground">
            その日の仕入れで内容は変わります。ここに載せきれない一品も、ぜひカウンターで。
          </p>
        </div>
        <div className="mt-12 grid grid-cols-1 gap-10 md:grid-cols-2">
          <div className="rounded-xl border border-border/60 bg-card/50 p-7 sm:p-8">
            <h3 className="text-xl">定番のおばんざい</h3>
            <ul className="mt-6 divide-y divide-border/50">
              {STAPLE.map((item) => (
                <li
                  key={item.name}
                  className="flex items-baseline justify-between gap-4 py-3.5"
                >
                  <span className="text-[15px] text-foreground">{item.name}</span>
                  <span className="font-en shrink-0 text-base text-primary">
                    ¥{item.price}
                  </span>
                </li>
              ))}
            </ul>
          </div>
          <div className="rounded-xl border border-border/60 bg-card/50 p-7 sm:p-8">
            <h3 className="text-xl">季節の一品</h3>
            <ul className="mt-6 space-y-5">
              {SEASONAL.map((item) => (
                <li key={item.name}>
                  <div className="text-[15px] text-foreground">{item.name}</div>
                  <div className="mt-0.5 text-xs text-muted-foreground">
                    {item.note}
                  </div>
                </li>
              ))}
            </ul>
            <a
              href={INSTAGRAM_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-7 inline-flex items-center gap-2 text-sm text-primary transition-opacity hover:opacity-80"
            >
              <Instagram className="h-4 w-4" />
              本日の一品はInstagramで
              <ArrowRight className="h-3.5 w-3.5" />
            </a>
          </div>
        </div>
        <p className="mt-8 text-center text-xs text-muted-foreground">
          ※ 価格は税込です。仕入れにより内容・価格が変わる場合があります。
        </p>
      </Section>

      {/* Gallery */}
      <Section width="xl" padding="md">
        <div className="mb-8 flex items-end justify-between">
          <div>
            <div className="font-label text-xs uppercase tracking-[0.18em] text-primary">
              Gallery
            </div>
            <h2 className="mt-3 text-2xl sm:text-3xl">店内・調理の風景</h2>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4">
          {GALLERY.map((item, index) => (
            <div
              key={item.src}
              className={`overflow-hidden rounded-lg border border-border/50 ${
                index === 0
                  ? "col-span-2 row-span-2 sm:col-span-2 sm:row-span-2"
                  : ""
              }`}
            >
              <Image
                src={item.src}
                alt={item.alt}
                width={1280}
                height={720}
                className="h-full w-full object-cover transition-transform duration-500 hover:scale-105"
              />
            </div>
          ))}
        </div>
      </Section>

      {/* Access */}
      <div id="access" className="w-full bg-card/40 py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <div className="grid grid-cols-1 gap-10 lg:grid-cols-2 lg:gap-16">
            <div>
              <div className="font-label text-xs uppercase tracking-[0.18em] text-primary">
                Access
              </div>
              <h2 className="mt-4 text-3xl sm:text-4xl">お越しの際は</h2>
              <dl className="mt-8 space-y-5">
                {ACCESS.map((row) => {
                  const Icon = row.icon;
                  return (
                    <div key={row.label} className="flex gap-4">
                      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary/15 text-primary">
                        <Icon className="h-4 w-4" />
                      </span>
                      <div>
                        <dt className="font-label text-xs uppercase tracking-wider text-muted-foreground">
                          {row.label}
                        </dt>
                        <dd className="mt-0.5 text-[15px] text-foreground">
                          {row.value}
                        </dd>
                      </div>
                    </div>
                  );
                })}
              </dl>
              <Button
                asChild
                size="lg"
                className="mt-9 rounded-full bg-primary text-primary-foreground hover:bg-primary/90"
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
        </div>
      </div>

      {/* CTA */}
      <section className="relative isolate w-full overflow-hidden">
        <Image
          src="/yonago-gojo/g2.jpg"
          alt=""
          fill
          className="-z-20 object-cover"
          aria-hidden
        />
        <div className="absolute inset-0 -z-10 bg-gradient-to-r from-[var(--gojo-sumi)]/95 via-[var(--gojo-sumi)]/85 to-[var(--gojo-sumi)]/60" />
        <div className="mx-auto max-w-7xl px-4 py-24 sm:px-6 sm:py-32">
          <div className="max-w-xl">
            <h2 className="text-4xl leading-tight text-white sm:text-5xl">
              今夜、五条で。
            </h2>
            <p className="mt-5 text-base leading-relaxed text-white/80">
              旬のおばんざいと、店主の一杯を。ご予約・お問い合わせはInstagramのDMからどうぞ。
            </p>
            <Button
              asChild
              size="lg"
              className="mt-8 rounded-full bg-primary text-primary-foreground hover:bg-primary/90"
            >
              <a href={INSTAGRAM_URL} target="_blank" rel="noopener noreferrer">
                <Instagram className="mr-2 h-4 w-4" />
                Instagramを見る・予約する
              </a>
            </Button>
          </div>
        </div>
      </section>
    </LpShell>
  );
}
