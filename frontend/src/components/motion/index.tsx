'use client';

/**
 * 再利用デザイン部品: スクロール出現アニメーション（framer-motion ベース）。
 *
 * 成果物で「ふわっと出す」演出を手書きせず、これを使う:
 *   <FadeIn> ... </FadeIn>                     1要素をふわっと表示
 *   <Stagger><StaggerItem/>...<StaggerItem/>   リストを順番に表示
 *
 * 配色はいじらない（中身の見た目はそのまま）。出現の動きだけを足す部品。
 */
import { AnimatePresence, motion, type Variants } from 'framer-motion';
import {
  useReducedMotion,
  useScroll,
  useTransform,
  type MotionValue,
} from 'framer-motion';
import * as React from 'react';
import type { ReactNode } from 'react';

const EASE: [number, number, number, number] = [0.22, 1, 0.36, 1];

type FadeInProps = {
  children: ReactNode;
  className?: string;
  /** 出現の遅延（秒） */
  delay?: number;
  /** 開始時の下方向オフセット（px） */
  y?: number;
  /** アニメ時間（秒） */
  duration?: number;
  /** 一度出たら再アニメしない（default true） */
  once?: boolean;
};

/** スクロールで画面に入ったら、ふわっと上に出現する。 */
export function FadeIn({
  children,
  className,
  delay = 0,
  y = 16,
  duration = 0.5,
  once = true,
}: FadeInProps) {
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once, amount: 0.2 }}
      transition={{ duration, delay, ease: EASE }}
    >
      {children}
    </motion.div>
  );
}

/** FadeIn の意味的エイリアス（スクロール連動の「現れ」を強調したい時に）。 */
export const Reveal = FadeIn;

type StaggerProps = {
  children: ReactNode;
  className?: string;
  /** 子要素ごとの遅延（秒） */
  gap?: number;
  once?: boolean;
};

/** 子要素 (<StaggerItem>) を順番に出現させるコンテナ。 */
export function Stagger({ children, className, gap = 0.08, once = true }: StaggerProps) {
  const container: Variants = {
    hidden: {},
    show: { transition: { staggerChildren: gap } },
  };
  return (
    <motion.div
      className={className}
      variants={container}
      initial="hidden"
      whileInView="show"
      viewport={{ once, amount: 0.2 }}
    >
      {children}
    </motion.div>
  );
}

type StaggerItemProps = {
  children: ReactNode;
  className?: string;
  y?: number;
  duration?: number;
};

/** <Stagger> の中で使う1要素。 */
export function StaggerItem({ children, className, y = 16, duration = 0.5 }: StaggerItemProps) {
  const item: Variants = {
    hidden: { opacity: 0, y },
    show: { opacity: 1, y: 0, transition: { duration, ease: EASE } },
  };
  return (
    <motion.div className={className} variants={item}>
      {children}
    </motion.div>
  );
}

type ImageRevealProps = {
  src: string;
  alt: string;
  className?: string;
  imageClassName?: string;
  direction?: 'left' | 'right' | 'top' | 'bottom';
  duration?: number;
  delay?: number;
  once?: boolean;
};

/** Reveals an image with a directional clip mask. Use for editorial HP image entrances. */
export function ImageReveal({
  src,
  alt,
  className,
  imageClassName,
  direction = 'left',
  duration = 0.9,
  delay = 0,
  once = true,
}: ImageRevealProps) {
  const shouldReduceMotion = useReducedMotion();
  const hiddenClip = {
    left: 'inset(0 100% 0 0)',
    right: 'inset(0 0 0 100%)',
    top: 'inset(0 0 100% 0)',
    bottom: 'inset(100% 0 0 0)',
  }[direction];

  return (
    <motion.div
      className={className}
      initial={shouldReduceMotion ? false : { clipPath: hiddenClip, opacity: 0.96 }}
      whileInView={{ clipPath: 'inset(0 0 0 0)', opacity: 1 }}
      viewport={{ once, amount: 0.35 }}
      transition={{ duration, delay, ease: EASE }}
      style={{ overflow: 'hidden' }}
    >
      <motion.img
        src={src}
        alt={alt}
        className={imageClassName}
        draggable={false}
        initial={shouldReduceMotion ? false : { scale: 1.08 }}
        whileInView={{ scale: 1 }}
        viewport={{ once, amount: 0.35 }}
        transition={{ duration: duration + 0.15, delay, ease: EASE }}
      />
    </motion.div>
  );
}

type ParallaxMediaProps = {
  src: string;
  alt?: string;
  type?: 'image' | 'video';
  className?: string;
  mediaClassName?: string;
  intensity?: 'subtle' | 'medium' | 'strong';
  poster?: string;
};

/** Moves media at a slower rate than the page scroll. Keep inside an overflow-hidden frame. */
export function ParallaxMedia({
  src,
  alt = '',
  type = 'image',
  className,
  mediaClassName,
  intensity = 'subtle',
  poster,
}: ParallaxMediaProps) {
  const ref = React.useRef<HTMLDivElement>(null);
  const shouldReduceMotion = useReducedMotion();
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ['start end', 'end start'],
  });
  const amount = { subtle: 28, medium: 56, strong: 90 }[intensity];
  const y = useTransform(scrollYProgress, [0, 1], shouldReduceMotion ? [0, 0] : [-amount, amount]);

  return (
    <div ref={ref} className={`overflow-hidden ${className ?? ''}`}>
      <motion.div style={{ y }} className="h-full w-full">
        {type === 'video' ? (
          <video
            src={src}
            poster={poster}
            className={mediaClassName}
            autoPlay
            muted
            loop
            playsInline
          />
        ) : (
          <img src={src} alt={alt} className={mediaClassName} draggable={false} />
        )}
      </motion.div>
    </div>
  );
}

type TextRevealProps = {
  text: string;
  as?: 'p' | 'span' | 'div' | 'h1' | 'h2' | 'h3';
  className?: string;
  lineClassName?: string;
  delay?: number;
  gap?: number;
  once?: boolean;
};

/** Reveals text line by line. Pass explicit newline breaks when line rhythm matters. */
export function TextReveal({
  text,
  as = 'div',
  className,
  lineClassName,
  delay = 0,
  gap = 0.08,
  once = true,
}: TextRevealProps) {
  const Tag = as;
  const lines = text.split('\n');

  return (
    <Tag className={className}>
      {lines.map((line, index) => (
        <span key={`${line}-${index}`} className="block overflow-hidden">
          <motion.span
            className={`block ${lineClassName ?? ''}`}
            initial={{ y: '110%', opacity: 0 }}
            whileInView={{ y: '0%', opacity: 1 }}
            viewport={{ once, amount: 0.7 }}
            transition={{ duration: 0.65, delay: delay + index * gap, ease: EASE }}
          >
            {line}
          </motion.span>
        </span>
      ))}
    </Tag>
  );
}

export type StickyStoryChapter = {
  eyebrow?: string;
  title: string;
  body?: string;
  media?: ReactNode;
};

type StickyStoryProps = {
  chapters: StickyStoryChapter[];
  className?: string;
  mediaClassName?: string;
  contentClassName?: string;
  chapterClassName?: string;
  progressLabel?: string;
  stickyTopClassName?: string;
};

/** Sticky editorial section with visible chapter progress and media handoff. */
export function StickyStory({
  chapters,
  className,
  mediaClassName,
  contentClassName,
  chapterClassName,
  progressLabel = 'story',
  stickyTopClassName = 'lg:top-24',
}: StickyStoryProps) {
  const [activeIndex, setActiveIndex] = React.useState(0);
  const shouldReduceMotion = useReducedMotion();
  const mediaForActiveChapter =
    chapters[activeIndex]?.media ??
    [...chapters.slice(0, activeIndex + 1)].reverse().find((chapter) => chapter.media)?.media ??
    chapters.find((chapter) => chapter.media)?.media;

  return (
    <section className={`grid gap-12 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)] ${className ?? ''}`}>
      <div className={`lg:sticky ${stickyTopClassName} lg:h-[calc(100vh-8rem)] ${mediaClassName ?? ''}`}>
        <div className="relative h-full overflow-hidden rounded-sm">
          <AnimatePresence mode="wait">
            <motion.div
              key={activeIndex}
              className="h-full"
              initial={shouldReduceMotion ? false : { opacity: 0, scale: 1.025 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={shouldReduceMotion ? { opacity: 0 } : { opacity: 0, scale: 0.99 }}
              transition={{ duration: 0.55, ease: EASE }}
            >
              {mediaForActiveChapter}
            </motion.div>
          </AnimatePresence>
          <div className="pointer-events-none absolute inset-x-0 bottom-0 flex items-end justify-between gap-4 bg-gradient-to-t from-black/70 via-black/20 to-transparent p-5 text-white">
            <div>
              <div className="text-[10px] uppercase tracking-[0.28em] text-white/65">
                {progressLabel}
              </div>
              <div className="mt-1 font-serif text-lg">
                {String(activeIndex + 1).padStart(2, '0')} /{' '}
                {String(chapters.length).padStart(2, '0')}
              </div>
            </div>
            <div className="flex min-w-28 gap-1.5">
              {chapters.map((chapter, index) => (
                <span
                  key={`${chapter.title}-bar`}
                  className={`h-px flex-1 transition-colors duration-300 ${
                    index <= activeIndex ? 'bg-white' : 'bg-white/30'
                  }`}
                />
              ))}
            </div>
          </div>
        </div>
      </div>
      <div className={`relative ${contentClassName ?? ''}`}>
        <div className="absolute bottom-0 left-4 top-0 hidden w-px bg-border/60 lg:block" />
        {chapters.map((chapter, index) => (
          <motion.article
            key={`${chapter.title}-${index}`}
            className={`relative flex min-h-[78vh] items-center py-16 pl-0 lg:pl-12 ${chapterClassName ?? ''}`}
            onViewportEnter={() => setActiveIndex(index)}
            viewport={{ amount: 0.55, margin: '-15% 0px -25% 0px' }}
          >
            <motion.div
              className="max-w-xl"
              initial={shouldReduceMotion ? false : { opacity: 0.25, y: 36, scale: 0.985 }}
              whileInView={{ opacity: 1, y: 0, scale: 1 }}
              viewport={{ amount: 0.55, margin: '-15% 0px -25% 0px' }}
              transition={{ duration: 0.65, ease: EASE }}
            >
              <div
                className={`absolute left-0 top-1/2 hidden h-3 w-3 -translate-x-[5px] -translate-y-1/2 rounded-full border transition-colors duration-300 lg:block ${
                  activeIndex === index
                    ? 'border-primary bg-primary'
                    : 'border-border bg-background'
                }`}
              />
              {chapter.eyebrow && (
                <div
                  className={`mb-4 text-xs uppercase tracking-[0.28em] transition-colors duration-300 ${
                    activeIndex === index ? 'text-primary' : 'text-muted-foreground'
                  }`}
                >
                  {chapter.eyebrow}
                </div>
              )}
              <h3 className="text-3xl leading-tight md:text-5xl">{chapter.title}</h3>
              {chapter.body && (
                <p className="mt-5 max-w-xl leading-8 text-muted-foreground">{chapter.body}</p>
              )}
              {chapter.media && (
                <div className="mt-8 lg:hidden">{chapter.media}</div>
              )}
            </motion.div>
          </motion.article>
        ))}
      </div>
    </section>
  );
}

type SectionThemeShiftProps = {
  children: ReactNode;
  className?: string;
  from?: string;
  to?: string;
  colorFrom?: string;
  colorTo?: string;
};

/** Animates a section's background/color while it enters the viewport. */
export function SectionThemeShift({
  children,
  className,
  from = 'var(--background)',
  to = 'var(--card)',
  colorFrom = 'var(--foreground)',
  colorTo = 'var(--foreground)',
}: SectionThemeShiftProps) {
  const ref = React.useRef<HTMLElement>(null);
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ['start end', 'center center'],
  });
  const backgroundColor = useTransform(scrollYProgress, [0, 1], [from, to]);
  const color = useTransform(scrollYProgress, [0, 1], [colorFrom, colorTo]);

  return (
    <motion.section ref={ref} className={className} style={{ backgroundColor, color }}>
      {children}
    </motion.section>
  );
}

export function useScrollRange<T>(
  value: MotionValue<number>,
  input: [number, number],
  output: [T, T],
) {
  return useTransform(value, input, output);
}
