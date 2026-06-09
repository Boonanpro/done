"use client";

import * as React from "react";
import {
  Instagram,
  MapPin,
  Clock,
  CalendarOff,
  CreditCard,
  Car,
} from "lucide-react";
import { LocationMap } from "@/components/templates/location-map";
import { Button } from "@/components/ui/button";
import { FadeIn, ParallaxMedia } from "@/components/motion";
import { CraftStory } from "./components/craft-story";
import {
  SectionKicker,
  SectionTitle,
  BodyCopy,
  EditorialButton,
  RoundelBadge,
  RuleDivider,
  SealMark,
  BrushStroke,
} from "@/components/templates";
import { GojoNav } from "./components/gojo-nav";
import { HeroPinnedMedia } from "./components/hero-pinned-media";

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


const GALLERY = [
  { src: "/yonago-gojo/g1.jpg", alt: "カウンターで仕込みをする店主", span: "col-span-2 row-span-2" },
  { src: "/yonago-gojo/g4.jpg", alt: "白身魚を捌くようす", span: "" },
  { src: "/yonago-gojo/g2.jpg", alt: "板場のようす", span: "" },
  { src: "/yonago-gojo/dish-poster.jpg", alt: "まな板の上の鮮魚", span: "" },
  { src: "/yonago-gojo/g3.jpg", alt: "厨房の手元", span: "" },
];

const CRAFT = [
  {
    no: "壱",
    eyebrow: "旬のおばんざい",
    title: "その日の地魚と、土の野菜。",
    body: "その日の地魚を捌き、土作りからこだわるグリーンファーム清水の野菜を炊く。家庭の味を一品ずつ、ていねいに。仕入れで顔ぶれが変わります。",
    media: {
      type: "video" as const,
      src: "/yonago-gojo/dish.mp4",
      poster: "/yonago-gojo/dish-poster.jpg",
      alt: "魚を捌く店主の手元",
    },
  },
  {
    no: "弐",
    eyebrow: "釜炊きのご飯",
    title: "香ばしい、おこげまで。",
    body: "小さな羽釜で一合ずつ炊き上げ、仕上げはおこげをひとすくい。湯気の立つうちに、目の前へ。〆まで楽しんでもらいます。",
    media: {
      type: "video" as const,
      src: "/yonago-gojo/rice.mp4",
      poster: "/yonago-gojo/rice-poster.jpg",
      alt: "羽釜で炊いたご飯をよそう店主",
    },
  },
  {
    no: "参",
    eyebrow: "店主が選ぶ国産酒",
    title: "その日の一品に、合わせて。",
    body: "全国から選んだ日本酒・焼酎・クラフトジン。カウンター越しに好みを聞きながら、その日のおばんざいに合う一杯を。",
    media: {
      type: "video" as const,
      src: "/yonago-gojo/sake.mp4",
      poster: "/yonago-gojo/sake-poster.jpg",
      alt: "棚に並ぶ国産酒のボトル",
    },
  },
];

const FOODS = [
  { src: "/yonago-gojo/food-fish.jpg", name: "旬の地魚 塩焼き", note: "境港・その日の魚で" },
  { src: "/yonago-gojo/food-kakuni.jpg", name: "大山豚の角煮", note: "とろりと炊いた看板の一品" },
  { src: "/yonago-gojo/food-katsu.jpg", name: "揚げたてメンチカツ", note: "サラダ添え" },
  { src: "/yonago-gojo/food-sausage.jpg", name: "ソーセージ盛り合わせ", note: "お酒のおともに" },
  { src: "/yonago-gojo/food-shellfish.jpg", name: "季節の貝の和え物", note: "大葉をのせて" },
  { src: "/yonago-gojo/food-cheese.jpg", name: "レーズンバター", note: "クラッカーと一緒に" },
];

const FIRST_TIME = [
  {
    q: "おひとりでも大丈夫？",
    a: "もちろんです。カウンター6席・テーブル2席の小さな店。おひとりでも、気のおけない仲間とも、肩肘張らずにどうぞ。",
  },
  {
    q: "予約はできますか？",
    a: "お席に限りがあるので、ご予約はInstagramのDMが確実です。空き状況もお気軽にお問い合わせください。",
  },
  {
    q: "メニューは決まっている？",
    a: "おばんざいはその日の仕入れで替わります。本日の一品は、Instagramでお知らせしています。",
  },
  {
    q: "駐車場はありますか？",
    a: "お店の隣に有料駐車場があります。",
  },
];

function CraftMedia({ media }: { media: (typeof CRAFT)[number]["media"] }) {
  if (media.type === "video") {
    return (
      <video
        src={media.src}
        poster={media.poster}
        autoPlay
        loop
        muted
        playsInline
        preload="metadata"
        aria-label={media.alt}
        className="h-full w-full object-cover"
      />
    );
  }

  return (
    <img
      src={media.src}
      alt={media.alt}
      className="h-full w-full object-cover"
    />
  );
}

export default function GojoPage() {
  return (
    <>
      <GojoNav />
      <span id="top" />

      <main className="pt-0 pb-16 lg:pb-0">
        {/* 画面に完全固定するヒーロー映像（背景） */}
        <HeroPinnedMedia />

        {/* ============ HERO（映像は固定。ロゴ/バッジ/文字だけが上を流れる） ============ */}
        <section className="relative w-full">
          <div className="relative z-10 lg:pl-[200px]">
            {/* 第一画面: ロゴ＋丸バッジ */}
            <div className="flex min-h-[100svh] flex-col justify-end">
              <div className="mx-auto w-full max-w-7xl px-6 pb-20 sm:px-10 sm:pb-14">
                <div className="flex animate-in fade-in slide-in-from-bottom-3 flex-col items-start gap-8 duration-1000 sm:flex-row sm:items-end sm:justify-between">
                  <img
                    src="/yonago-gojo/hero-wordmark.png"
                    alt="おばんざいbar"
                    data-edit-id="gojo-hero-title"
                    className="order-2 h-auto w-[170px] drop-shadow-md sm:order-1 sm:w-[clamp(220px,21vw,300px)]"
                  />
                  <RoundelBadge
                    eyebrow="seats"
                    value={
                      <span className="block text-[11px] font-headline leading-snug sm:text-[13px]">
                        カウンター6席
                        <br />
                        テーブル2席
                      </span>
                    }
                    className="order-1 w-28 self-end border-white/55 bg-black/35 text-white backdrop-blur-sm sm:order-2 sm:w-[152px] sm:self-auto"
                  />
                </div>
              </div>
            </div>

            {/* 店主の想い（見出しなし・小さい文字・ヒーロー動画の上） */}
            <div className="mx-auto w-full max-w-7xl px-6 pb-20 sm:px-10 sm:pb-28">
              <div
                className="max-w-xl space-y-3.5 text-[13px] leading-[1.95] text-white/75 sm:text-sm"
                style={{ fontFeatureSettings: '"palt" 1' }}
              >
                <p data-edit-id="gojo-about-p1">
                  米子の夜に、ふらりと立ち寄れる小さな隠れ家。人と人との&ldquo;ご縁&rdquo;がつながる場所でありたい——そんな想いではじめました。
                </p>
                <p data-edit-id="gojo-about-p2">
                  カウンター6席とテーブル2席だけの、小さなお店。店主との会話を肴に、気づけば何度も足を運びたくなる。そんな居心地のよさを大切にしています。
                </p>
                <p data-edit-id="gojo-about-p3">
                  派手さはなくても、素材とお酒、そして一杯の時間に正直に。肩肘張らずに、ゆっくりと過ごしてください。
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* 左レールをよけた本文エリア（不透明背景で固定映像を覆う） */}
        <div className="relative z-10 bg-background lg:pl-[200px]">
          {/* ============ FACTS 帯 ============ */}
          <div className="w-full bg-card/40">
            <div className="mx-auto grid max-w-7xl grid-cols-2 gap-y-2 sm:grid-cols-4">
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

          {/* ============ MENU（和紙の明セクション） ============ */}
          <section id="menu" className="relative w-full overflow-hidden py-24 sm:py-32">
            <img
              src="/yonago-gojo/texture-washi.jpg"
              alt=""
              aria-hidden
              className="absolute inset-0 h-full w-full object-cover"
            />
            <div className="absolute inset-0 bg-[#f4ecdd]/55" />
            <div className="relative mx-auto max-w-5xl px-6 sm:px-10">
              {/* 墨の筆ストローク（透過SVG）と見出し */}
              <div className="text-center">
                <BrushStroke className="mx-auto mb-4 h-9 w-44 text-[#3a2e20] sm:h-11 sm:w-56" />
                <SectionKicker className="text-[#9a6b28]">menu</SectionKicker>
                <SectionTitle
                  className="mt-2 text-[#241c14] sm:text-[clamp(2rem,3vw,3rem)]"
                  data-edit-id="gojo-menu-h2"
                >
                  お品書き
                </SectionTitle>
                <BodyCopy
                  className="mx-auto mt-4 max-w-xl text-center text-[#5c4f40]"
                  data-edit-id="gojo-menu-lead"
                >
                  その日の仕入れで内容は変わります。ここに載せきれない一品も、ぜひカウンターで。
                </BodyCopy>
                <RuleDivider className="mx-auto mt-9 max-w-[14rem] text-[#9a6b28]" />
              </div>

              {/* 名物（実際の料理写真） */}
              <div className="mt-12 grid grid-cols-2 gap-4 sm:gap-5 lg:grid-cols-3">
                {FOODS.map((f) => (
                  <FadeIn key={f.src}>
                    <figure className="group">
                      <div className="aspect-[4/3] overflow-hidden rounded-sm ring-1 ring-[#cdb892]/60">
                        <img
                          src={f.src}
                          alt={f.name}
                          className="h-full w-full object-cover transition-transform duration-700 group-hover:scale-105"
                        />
                      </div>
                      <figcaption className="mt-2.5">
                        <span className="font-headline text-[15px] text-[#241c14]">{f.name}</span>
                        <span className="mt-0.5 block text-[11px] text-[#7a6c58]">{f.note}</span>
                      </figcaption>
                    </figure>
                  </FadeIn>
                ))}
              </div>

              <div className="mt-16 grid grid-cols-1 gap-12 md:grid-cols-2 md:gap-16">
                {/* 定番 */}
                <div>
                  <h3
                    className="flex items-center gap-3 font-headline text-xl text-[#241c14]"
                    data-edit-id="gojo-menu-staple-h"
                  >
                    <SealMark className="text-[#9a6b28]">定</SealMark>
                    定番のおばんざい
                    <span className="font-en text-[11px] uppercase tracking-[0.2em] text-[#9a6b28]">
                      staple
                    </span>
                  </h3>
                  <ul className="mt-6 space-y-1">
                    {STAPLE_MENU.map((m) => (
                      <li key={m.name} className="flex items-baseline gap-2 py-2.5">
                        <span className="text-[15px] text-[#332a20]">{m.name}</span>
                        <span className="mx-1 flex-1 translate-y-[-3px] border-b border-dotted border-[#bda985]" />
                        <span className="font-en shrink-0 text-base text-[#9a6b28]">
                          ¥{m.price}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>

                {/* 季節 */}
                <div>
                  <h3
                    className="flex items-center gap-3 font-headline text-xl text-[#241c14]"
                    data-edit-id="gojo-menu-seasonal-h"
                  >
                    <SealMark className="text-[#9a6b28]">季</SealMark>
                    季節の一品
                    <span className="font-en text-[11px] uppercase tracking-[0.2em] text-[#9a6b28]">
                      seasonal
                    </span>
                  </h3>
                  <ul className="mt-6 space-y-5">
                    {SEASONAL_MENU.map((m) => (
                      <li key={m.name} className="border-b border-[#d8c9ac] pb-4">
                        <div className="text-[15px] text-[#332a20]">{m.name}</div>
                        <div className="mt-1 text-xs text-[#7a6c58]">{m.note}</div>
                      </li>
                    ))}
                  </ul>
                  <EditorialButton
                    href={INSTAGRAM_URL}
                    target="_blank"
                    rel="noopener noreferrer"
                    variant="ghost"
                    className="mt-6 -ml-7 border-transparent text-[#9a6b28] hover:text-[#7a5320]"
                  >
                    <span className="inline-flex items-center gap-2">
                      <Instagram className="h-4 w-4" />
                      本日の一品はInstagramで
                    </span>
                  </EditorialButton>
                </div>
              </div>
              <p className="mt-12 text-center text-xs text-[#7a6c58]">
                ※ 価格は税込です。仕入れにより内容・価格が変わる場合があります。
              </p>
            </div>
          </section>

          {/* ============ CRAFT + 調理動画（映像を固定し、最後の章まで残す） ============ */}
          <section id="craft" className="mx-auto max-w-7xl px-6 py-24 sm:px-10 sm:py-32">
            <SectionKicker className="text-primary">craft</SectionKicker>
            <SectionTitle
              className="mt-3 sm:text-[clamp(2rem,3.2vw,3.25rem)]"
              data-edit-id="gojo-craft-h2"
            >
              一品一品に、手をかけて。
            </SectionTitle>
            <BodyCopy className="mt-4 max-w-md">
              仕込みの風景そのものが、五条の味わい。その手元を、少しだけお見せします。
            </BodyCopy>

            <CraftStory
              progressLabel="gojo craft"
              className="mt-14"
              mediaFrameClassName="shadow-2xl shadow-black/40"
              eyebrowClassName="text-primary"
              chapters={CRAFT.map((c) => ({
                eyebrow: `${c.no} / ${c.eyebrow}`,
                title: c.title,
                body: c.body,
                media: <CraftMedia media={c.media} />,
              }))}
            />
          </section>

          {/* ============ GALLERY（非対称モザイク） ============ */}
          <section id="gallery" className="w-full bg-card/30 py-24 sm:py-32">
            <div className="mx-auto max-w-7xl px-6 sm:px-10">
              <div className="mb-10 flex items-end justify-between">
                <div>
                  <SectionKicker className="text-primary">gallery</SectionKicker>
                  <SectionTitle
                    className="mt-3 sm:text-[clamp(2rem,3vw,3rem)]"
                    data-edit-id="gojo-gallery-h2"
                  >
                    店内・調理の風景
                  </SectionTitle>
                </div>
                <span
                  className="hidden font-headline text-sm tracking-[0.3em] text-muted-foreground sm:block"
                  style={{ writingMode: "vertical-rl" }}
                >
                  灯りの灯る、夜の板場
                </span>
              </div>
              <div className="grid auto-rows-[150px] grid-cols-2 gap-3 sm:auto-rows-[200px] sm:grid-cols-4 sm:gap-4">
                {GALLERY.map((g) => (
                  <FadeIn key={g.src} className={g.span}>
                    <div className="group h-full w-full overflow-hidden rounded-sm">
                      <img
                        src={g.src}
                        alt={g.alt}
                        className="h-full w-full object-cover transition-transform duration-700 group-hover:scale-105"
                      />
                    </div>
                  </FadeIn>
                ))}
              </div>
            </div>
          </section>

          {/* ============ はじめての方へ / FAQ ============ */}
          <section id="first" className="w-full bg-card/30 py-24 sm:py-32">
            <div className="mx-auto max-w-5xl px-6 sm:px-10">
              <SectionKicker className="text-primary">first visit</SectionKicker>
              <SectionTitle
                className="mt-3 sm:text-[clamp(2rem,3vw,3rem)]"
                data-edit-id="gojo-first-h2"
              >
                はじめての方へ
              </SectionTitle>
              <BodyCopy className="mt-4 max-w-xl">
                小さな隠れ家なので、来店前に知っておくと安心なことをまとめました。
              </BodyCopy>

              <dl className="mt-12 grid grid-cols-1 gap-x-12 gap-y-9 md:grid-cols-2">
                {FIRST_TIME.map((item, i) => (
                  <FadeIn key={item.q} delay={i * 0.05}>
                    <div className="border-t border-border/40 pt-5">
                      <dt className="flex items-start gap-3 font-headline text-lg text-foreground">
                        <span className="font-en text-sm text-primary">Q.</span>
                        {item.q}
                      </dt>
                      <dd className="mt-2.5 pl-7 text-[14px] leading-relaxed text-muted-foreground">
                        {item.a}
                      </dd>
                    </div>
                  </FadeIn>
                ))}
              </dl>
            </div>
          </section>

          {/* ============ ACCESS ============ */}
          <section id="access" className="mx-auto max-w-7xl px-6 py-24 sm:px-10 sm:py-32">
            <div className="grid grid-cols-1 gap-12 lg:grid-cols-2 lg:gap-16">
              <div>
                <SectionKicker className="text-primary">access</SectionKicker>
                <SectionTitle
                  className="mt-3 sm:text-[clamp(2rem,3vw,3rem)]"
                  data-edit-id="gojo-access-h2"
                >
                  お越しの際は
                </SectionTitle>
                <dl className="mt-9 space-y-6">
                  {[
                    { icon: MapPin, label: "住所", value: ADDRESS },
                    { icon: Clock, label: "営業時間", value: "18:00 – 23:00" },
                    { icon: CalendarOff, label: "定休日", value: "火曜・水曜" },
                    { icon: CreditCard, label: "お支払い", value: "現金・各種カード・PayPay" },
                    { icon: Car, label: "駐車場", value: "専用駐車場なし（近隣に有料駐車場あり）" },
                  ].map((row) => (
                    <div key={row.label} className="flex gap-4 pb-1">
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

          {/* ============ CTA（琥珀の灯りの上に・視差で奥行き） ============ */}
          <section className="relative isolate w-full overflow-hidden">
            <ParallaxMedia
              src="/yonago-gojo/night-amber.jpg"
              intensity="subtle"
              className="absolute inset-x-0 -inset-y-[12%] -z-20"
              mediaClassName="h-full w-full object-cover"
            />
            <div className="absolute inset-0 -z-10 bg-gradient-to-r from-[var(--gojo-sumi)]/95 via-[var(--gojo-sumi)]/80 to-[var(--gojo-sumi)]/40" />
            <div className="mx-auto max-w-7xl px-6 py-28 sm:px-10 sm:py-36">
              <FadeIn>
                <div className="max-w-xl">
                  <SectionKicker className="text-primary">tonight at gojo</SectionKicker>
                  <SectionTitle
                    className="mt-4 text-white sm:text-[clamp(2.5rem,4.5vw,4rem)]"
                    data-edit-id="gojo-cta-h2"
                  >
                    今夜、五条で。
                  </SectionTitle>
                  <p className="mt-5 text-base leading-relaxed text-white/80" style={{ fontFeatureSettings: '"palt" 1' }}>
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
          <footer className="w-full bg-background">
            <div className="mx-auto max-w-7xl px-6 py-12 sm:px-10">
              <div className="flex flex-col gap-8 sm:flex-row sm:items-end sm:justify-between">
                <div className="flex items-center gap-4">
                  <span className="relative block h-14 w-14">
                    <img
                      src="/yonago-gojo/logo-text.png"
                      alt="OBANZAI bar 五条 ロゴ"
                      className="h-full w-full object-contain"
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
              <div className="mt-8 pt-2 font-en text-xs tracking-wider text-muted-foreground">
                © {new Date().getFullYear()} OBANZAI bar 五条 · 米子 · 富士見町
              </div>
            </div>
          </footer>
        </div>
      </main>
    </>
  );
}
