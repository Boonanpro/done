'use client';

import { motion, useScroll } from 'framer-motion';
import { useRef } from 'react';

import {
  FadeIn,
  ImageReveal,
  ParallaxMedia,
  PinnedStory,
  SectionThemeShift,
  Stagger,
  StaggerItem,
  StickyStory,
  TextReveal,
  useScrollRange,
} from '@/components/motion';

const imageA = '/yonago-gojo/g1.jpg';
const imageB = '/yonago-gojo/g3.jpg';
const imageC = '/yonago-gojo/g4.jpg';
const videoA = '/yonago-gojo/dish.mp4';
const posterA = '/yonago-gojo/dish-poster.jpg';

type Status = 'usable' | 'review' | 'risky';

const statusText: Record<Status, string> = {
  usable: '採用可',
  review: '要確認',
  risky: '危険',
};

function DemoBlock({
  id,
  title,
  status,
  notes,
  children,
}: {
  id: string;
  title: string;
  status: Status;
  notes: string;
  children: React.ReactNode;
}) {
  const statusClass = {
    usable: 'border-emerald-400/30 bg-emerald-400/10 text-emerald-200',
    review: 'border-amber-400/30 bg-amber-400/10 text-amber-200',
    risky: 'border-red-400/30 bg-red-400/10 text-red-200',
  }[status];

  return (
    <section id={id} className="border-t border-white/10 px-6 py-24 sm:px-10">
      <div className="mx-auto max-w-6xl">
        <div className="mb-10 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <div className="mb-3 font-mono text-xs uppercase tracking-[0.18em] text-white/45">
              components/motion
            </div>
            <h2 className="text-3xl font-medium tracking-normal text-white sm:text-5xl">
              {title}
            </h2>
          </div>
          <div className={`w-fit border px-3 py-1.5 text-xs tracking-[0.14em] ${statusClass}`}>
            {statusText[status]}
          </div>
        </div>
        <p className="mb-10 max-w-2xl text-sm leading-7 text-white/62">{notes}</p>
        {children}
      </div>
    </section>
  );
}

function SampleCard({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-36 border border-white/12 bg-white/[0.035] p-6 shadow-2xl shadow-black/20">
      {children}
    </div>
  );
}

function ScrollRangeDemo() {
  const ref = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ['start end', 'end start'],
  });
  const scaleX = useScrollRange(scrollYProgress, [0.15, 0.85], [0.05, 1]);
  const opacity = useScrollRange(scrollYProgress, [0.15, 0.7], [0.25, 1]);

  return (
    <div ref={ref} className="relative min-h-[80vh] border border-white/12 bg-white/[0.03] p-8">
      <div className="sticky top-10">
        <div className="mb-6 h-1 overflow-hidden bg-white/10">
          <motion.div className="h-full origin-left bg-white" style={{ scaleX }} />
        </div>
        <motion.div style={{ opacity }} className="max-w-xl">
          <div className="font-mono text-xs uppercase tracking-[0.18em] text-white/45">
            useScrollRange
          </div>
          <h3 className="mt-4 text-4xl font-medium leading-tight">
            スクロール量を別の表現に変換する低レイヤー部品
          </h3>
          <p className="mt-5 leading-7 text-white/60">
            これ単体で見た目が完成する部品ではなく、ページ専用の演出を作る時の補助です。
          </p>
        </motion.div>
      </div>
    </div>
  );
}

export default function MotionComponentsScratchPage() {
  return (
    <main className="h-screen overflow-y-auto bg-[#0b0907] text-white">
      <section className="px-6 py-20 sm:px-10">
        <div className="mx-auto max-w-6xl">
          <div className="max-w-3xl">
            <div className="mb-8 flex flex-wrap gap-3 text-sm text-white/60">
              <a href="/scratch/motion-components" className="border border-white/20 px-4 py-2 text-white">
                モーション
              </a>
              <a href="/scratch/typography-components" className="border border-white/10 px-4 py-2 hover:border-white/30">
                文字組み
              </a>
            </div>
            <div className="mb-5 font-mono text-xs uppercase tracking-[0.22em] text-white/45">
              Scratch / Motion Components
            </div>
            <h1 className="text-5xl font-medium leading-[1.04] tracking-normal sm:text-7xl">
              モーション部品カタログ
            </h1>
            <p className="mt-7 max-w-2xl text-base leading-8 text-white/62">
              既存の motion component を実画面で確認するためのページです。Dan に再利用させてよい品質か、
              壊れやすいか、見た目として効いているかをここで判断します。
            </p>
          </div>
          <div className="mt-10 grid gap-2 text-sm text-white/60 sm:grid-cols-4">
            {[
              'FadeIn / Reveal',
              'Stagger',
              'ImageReveal',
              'ParallaxMedia',
              'TextReveal',
              'PinnedStory',
              'StickyStory',
              'SectionThemeShift',
              'useScrollRange',
            ].map((item) => (
              <a key={item} href={`#${item.toLowerCase().replaceAll(' / ', '-').replaceAll(' ', '-')}`} className="border border-white/10 px-4 py-3 hover:border-white/30">
                {item}
              </a>
            ))}
          </div>
        </div>
      </section>

      <DemoBlock
        id="fadein-reveal"
        title="FadeIn / Reveal"
        status="usable"
        notes="基本のフェードインです。低リスクですが、これだけで高級感が出るわけではありません。あくまで最低限の出現演出です。"
      >
        <div className="grid gap-4 sm:grid-cols-3">
          {[0, 0.12, 0.24].map((delay, index) => (
            <FadeIn key={delay} delay={delay}>
              <SampleCard>
                <div className="font-mono text-xs text-white/40">0{index + 1}</div>
                <h3 className="mt-8 text-2xl">静かに表示</h3>
                <p className="mt-3 text-sm leading-6 text-white/55">
                  透明度と少しの上下移動だけで出します。
                </p>
              </SampleCard>
            </FadeIn>
          ))}
        </div>
      </DemoBlock>

      <DemoBlock
        id="stagger"
        title="Stagger / StaggerItem"
        status="usable"
        notes="カードやリストを順番に出す部品です。強く使いすぎるとテンプレ感が出るので、控えめな用途向けです。"
      >
        <Stagger className="grid gap-4 sm:grid-cols-4" gap={0.1}>
          {['ヒーロー', 'お品書き', 'こだわり', 'アクセス'].map((item) => (
            <StaggerItem key={item}>
              <SampleCard>
                <div className="text-3xl">{item}</div>
                <div className="mt-8 h-px bg-white/20" />
              </SampleCard>
            </StaggerItem>
          ))}
        </Stagger>
      </DemoBlock>

      <DemoBlock
        id="imagereveal"
        title="ImageReveal"
        status="review"
        notes="写真をマスクで開く演出です。うまく使うと編集的ですが、環境によって表示が固まる/ギミックっぽくなる可能性があるため要確認です。"
      >
        <div className="grid gap-6 sm:grid-cols-2">
          <ImageReveal
            src={imageA}
            alt="カウンターの写真"
            direction="left"
            className="aspect-[4/3] bg-white/5"
            imageClassName="h-full w-full object-cover"
          />
          <ImageReveal
            src={imageB}
            alt="料理の写真"
            direction="bottom"
            className="aspect-[4/3] bg-white/5"
            imageClassName="h-full w-full object-cover"
          />
        </div>
      </DemoBlock>

      <DemoBlock
        id="parallaxmedia"
        title="ParallaxMedia"
        status="usable"
        notes="写真や動画を少し遅れて動かす部品です。大きな写真やフルブリードに使うと効きます。小さいサムネイルには向きません。"
      >
        <ParallaxMedia
          src={imageC}
          alt="店内カウンター"
          intensity="medium"
          className="h-[70vh] border border-white/10"
          mediaClassName="h-[calc(100%+112px)] w-full object-cover"
        />
      </DemoBlock>

      <DemoBlock
        id="textreveal"
        title="TextReveal"
        status="usable"
        notes="見出しを行ごとに出す部品です。ヒーローや章見出しには使えますが、本文には使わない方がよいです。"
      >
        <TextReveal
          text={'動きは、\n装飾ではなく設計。'}
          as="h2"
          className="text-5xl font-medium leading-[1.08] sm:text-7xl"
          lineClassName="pb-2"
        />
      </DemoBlock>

      <DemoBlock
        id="pinnedstory"
        title="PinnedStory"
        status="usable"
        notes="StickyStory の本命置き換え候補です。CSS sticky に頼らず、JS でメディアを擬似固定します。章ごとに画像/動画が切り替わり、最後の章までメディアが残るかを確認します。"
      >
        <PinnedStory
          progressLabel="pinned story"
          className="min-h-[280vh]"
          mediaFrameClassName="border border-white/10 bg-white/5"
          chapters={[
            {
              eyebrow: '01 / 動画',
              title: 'メディアを画面内に留める',
              body: '左側の映像がその場に残り、右側の文章だけが進む見せ方です。',
              media: (
                <video
                  src={videoA}
                  poster={posterA}
                  autoPlay
                  muted
                  loop
                  playsInline
                  className="h-full w-full object-cover"
                />
              ),
            },
            {
              eyebrow: '02 / 写真',
              title: '章ごとにメディアを切り替える',
              body: '章の進行に合わせて、左側の写真や動画が切り替わります。',
              media: <img src={imageB} alt="" className="h-full w-full object-cover" />,
            },
            {
              eyebrow: '03 / 読了',
              title: '最後までメディアを残す',
              body: '最後の文章を読み終えるまで、左側のメディアが画面内に残る必要があります。',
              media: <img src={imageC} alt="" className="h-full w-full object-cover" />,
            },
          ]}
        />
      </DemoBlock>

      <DemoBlock
        id="stickystory"
        title="StickyStory"
        status="risky"
        notes="片側のメディアを固定し、章ごとに文章と画像/動画を切り替える想定の部品です。現状は CSS sticky と viewport callback に依存しており、実環境で壊れやすいので危険扱いです。"
      >
        <StickyStory
          progressLabel="sticky story"
          className="min-h-[280vh]"
          mediaClassName="rounded-sm"
          chapters={[
            {
              eyebrow: '01 / 動画',
              title: 'メディアが固定されるべき場所',
              body: 'この途中で左側の映像が流れて消えるなら、本番で使う品質ではありません。',
              media: (
                <video
                  src={videoA}
                  poster={posterA}
                  autoPlay
                  muted
                  loop
                  playsInline
                  className="h-full w-full object-cover"
                />
              ),
            },
            {
              eyebrow: '02 / 写真',
              title: '章が進むと写真が切り替わる',
              body: '章の切り替わりが分かること、切り替えのタイミングが自然なことを確認します。',
              media: <img src={imageB} alt="" className="h-full w-full object-cover" />,
            },
            {
              eyebrow: '03 / 最後の保持',
              title: '最後の章までメディアが残る',
              body: '五条の craft セクションで問題になった失敗パターンをここで確認します。',
              media: <img src={imageC} alt="" className="h-full w-full object-cover" />,
            },
          ]}
        />
      </DemoBlock>

      <DemoBlock
        id="sectionthemeshift"
        title="SectionThemeShift"
        status="review"
        notes="セクションに入る時に背景色や文字色を変える部品です。雰囲気作りには使えますが、理由なく使うと安っぽくなります。"
      >
        <SectionThemeShift
          className="min-h-[90vh] border border-white/10 p-8"
          from="#120d09"
          to="#e9dcc8"
          colorFrom="#ffffff"
          colorTo="#1d1510"
        >
          <div className="sticky top-12 max-w-2xl">
            <div className="font-mono text-xs uppercase tracking-[0.18em] opacity-50">
              theme shift
            </div>
            <h3 className="mt-5 text-5xl font-medium leading-tight">
              セクションの進入に合わせて背景トーンが変わります。
            </h3>
          </div>
        </SectionThemeShift>
      </DemoBlock>

      <DemoBlock
        id="usescrollrange"
        title="useScrollRange"
        status="review"
        notes="スクロール量を別の値に変換する低レイヤーの補助です。完成済みの見た目部品ではなく、専用演出を作る時に使います。"
      >
        <ScrollRangeDemo />
      </DemoBlock>
    </main>
  );
}
