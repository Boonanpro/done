"use client";

// T3 スクロール動画ヒーロー（Royal Pop 型）のスクラブ機構 実証デモ
// - スクロール量に応じて video.currentTime を動かす（コマ送り）
// - rAF で目標時刻へ lerp して滑らかに
// - 既存素材 /amagasaki-hero.mp4（追加npm・AI生成不要）
// - ⚠️ このアプリは globals.css で html,body{overflow:hidden}（固定ビューポート設計）。
//   そのため body ではなく **内部スクロールコンテナ**(<main> 自体)をスクロールさせ、
//   スクラブもそのコンテナのスクロールから算出する（artifacts と同じパターン）。
// - 本番 T3 では GSAP ScrollTrigger + Lenis + canvasフレーム方式で更に滑らかにする

import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";

const VIDEO_SRC = "/amagasaki-hero-seek.mp4"; // 全フレームkeyframe再エンコード版（スクラブ用）
const SCROLL_HEIGHT_VH = 320; // スクラブを駆動する縦長エリア

export default function ScrollVideoTest() {
  const scrollerRef = useRef<HTMLElement>(null);
  const scrubRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const targetTimeRef = useRef(0);
  const rafRef = useRef<number | null>(null);
  const [progress, setProgress] = useState(0);
  const [ready, setReady] = useState(false);

  // 内部スクロールコンテナのスクロール → 目標再生位置
  const update = () => {
    const scroller = scrollerRef.current;
    const scrub = scrubRef.current;
    const video = videoRef.current;
    if (!scroller || !scrub || !video || !video.duration) return;
    const sRect = scroller.getBoundingClientRect();
    const cRect = scrub.getBoundingClientRect();
    const passed = sRect.top - cRect.top; // scrub の上端がコンテナ上端を越えた量
    const total = scrub.offsetHeight - scroller.clientHeight; // sticky 中の可動距離
    const p = total > 0 ? Math.min(Math.max(passed / total, 0), 1) : 0;
    setProgress(p);
    targetTimeRef.current = p * video.duration;
  };

  // rAF で currentTime を目標へ lerp（スクラブを滑らかに）
  useEffect(() => {
    const tick = () => {
      const video = videoRef.current;
      if (video && video.duration) {
        const cur = video.currentTime;
        const target = targetTimeRef.current;
        if (Math.abs(target - cur) > 0.01) {
          try {
            video.currentTime = cur + (target - cur) * 0.15;
          } catch {
            /* seek 中は無視 */
          }
        }
      }
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, []);

  return (
    <main
      ref={scrollerRef}
      onScroll={update}
      className="h-screen overflow-y-auto bg-black text-white"
    >
      {/* イントロ（フラット） */}
      <section className="flex h-screen flex-col items-center justify-center gap-4 px-6 text-center">
        <h1 className="text-4xl font-bold sm:text-6xl">スクロールで動画が動く</h1>
        <p className="text-white/60">
          下にスクロールしてください（T3: scroll-video hero のスクラブ実証）
        </p>
        <div className="mt-4 animate-bounce text-white/40">↓</div>
      </section>

      {/* スクロールスクラブ動画 */}
      <div
        ref={scrubRef}
        style={{ height: `${SCROLL_HEIGHT_VH}vh` }}
        className="relative"
      >
        <div className="sticky top-0 flex h-screen items-center justify-center overflow-hidden">
          <video
            ref={videoRef}
            src={VIDEO_SRC}
            muted
            playsInline
            preload="auto"
            onLoadedMetadata={() => {
              setReady(true);
              update();
            }}
            className="h-full w-full object-cover"
            style={{ filter: "brightness(0.7)" }}
          />

          {/* 進捗バー */}
          <div
            className="absolute left-0 top-0 h-1 bg-white"
            style={{ width: `${progress * 100}%` }}
          />

          {/* スクロール位置に連動する見出し（framer-motion） */}
          <div className="absolute inset-0 flex items-center justify-center px-6 text-center">
            {progress < 0.34 && (
              <motion.h2
                key="a"
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                className="text-3xl font-semibold drop-shadow sm:text-5xl"
              >
                映像が主役のヒーロー
              </motion.h2>
            )}
            {progress >= 0.34 && progress < 0.67 && (
              <motion.h2
                key="b"
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                className="text-3xl font-semibold drop-shadow sm:text-5xl"
              >
                スクロール量 ＝ 再生位置
              </motion.h2>
            )}
            {progress >= 0.67 && (
              <motion.h2
                key="c"
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                className="text-3xl font-semibold drop-shadow sm:text-5xl"
              >
                Royal Pop 型の作り方
              </motion.h2>
            )}
          </div>

          {!ready && (
            <div className="absolute inset-0 flex items-center justify-center bg-black text-white/50">
              動画を読み込み中…
            </div>
          )}
        </div>
      </div>

      {/* アウトロ（フラットに戻る） */}
      <section className="flex h-screen flex-col items-center justify-center gap-3 px-6 text-center">
        <h2 className="text-3xl font-bold sm:text-5xl">ここから通常コンテンツ</h2>
        <p className="text-white/60">スクロールを抜けるとフラットなセクション（T1）に戻る</p>
      </section>
    </main>
  );
}
