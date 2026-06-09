"use client";

/**
 * CraftStory — 五条 craft セクション専用のスクロール固定ナラティブ。
 *
 * 旧 PinnedStory（共通部品）から移行。脆さの原因だった「scroller 自動検出」を
 * やめ、gsap-scrolltrigger スキルの基本に従って **既定の window スクローラ**で
 * ピン留めする（artifacts は body:auto で文書スクロールのため window が正）。
 *
 * - PC(lg+): 左の映像列を ScrollTrigger で固定し、右の章テキストをスクロール。
 *   章ごとに映像/写真を切り替える。
 * - モバイル: 固定はせず縦に積む（ピン留めをスマホへ強制しない）。
 */

import * as React from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { gsap } from "gsap";
import { useGSAP } from "@gsap/react";
import { ScrollTrigger } from "gsap/ScrollTrigger";

if (typeof window !== "undefined") {
  gsap.registerPlugin(ScrollTrigger, useGSAP);
}

const EASE: [number, number, number, number] = [0.22, 1, 0.36, 1];

export type CraftStoryChapter = {
  eyebrow?: string;
  title: string;
  body?: string;
  media?: React.ReactNode;
};

type CraftStoryProps = {
  chapters: CraftStoryChapter[];
  className?: string;
  mediaFrameClassName?: string;
  eyebrowClassName?: string;
  progressLabel?: string;
  /** 固定開始時にビューポート上端からあける余白(px)。ナビ分。 */
  pinTop?: number;
};

export function CraftStory({
  chapters,
  className,
  mediaFrameClassName,
  eyebrowClassName,
  progressLabel = "story",
  pinTop = 96,
}: CraftStoryProps) {
  const [activeIndex, setActiveIndex] = React.useState(0);
  const rootRef = React.useRef<HTMLElement>(null);
  const mediaColRef = React.useRef<HTMLDivElement>(null);
  const chapterRefs = React.useRef<Array<HTMLDivElement | null>>([]);
  const reduceMotion = useReducedMotion();
  const activeChapter = chapters[activeIndex] ?? chapters[0];

  useGSAP(
    () => {
      const root = rootRef.current;
      const mediaCol = mediaColRef.current;
      if (!root || !mediaCol || reduceMotion || window.innerWidth < 1024) return;

      // 映像列を固定（既定の window スクローラ。独自スクローラは掴まない）
      const pinTrigger = ScrollTrigger.create({
        trigger: root,
        start: () => `top ${pinTop}`,
        end: "bottom bottom",
        pin: mediaCol,
        pinSpacing: false,
        anticipatePin: 1,
        invalidateOnRefresh: true,
      });

      // 章ごとに active を切り替え（中央に来た章をアクティブに）
      const chapterTriggers = chapterRefs.current
        .filter((el): el is HTMLDivElement => !!el)
        .map((el, index) =>
          ScrollTrigger.create({
            trigger: el,
            start: "top center",
            end: "bottom center",
            onToggle: (self) => {
              if (self.isActive) setActiveIndex(index);
            },
          }),
        );

      requestAnimationFrame(() => ScrollTrigger.refresh());

      return () => {
        pinTrigger.kill();
        chapterTriggers.forEach((t) => t.kill());
      };
    },
    { dependencies: [chapters.length, pinTop, reduceMotion], scope: rootRef, revertOnUpdate: true },
  );

  return (
    <>
      {/* ===== モバイル: 縦積み（固定しない） ===== */}
      <div className={`flex flex-col gap-8 lg:hidden ${className ?? ""}`}>
        {chapters.map((chapter, index) => (
          <article key={`${chapter.title}-m`} className="overflow-hidden">
            {chapter.media && (
              <div
                className={`relative aspect-[4/5] overflow-hidden rounded-sm bg-muted ${mediaFrameClassName ?? ""}`}
              >
                {chapter.media}
              </div>
            )}
            <div className="pt-5">
              {chapter.eyebrow && (
                <div className={`mb-3 text-xs tracking-[0.08em] text-primary ${eyebrowClassName ?? ""}`}>
                  {chapter.eyebrow}
                </div>
              )}
              <h3 className="text-2xl leading-tight">{chapter.title}</h3>
              {chapter.body && (
                <p className="mt-4 leading-8 text-muted-foreground">{chapter.body}</p>
              )}
            </div>
          </article>
        ))}
      </div>

      {/* ===== PC: 左の映像を固定、右の章をスクロール ===== */}
      <section
        ref={rootRef}
        data-motion="craft-story"
        className={`hidden gap-12 lg:grid lg:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)] ${className ?? ""}`}
      >
        <div ref={mediaColRef} className="relative">
          <div className="h-[calc(100vh-8rem)]">
            <div className={`relative h-full overflow-hidden rounded-sm ${mediaFrameClassName ?? ""}`}>
              <AnimatePresence mode="wait">
                <motion.div
                  key={activeIndex}
                  className="h-full"
                  initial={reduceMotion ? false : { opacity: 0, scale: 1.025 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={reduceMotion ? { opacity: 0 } : { opacity: 0, scale: 0.99 }}
                  transition={{ duration: 0.55, ease: EASE }}
                >
                  {activeChapter?.media}
                </motion.div>
              </AnimatePresence>
              <div className="pointer-events-none absolute inset-x-0 bottom-0 flex items-end justify-between gap-4 bg-gradient-to-t from-black/70 via-black/20 to-transparent p-5 text-white">
                <div>
                  <div className="text-[10px] uppercase tracking-[0.28em] text-white/65">
                    {progressLabel}
                  </div>
                  <div className="mt-1 font-serif text-lg">
                    {String(activeIndex + 1).padStart(2, "0")} /{" "}
                    {String(chapters.length).padStart(2, "0")}
                  </div>
                </div>
                <div className="flex min-w-28 gap-1.5">
                  {chapters.map((chapter, index) => (
                    <span
                      key={`${chapter.title}-bar`}
                      className={`h-px flex-1 transition-colors duration-300 ${
                        index <= activeIndex ? "bg-white" : "bg-white/30"
                      }`}
                    />
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="relative">
          <div className="absolute bottom-0 left-4 top-0 hidden w-px bg-border/60 lg:block" />
          {chapters.map((chapter, index) => (
            <div
              key={`${chapter.title}-${index}`}
              ref={(el) => {
                chapterRefs.current[index] = el;
              }}
              className="relative flex min-h-[86vh] flex-col justify-center py-16 lg:pl-12"
            >
              <div
                aria-hidden="true"
                className={`absolute left-4 top-1/2 hidden h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border transition-colors duration-300 lg:block ${
                  activeIndex === index ? "border-primary bg-primary" : "border-border bg-background"
                }`}
              />
              {chapter.eyebrow && (
                <div
                  className={`mb-4 text-xs tracking-[0.08em] transition-colors duration-300 ${
                    activeIndex === index ? "text-primary" : "text-muted-foreground"
                  } ${eyebrowClassName ?? ""}`}
                >
                  {chapter.eyebrow}
                </div>
              )}
              <h3 className="max-w-xl text-3xl leading-tight md:text-5xl">{chapter.title}</h3>
              {chapter.body && (
                <p className="mt-5 max-w-xl leading-8 text-muted-foreground">{chapter.body}</p>
              )}
            </div>
          ))}
          <div aria-hidden="true" className="hidden h-[64vh] lg:block" />
        </div>
      </section>
    </>
  );
}
