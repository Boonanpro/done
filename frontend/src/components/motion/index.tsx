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
import { motion, type Variants } from 'framer-motion';
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
