"use client";

import * as React from "react";
import { motion, useReducedMotion } from "framer-motion";
import { VolumeX, Wind, Droplet, ShieldCheck, Zap } from "lucide-react";

import { Section, FaqSection } from "@/components/templates";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { WaitlistForm } from "./components/waitlist-form";
import { ThermalColumn } from "./components/thermal-column";
import { PowerCompare } from "./components/power-compare";

/* ------------------------------------------------------------------ */

function Reveal({
  children,
  delay = 0,
  className,
}: {
  children: React.ReactNode;
  delay?: number;
  className?: string;
}) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      initial={reduce ? false : { opacity: 0, y: 18 }}
      whileInView={reduce ? undefined : { opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-70px" }}
      transition={{ duration: 0.55, delay, ease: "easeOut" }}
      className={className}
    >
      {children}
    </motion.div>
  );
}

function ScrollCta({
  label,
  editId,
  variant = "default",
}: {
  label: string;
  editId: string;
  variant?: "default" | "outline";
}) {
  return (
    <Button
      size="lg"
      variant={variant}
      data-edit-id={editId}
      onClick={() =>
        document
          .getElementById("waitlist")
          ?.scrollIntoView({ behavior: "smooth", block: "center" })
      }
      className="h-12 px-8 text-base font-bold"
    >
      {label}
    </Button>
  );
}

/* ------------------------------------------------------------------ */

const ZEROS = [
  {
    icon: VolumeX,
    unit: "dB",
    label: "音",
    body: "ファンもポンプも入っていません。動く部品がないので、そもそも音の出るところがありません。通話中でもマイクに乗りません。",
  },
  {
    icon: Wind,
    unit: "m/s",
    label: "風",
    body: "熱を風で送りません。書類が飛ばず、埃も舞いません。顔に当たってだるくなることもありません。",
  },
  {
    icon: Droplet,
    unit: "%",
    label: "乾燥",
    body: "空気を動かさないので、部屋の湿度が下がりません。夕方に喉が痛くなる、目が乾く、が起きません。",
  },
];

const PLACEMENTS = [
  {
    title: "デスクの脚に、貼る",
    body: "側面のマグネットで、スチール脚のデスクにそのまま付きます。床に何も置かないので、掃除のときに動かす必要がありません。",
  },
  {
    title: "スタンドで、立てる",
    body: "背面のスタンドを起こすと、木や樹脂の脚のデスクでも自立します。角度は2段階。すねに向けるか、足の甲に向けるかを選べます。",
  },
  {
    title: "床に、寝かせる",
    body: "平らに置くと足置きの高さになります。足の裏から直接あたためたい日はこの向きで。上に足を乗せても構いません。",
  },
];

const SPECS = [
  { label: "消費電力", value: "150", unit: "W", note: "強150W / 中100W / 弱60W" },
  { label: "表面温度", value: "45", unit: "℃", note: "強で運転したときの上限（設計目標）" },
  { label: "サイズ", value: "65×45", unit: "cm", note: "厚さ2.5cm" },
  { label: "重さ", value: "1.8", unit: "kg", note: "スタンド・マグネットを含む目標値" },
  { label: "立ち上がり", value: "90", unit: "秒", note: "表面温度に達するまで" },
  { label: "電源", value: "AC100", unit: "V", note: "家庭用コンセント。ケーブル長2.5m" },
];

const FAQ_ITEMS = [
  {
    question: "本当に足が暖まりますか？",
    answer: (
      <div className="space-y-2">
        <p>
          パネルの正面30〜40cmの範囲、つまりデスクの下にいる足とすねが暖まります。遠赤外線は空気ではなく物に直接あたるので、部屋が寒くても、あたっている面はすぐに暖かくなります。
        </p>
        <p>
          逆に言うと、あたっていない背中や肩は暖まりません。足元の寒さを解決する道具だとお考えください。
        </p>
      </div>
    ),
  },
  {
    question: "これがあれば、エアコンはいらなくなりますか？",
    answer:
      "いいえ。150Wでは部屋の空気は暖まりません。エアコンやほかの暖房と一緒に使うものです。ただ、足元が寒くなくなると同じ室温でも寒く感じにくくなるため、エアコンの設定温度を1〜2℃下げても平気になる方が多いはずです。そこは実際に試していただくしかありません。",
  },
  {
    question: "低温やけどが心配です。",
    answer:
      "表面温度が45℃を超えない設計にします。市販の電気ストーブは表面が数百℃になりますが、この製品は触れても瞬間的にやけどする温度ではありません。ただし、素肌を長時間あて続けると低温やけどの原因になります。靴下やズボン越しにお使いください。眠ってしまっても大丈夫なように、3時間で自動的に切れる仕組みを入れます。",
  },
  {
    question: "倒れたときはどうなりますか？",
    answer:
      "内部の傾きセンサーが働き、電源が切れます。掃除機をかけていて当たった、椅子で押してしまった、といったときに、そのまま点いたままになりません。パネルの上に物が落ちて覆われたときも、温度が上がりすぎる前に出力を絞ります。",
  },
  {
    question: "電気代はどのくらいですか？",
    answer:
      "強（150W）で1時間およそ4.7円です。1日8時間・平日20日でおよそ740円になります。1kWhあたり31円で計算した目安です。エアコンに加えてかかる金額なので、電気代そのものは増えます。",
  },
  {
    question: "デスクの脚が木製です。マグネットは使えません。",
    answer:
      "背面のスタンドを起こして立ててお使いください。マグネットは「床に何も置きたくない方」向けの選択肢のひとつで、必須ではありません。立てる・寝かせるの2通りだけでも問題なくお使いいただけます。",
  },
  {
    question: "小さな子どもやペットがいても大丈夫ですか？",
    answer:
      "表面が45℃までなので、触れてすぐにやけどをする温度ではありません。ただし長く触れ続けるのは危険ですし、倒される可能性もあります。目の届かないところでの使用は避けてください。転倒時に電源が切れる仕組みは入れますが、それだけで安全になるとは考えていません。",
  },
  {
    question: "いつ買えますか？いくらですか？",
    answer:
      "現在は開発中で、発売日は決まっていません。価格は9,800円を目指していますが、部材の見積もり次第で変わります。先行登録いただいた方には、決まり次第いちばんにご連絡します。",
  },
];

/* ------------------------------------------------------------------ */

export default function AshimotoHeaterPage() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* ------------------------------- nav */}
      <header className="sticky top-0 z-40 w-full border-b border-border/60 bg-background/85 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3.5 sm:px-6">
          <span
            className="font-headline text-base tracking-wide text-foreground sm:text-lg"
            data-edit-id="ashimoto-nav-brand"
          >
            足元パネルヒーター
          </span>
          <Button
            size="sm"
            onClick={() =>
              document
                .getElementById("waitlist")
                ?.scrollIntoView({ behavior: "smooth", block: "center" })
            }
            className="font-bold"
            data-edit-id="ashimoto-nav-cta"
          >
            発売のお知らせを受け取る
          </Button>
        </div>
      </header>

      {/* ------------------------------- hero（センター寄せのコピー → 全幅の写真帯） */}
      <section className="relative">
        <div className="mx-auto max-w-3xl px-4 pb-14 pt-16 text-center sm:px-6 sm:pb-16 sm:pt-24">
          <Badge
            variant="outline"
            className="mb-8 rounded-none border-primary/50 bg-transparent px-2.5 py-1 text-[11px] font-normal tracking-wider text-primary"
            data-edit-id="ashimoto-top-hero-badge"
          >
            開発中 — 先行登録受付
          </Badge>
          <h1
            className="text-[2rem] leading-[1.35] tracking-tight text-foreground sm:text-[2.9rem] lg:text-[3.2rem]"
            data-edit-id="ashimoto-top-hero-h1"
          >
            足元だけ、暖める。
          </h1>
          <p
            className="mx-auto mt-8 max-w-xl text-[15px] leading-[2.1] text-muted-foreground sm:text-base"
            data-edit-id="ashimoto-top-hero-lead"
          >
            デスクの下に置く、遠赤外線のパネルです。
            消費電力は150W。音も風もなく、部屋の空気を乾かしません。
          </p>
          <div className="mt-10 flex flex-col items-center gap-4">
            <ScrollCta
              label="発売のお知らせを受け取る"
              editId="ashimoto-top-hero-cta"
            />
            <span
              className="text-xs leading-relaxed text-muted-foreground"
              data-edit-id="ashimoto-top-hero-cta-note"
            >
              登録は無料。お支払いはありません。
            </span>
          </div>
        </div>

        {/* 全幅の写真帯（文字を重ねないので暗転させない） */}
        <img
          src="/scratch/ashimoto-heater/hero.jpg"
          alt="木のデスクの下に立てられた、白い薄型のパネルヒーター。すぐそばで厚手の靴下をはいた足がくつろいでいる。"
          data-edit-id="ashimoto-top-hero-image"
          className="h-[46vh] w-full object-cover sm:h-[58vh] lg:h-[68vh]"
        />
      </section>

      {/* ------------------------------- 課題：垂直の温度スケール */}
      <Section width="lg" padding="lg">
        <div className="grid items-center gap-12 lg:grid-cols-[minmax(0,1fr)_minmax(0,0.95fr)] lg:gap-20">
          <Reveal>
            <ThermalColumn />
          </Reveal>
          <Reveal delay={0.1}>
            <p
              className="font-eyebrow text-[11px] text-primary"
              data-edit-id="ashimoto-top-pain-eyebrow"
            >
              why we made it
            </p>
            <h2
              className="mt-4 text-3xl leading-snug tracking-tight sm:text-4xl"
              data-edit-id="ashimoto-top-pain-h2"
            >
              暖房は効いている。
              <br />
              足以外は。
            </h2>
            <p
              className="mt-6 max-w-lg text-sm leading-[2.1] text-muted-foreground sm:text-base"
              data-edit-id="ashimoto-top-pain-body"
            >
              暖かい空気は天井へ上がります。だから頭のあたりは設定温度どおりになるのに、
              床から10cmの高さだけが5〜8℃低いまま取り残されます。
            </p>
            <p
              className="mt-5 max-w-lg text-sm leading-[2.1] text-muted-foreground sm:text-base"
              data-edit-id="ashimoto-top-pain-body2"
            >
              エアコンを強くしても、上が暑くなるだけで足元は変わりません。
              頭がのぼせて、足の指先だけが冷たい。一日中この状態で仕事をしています。
            </p>
            <p
              className="mt-5 max-w-lg text-sm leading-[2.1] text-muted-foreground sm:text-base"
              data-edit-id="ashimoto-top-pain-body3"
            >
              足元だけを、足元のために暖める。それがこの製品のすべてです。
            </p>
          </Reveal>
        </div>
      </Section>

      {/* ------------------------------- 3つのゼロ */}
      <div className="border-y border-border bg-muted/60">
        <Section width="lg" padding="lg">
          <Reveal>
            <p
              className="font-eyebrow text-[11px] text-primary"
              data-edit-id="ashimoto-top-zero-eyebrow"
            >
              three zeros
            </p>
            <h2
              className="mt-4 max-w-2xl text-3xl leading-snug tracking-tight sm:text-4xl"
              data-edit-id="ashimoto-top-zero-h2"
            >
              仕事の邪魔を、しません。
            </h2>
            <p
              className="mt-5 max-w-xl text-sm leading-loose text-muted-foreground sm:text-base"
              data-edit-id="ashimoto-top-zero-lead"
            >
              足元の暖房を選ぶとき、本当に困るのは暖かさではなく副作用のほうでした。
              熱を風で運ばない構造にすると、そのすべてが消えます。
            </p>
          </Reveal>

          <div className="mt-14 border-t border-border">
            {ZEROS.map((z, i) => {
              const Icon = z.icon;
              return (
                <Reveal key={z.label} delay={i * 0.06}>
                  <div className="grid grid-cols-1 items-baseline gap-x-8 gap-y-3 border-b border-border py-8 sm:grid-cols-[5.5rem_minmax(0,9rem)_minmax(0,1fr)] sm:py-9">
                    <div className="font-num text-[3.6rem] leading-[0.8] text-primary sm:text-[4.5rem]">
                      0
                      <span className="ml-1 align-top text-base text-muted-foreground">
                        {z.unit}
                      </span>
                    </div>
                    <h3
                      className="flex items-center gap-3 text-xl text-foreground sm:text-2xl"
                      data-edit-id={`ashimoto-top-zero-${i}-title`}
                    >
                      <Icon className="h-[1.05rem] w-[1.05rem] shrink-0 text-primary" />
                      {z.label}
                    </h3>
                    <p
                      className="text-sm leading-[2] text-muted-foreground"
                      data-edit-id={`ashimoto-top-zero-${i}-body`}
                    >
                      {z.body}
                    </p>
                  </div>
                </Reveal>
              );
            })}
          </div>
        </Section>
      </div>

      {/* ------------------------------- 置き方3通り */}
      <Section width="lg" padding="lg">
        <div className="grid gap-12 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)] lg:gap-16">
          <Reveal className="lg:sticky lg:top-28 lg:self-start">
            <figure>
              <img
                src="/scratch/ashimoto-heater/product.jpg"
                alt="白い薄型パネルヒーターの製品写真。背面のスタンドを起こして自立させた状態で、側面にマグネット、右下に小さなダイヤルがある。"
                data-edit-id="ashimoto-top-place-image"
                className="w-full border border-border object-cover"
              />
              <figcaption className="mt-3 text-xs text-muted-foreground">
                ※ 写真はデザイン案のイメージです。実際の製品とは異なります。
              </figcaption>
            </figure>
          </Reveal>
          <Reveal delay={0.08}>
            <p
              className="font-eyebrow text-[11px] text-primary"
              data-edit-id="ashimoto-top-place-eyebrow"
            >
              three ways
            </p>
            <h2
              className="mt-4 text-3xl leading-snug tracking-tight sm:text-4xl"
              data-edit-id="ashimoto-top-place-h2"
            >
              置き方は、3通り。
            </h2>
            <p
              className="mt-5 text-sm leading-loose text-muted-foreground sm:text-base"
              data-edit-id="ashimoto-top-place-lead"
            >
              デスクの形は人それぞれです。どんな机でも足元に置けるように、
              固定のしかたを3つ用意しました。
            </p>

            <div className="mt-10 border-t border-border">
              {PLACEMENTS.map((p, i) => (
                <div
                  key={p.title}
                  className="grid grid-cols-[2.5rem_minmax(0,1fr)] gap-x-5 gap-y-2 border-b border-border py-6"
                >
                  <span className="font-num text-xl leading-none text-primary/70">
                    0{i + 1}
                  </span>
                  <div>
                    <h3
                      className="text-lg text-foreground"
                      data-edit-id={`ashimoto-top-place-${i}-title`}
                    >
                      {p.title}
                    </h3>
                    <p
                      className="mt-2.5 text-sm leading-[2] text-muted-foreground"
                      data-edit-id={`ashimoto-top-place-${i}-body`}
                    >
                      {p.body}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </Reveal>
        </div>
      </Section>

      {/* ------------------------------- 電気代 */}
      <div className="border-y border-border bg-card">
        <Section width="lg" padding="lg">
          <div className="grid gap-12 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.5fr)] lg:gap-16">
            <Reveal className="lg:sticky lg:top-28 lg:self-start">
              <Zap className="mb-6 h-[1.05rem] w-[1.05rem] text-primary" />
              <h2
                className="text-3xl leading-snug tracking-tight sm:text-4xl"
                data-edit-id="ashimoto-top-power-h2"
              >
                1時間、
                <br />
                4.7円です。
              </h2>
              <p
                className="mt-6 text-sm leading-[2.1] text-muted-foreground sm:text-base"
                data-edit-id="ashimoto-top-power-body"
              >
                150Wは、10畳用エアコンの暖房時の定格消費電力のおよそ7分の1です。
                足元だけを暖めるので、これだけの電力で足ります。
              </p>
              <p
                className="mt-5 text-sm leading-[2.1] text-muted-foreground sm:text-base"
                data-edit-id="ashimoto-top-power-body2"
              >
                1日8時間、平日20日で、ひと月およそ740円。
                つけっぱなしにしても気にならない金額に収めることを、設計の条件にしました。
              </p>
            </Reveal>
            <Reveal delay={0.1}>
              <PowerCompare />
            </Reveal>
          </div>
        </Section>
      </div>

      {/* ------------------------------- 安全（ページ唯一の暗い全幅帯） */}
      <div className="ink-band w-full">
        <Section width="lg" padding="lg">
          <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)] lg:gap-20">
            <Reveal>
              <ShieldCheck className="mb-7 h-[1.15rem] w-[1.15rem] text-primary" />
              <h2
                className="ink-heading text-[2.1rem] leading-[1.3] tracking-tight sm:text-4xl lg:text-[2.9rem]"
                data-edit-id="ashimoto-top-safety-h2"
              >
                倒れたら、
                <br />
                消えます。
              </h2>
            </Reveal>
            <Reveal delay={0.1} className="lg:pt-3">
              <p
                className="ink-body text-sm leading-[2.1] sm:text-base"
                data-edit-id="ashimoto-top-safety-body"
              >
                傾きを感じると、電源が切れます。掃除機が当たった、椅子で押した。
                そういう日常の事故で、点いたままにならない仕組みです。
                切り忘れても3時間で自動的に止まります。
              </p>
              <p
                className="ink-note mt-6 border-t pt-6 text-sm leading-[2.1]"
                data-edit-id="ashimoto-top-safety-body2"
              >
                表面温度は45℃まで。電気ストーブのように赤熱しないので、
                触れた瞬間にやけどをすることはありません。
                ただし素肌を長時間あて続けると低温やけどの原因になります。靴下やズボン越しにお使いください。
              </p>
            </Reveal>
          </div>
        </Section>
      </div>

      {/* ------------------------------- 正直な話 */}
      <Section width="lg" padding="lg">
        <Reveal>
          <p
            className="font-eyebrow text-[11px] text-primary"
            data-edit-id="ashimoto-top-honest-eyebrow"
          >
            honest note
          </p>
          <h2
            className="mt-4 max-w-2xl text-3xl leading-snug tracking-tight sm:text-4xl"
            data-edit-id="ashimoto-top-honest-h2"
          >
            先に書いておきます。
            <br />
            部屋は、暖まりません。
          </h2>
        </Reveal>
        <Reveal delay={0.1}>
          <div className="mt-10 max-w-3xl border-l-2 border-primary/50 pl-6 sm:pl-8">
            <p
              className="text-[15px] leading-[2.1] text-foreground sm:text-base"
              data-edit-id="ashimoto-top-honest-body"
            >
              150Wで部屋の空気を暖めることはできません。これはエアコンの代わりではなく、
              エアコンでは届かない足元だけを引き受ける道具です。電気代も、エアコンに上乗せでかかります。
            </p>
            <p
              className="mt-5 text-sm leading-[2.1] text-muted-foreground"
              data-edit-id="ashimoto-top-honest-body2"
            >
              そのかわり、足が寒くなくなると、同じ室温でも寒く感じにくくなります。
              エアコンの設定温度を1〜2℃下げても平気になる方は多いはずです。
              ただしそれは体感の話で、必ずそうなるとは言えません。ここは正直にお伝えしておきます。
            </p>
          </div>
        </Reveal>
      </Section>

      {/* ------------------------------- 仕様 */}
      <div className="border-y border-border bg-muted/60">
        <Section width="lg" padding="md">
          <Reveal>
            <h2
              className="text-2xl leading-snug tracking-tight sm:text-3xl"
              data-edit-id="ashimoto-top-spec-h2"
            >
              仕様（開発中の目標値）
            </h2>
          </Reveal>
          <div className="mt-10 grid gap-x-12 sm:grid-cols-2">
            {SPECS.map((s, i) => (
              <Reveal key={s.label} delay={i * 0.04}>
                <div className="flex items-baseline justify-between gap-6 border-b border-border py-5">
                  <div>
                    <dt
                      className="text-sm text-foreground"
                      data-edit-id={`ashimoto-top-spec-${i}-label`}
                    >
                      {s.label}
                    </dt>
                    <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                      {s.note}
                    </p>
                  </div>
                  <div className="shrink-0 font-num text-3xl leading-none text-foreground">
                    {s.value}
                    <span className="ml-1 align-top text-sm text-primary">
                      {s.unit}
                    </span>
                  </div>
                </div>
              </Reveal>
            ))}
          </div>
        </Section>
      </div>

      {/* ------------------------------- 登録 */}
      <div id="waitlist" className="warm-floor border-t border-border">
        <Section width="md" padding="lg">
          <Reveal className="text-center">
            <h2
              className="text-3xl leading-snug tracking-tight sm:text-4xl"
              data-edit-id="ashimoto-top-waitlist-h2"
            >
              まだ、開発中です。
            </h2>
            <p
              className="mx-auto mt-6 max-w-lg text-sm leading-loose text-muted-foreground sm:text-base"
              data-edit-id="ashimoto-top-waitlist-lead"
            >
              価格は9,800円を目指しています。
              先行登録いただいた方には、発売の見通しが立ち次第、いちばんにご連絡します。
            </p>
          </Reveal>
          <Reveal delay={0.1} className="mt-10">
            <WaitlistForm />
          </Reveal>
        </Section>
      </div>

      {/* ------------------------------- FAQ */}
      <Section
        width="md"
        padding="lg"
        eyebrow="よくある質問"
        heading="気になるところに、先に答えます。"
      >
        <FaqSection items={FAQ_ITEMS} />
        <div className="mt-10 text-center">
          <ScrollCta
            label="発売のお知らせを受け取る"
            editId="ashimoto-top-faq-cta"
          />
        </div>
      </Section>

      {/* ------------------------------- footer */}
      <footer className="border-t border-border bg-muted/70">
        <div className="mx-auto max-w-6xl space-y-4 px-4 py-12 sm:px-6">
          <p className="font-headline text-base text-foreground">
            足元パネルヒーター
          </p>
          <p className="max-w-3xl text-xs leading-loose text-muted-foreground">
            このページは開発中の製品について、ほしい方がどれくらいいらっしゃるかを調べるために公開しています。
            発売日・価格・仕様はいずれも未確定で、記載の数値は設計上の目標値および計算値です。
            掲載している写真はデザイン案のイメージで、実際の製品とは異なります。
            暖かさの感じ方は、机の形・座り方・部屋の断熱・外気温によって変わります。
            電気代は1kWhあたり31円で計算した目安です。他の暖房器具との比較は、いずれもカタログ上の定格消費電力どうしの比較です。
            製品化にあたっては電気用品安全法の基準に適合させたうえで販売します。
            現時点でご登録いただいても、お支払いの義務は一切発生しません。
          </p>
          <p className="text-xs text-muted-foreground">
            © 2026 足元パネルヒーター プロジェクト
          </p>
        </div>
      </footer>
    </div>
  );
}
