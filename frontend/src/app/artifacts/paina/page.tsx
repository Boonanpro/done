"use client";

import * as React from "react";
import { Reveal } from "./components/reveal";

export default function PainaHome() {
  return (
    <section className="px-6 pb-32 pt-40 md:pt-52">
      <Reveal>
        <div className="mx-auto max-w-[640px] text-center">
          <h1
            className="font-serif-jp text-[2.1rem] leading-[1.5] tracking-[0.01em] text-[var(--paina-fg)] sm:text-[2.6rem]"
            data-edit-id="home-title"
          >
            AIエージェント、ダン
          </h1>

          <div
            className="font-serif-jp mt-14 space-y-8 text-[16.5px] leading-[2.15] text-[var(--paina-fg)] md:text-[17.5px]"
            data-edit-id="home-letter"
          >
            <p>私たちは、人とともに働くAIをつくっています。</p>

            <p>
              AIは急速に賢くなりました。けれど「賢いこと」と「役に立つこと」のあいだには、まだ大きな隔たりがあります。
              多くのAIは、答えを返すところで止まります。私たちが本当に欲しいのは、答えではなく、終わっている状態です。
            </p>

            <p>
              調べ、判断し、実際に手を動かし、結果を確かめて、必要なら自分で直す。
              その最後の一歩までを引き受けてはじめて、AIは仕事の相棒になります。
              私たちはこのAIを「ダン（Done）」と名づけました。
              「やっておいて」と頼んだことが、本当に終わっている。その当たり前を、誰にとっても当たり前にしたい。
            </p>

            <p>
              私たちは、ダンに代わりを求めていません。人の隣で働く相棒を育てています。
              判断は人が握り、面倒な実務はダンが引き受ける。
              その境界を丁寧に設計することが、信頼できるAIの出発点だと考えています。
            </p>

            <p>
              自律と暴走は紙一重です。だからこそ私たちは、力を増やすことと同じだけ、
              人が安心して任せられる仕組みをつくることに時間をかけます。
              派手な機能より、壊れない土台。地味でも正しい順序で積み上げることが、
              長く使えるAIをつくる唯一の道だと信じています。
            </p>

            <p>
              そして私たちは、自分たちの仕事をダン自身に任せながら、毎日ダンを鍛えています。
              実際の現場で使い、つまずき、直す。
              現実から逆算することでしか、本当に役立つAIは生まれません。
            </p>

            <p>ひとつずつ、確かに。私たちは、長く隣にいられるAIを目指します。</p>
          </div>

          <p className="font-en mt-16 text-[15px] italic tracking-wide text-[var(--paina-muted)]">
            株式会社パイナ
          </p>
        </div>
      </Reveal>
    </section>
  );
}
