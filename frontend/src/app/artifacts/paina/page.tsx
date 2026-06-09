"use client";

import * as React from "react";
import { Reveal } from "./components/reveal";
import { useLang } from "./components/lang-context";

const CONTENT = {
  ja: {
    title: "AIエージェント、ダン",
    paragraphs: [
      "人とともに働くAIをつくっています。",
      "AIは急速に賢くなりました。けれど「賢いこと」と「役に立つこと」のあいだには、まだ大きな隔たりがあります。多くのAIは、答えを返すところで止まります。本当に必要なのは、答えではなく、終わっている状態です。",
      "調べ、判断し、実際に手を動かし、結果を確かめて、必要なら自分で直す。その最後の一歩までを引き受けてはじめて、AIは仕事の相棒になります。このAIを「ダン（Done）」と名づけました。「やっておいて」と頼んだことが、本当に終わっている。その当たり前を、誰にとっても当たり前にしたい。",
      "ダンに、人の代わりは求めていません。目指すのは、人の隣で働く相棒です。判断は人が握り、面倒な実務はダンが引き受ける。その境界を丁寧に設計することが、信頼できるAIの出発点だと考えています。",
      "自律と暴走は紙一重です。だからこそ、力を増やすことと同じだけ、人が安心して任せられる仕組みづくりに時間をかけます。派手な機能より、壊れない土台。地味でも正しい順序で積み上げることが、長く使えるAIをつくる唯一の道だと信じています。",
      "そして、自分の仕事をダン自身に任せながら、毎日ダンを鍛えています。実際の現場で使い、つまずき、直す。現実から逆算することでしか、本当に役立つAIは生まれません。",
      "ひとつずつ、確かに。長く隣にいられるAIを目指します。",
    ],
    signature: "株式会社パイナ",
  },
  en: {
    title: "Done, an AI agent",
    paragraphs: [
      "Building AI that works alongside people.",
      "AI has grown remarkably capable. Yet between being smart and being useful, a wide gap still remains. Most AI stops at returning an answer. What's actually needed isn't an answer — it's the state of being finished.",
      "Looking things up, deciding, doing the actual work, checking the result, and fixing it when needed. Only when AI carries that final step does it become a real partner in your work. This AI is named “Done.” What you asked to be taken care of is genuinely finished. That ordinary thing — making it ordinary for everyone.",
      "Done is not meant to replace people. The aim is a partner that works beside you. People hold the judgment; Done takes on the tedious work. Designing that boundary with care is where trustworthy AI begins.",
      "Autonomy and recklessness are a hair apart. So just as much care goes into raising its capability as into building the safeguards that let people delegate with confidence. A solid foundation over flashy features. Building in the right order — however unglamorous — is the only path to AI that lasts.",
      "And Done is sharpened every day by being trusted with real work. Used in the field, it stumbles, and it gets fixed. Only by working backward from reality can AI become genuinely useful.",
      "One at a time, with certainty. Aiming for an AI that can stay beside you for the long run.",
    ],
    signature: "PAINA Inc.",
  },
};

export default function PainaHome() {
  const { lang } = useLang();
  const c = CONTENT[lang];

  return (
    <section className="px-6 pb-32 pt-40 md:pt-52">
      <Reveal>
        <div className="mx-auto max-w-[640px] text-center">
          <h1
            className="font-serif-jp whitespace-nowrap text-[1.55rem] leading-[1.5] tracking-[0.01em] text-[var(--paina-fg)] sm:whitespace-normal sm:text-[2.6rem]"
            data-edit-id="home-title"
          >
            {c.title}
          </h1>

          <div
            className="font-serif-jp mt-14 space-y-8 text-[16.5px] leading-[2.15] text-[var(--paina-fg)] md:text-[17.5px]"
            data-edit-id="home-letter"
          >
            {c.paragraphs.map((p, i) => (
              <p key={i}>{p}</p>
            ))}
          </div>

          <p className="font-en mt-16 text-[15px] italic tracking-wide text-[var(--paina-muted)]">
            {c.signature}
          </p>
        </div>
      </Reveal>
    </section>
  );
}
