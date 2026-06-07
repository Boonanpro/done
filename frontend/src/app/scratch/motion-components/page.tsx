'use client';

import { motion, useScroll } from 'framer-motion';
import { useRef } from 'react';

import {
  FadeIn,
  ImageReveal,
  ParallaxMedia,
  SectionThemeShift,
  Stagger,
  StaggerItem,
  TextReveal,
  useScrollRange,
} from '@/components/motion';

const imageA = '/yonago-gojo/g1.jpg';
const imageB = '/yonago-gojo/g3.jpg';
const imageC = '/yonago-gojo/g4.jpg';

type Status = 'usable' | 'review';

const statusText: Record<Status, string> = {
  usable: '採用可',
  review: '要確認',
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
            スクロール量を別の表現へ変換する補助部品
          </h3>
          <p className="mt-5 leading-7 text-white/60">
            これ単体で見た目が完成する部品ではありません。専用演出を作る時の低レイヤー部品です。
          </p>
        </motion.div>
      </div>
    </div>
  );
}

export default function MotionComponentsScratchPage() {
  const navItems = [
    ['FadeIn / Reveal', 'fadein-reveal'],
    ['Stagger', 'stagger'],
    ['ImageReveal', 'imagereveal'],
    ['ParallaxMedia', 'parallaxmedia'],
    ['TextReveal', 'textreveal'],
    ['SectionThemeShift', 'sectionthemeshift'],
    ['useScrollRange', 'usescrollrange'],
  ];

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
            {navItems.map(([label, id]) => (
              <a key={id} href={`#${id}`} className="border border-white/10 px-4 py-3 hover:border-white/30">
                {label}
              </a>
            ))}
          </div>
        </div>
      </section>

      <DemoBlock
        id="fadein-reveal"
        title="FadeIn / Reveal"
        status="usable"
        notes="基本のフェードインです。低リスクですが、これだけで高級感が出るわけではありません。最低限の出現演出です。"
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
