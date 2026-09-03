'use client';

/**
 * VoiceOrb — ChatGPT の音声モード準拠のオーブ。
 *
 * 挙動仕様（ユーザー指定 2026-08-23 v2）:
 * - 中心は常に固定。上下左右に動かさない。
 * - ユーザーの声 = ボイスメーター。声の大きさに合わせてオーブが膨張し、静かになると元のサイズへ収縮。
 * - AI の声 = オーブ内部の雲だけが揺らめく。喋っていないときの雲はごくゆっくり漂うだけ。
 * - 色は状態で変えない（常に淡青の雲の球体）。
 *
 * v1 の不具合と対策:
 * - 雲がビクつく → 位相を「絶対時刻×可変速度」で計算していたため、音量が変わるたび
 *   角度がテレポートしていた。各雲が自前の位相を毎フレーム加算する方式（ph += dt*speed）に修正。
 * - 無音でも雲が暴れる → AI音量にノイズゲート（微小音量は0扱い）。
 */
import { useEffect, useRef } from 'react';

interface VoiceOrbProps {
  size?: number;
  /** マイク音量 0〜1（毎フレーム呼ばれる） */
  getUserLevel: () => number;
  /** AI音声の音量 0〜1（毎フレーム呼ばれる） */
  getAiLevel: () => number;
  active: boolean;
}

const CLOUDS = [
  { hue: 210, sat: 90, light: 80, r: 0.5, orbit: 0.26, sp: 0.25, ph0: 0.0 },
  { hue: 195, sat: 85, light: 86, r: 0.42, orbit: 0.3, sp: 0.34, ph0: 2.1 },
  { hue: 225, sat: 80, light: 78, r: 0.46, orbit: 0.22, sp: 0.21, ph0: 4.2 },
  { hue: 205, sat: 60, light: 92, r: 0.36, orbit: 0.32, sp: 0.42, ph0: 1.3 },
  { hue: 240, sat: 70, light: 82, r: 0.38, orbit: 0.28, sp: 0.3, ph0: 5.4 },
];

export function VoiceOrb({ size = 160, getUserLevel, getAiLevel, active }: VoiceOrbProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const getUserRef = useRef(getUserLevel);
  const getAiRef = useRef(getAiLevel);
  getUserRef.current = getUserLevel;
  getAiRef.current = getAiLevel;
  const activeRef = useRef(active);
  activeRef.current = active;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = size * dpr;
    canvas.height = size * dpr;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let raf = 0;
    let userSm = 0;
    let aiSm = 0;
    let lastT = performance.now();
    // 各雲の位相は自前で積分する（速度が変わっても連続、テレポートしない）
    const phases = CLOUDS.map((c) => c.ph0);
    let breath = 0;

    const draw = (t: number) => {
      const dt = Math.min(0.05, (t - lastT) / 1000);
      lastT = t;

      const rawUser = activeRef.current ? Math.min(1, getUserRef.current()) : 0;
      let rawAi = activeRef.current ? Math.min(1, getAiRef.current()) : 0;
      if (rawAi < 0.07) rawAi = 0; // ノイズゲート: 無音・環境ノイズで雲を動かさない
      userSm += (rawUser - userSm) * (rawUser > userSm ? 0.4 : 0.1);
      aiSm += (rawAi - aiSm) * (rawAi > aiSm ? 0.3 : 0.06);
      breath += dt;

      const S = size * dpr;
      const c = S / 2;
      // ---- ユーザー声 = ボイスメーター: 半径だけが音量で膨張/収縮。中心は固定 ----
      const idleBreath = 1 + Math.sin(breath * 0.9) * 0.008; // 待機時のごく浅い呼吸
      const R = S * 0.36 * idleBreath * (1 + userSm * 0.22);

      ctx.clearRect(0, 0, S, S);

      // 外周の光暈（膨張に追従）
      const halo = ctx.createRadialGradient(c, c, R * 0.75, c, c, R * 1.25);
      halo.addColorStop(0, 'rgba(150,190,255,0.20)');
      halo.addColorStop(1, 'rgba(150,190,255,0)');
      ctx.fillStyle = halo;
      ctx.beginPath();
      ctx.arc(c, c, R * 1.25, 0, Math.PI * 2);
      ctx.fill();

      // 球体ベース
      const base = ctx.createRadialGradient(c - R * 0.3, c - R * 0.35, R * 0.1, c, c, R);
      base.addColorStop(0, 'rgba(235,245,255,0.95)');
      base.addColorStop(0.55, 'rgba(190,215,250,0.9)');
      base.addColorStop(1, 'rgba(140,175,240,0.85)');
      ctx.fillStyle = base;
      ctx.beginPath();
      ctx.arc(c, c, R, 0, Math.PI * 2);
      ctx.fill();

      // ---- AI声 = 内部の雲の揺らめき（喋っていない時はゆっくり漂うだけ） ----
      ctx.save();
      ctx.beginPath();
      ctx.arc(c, c, R * 0.985, 0, Math.PI * 2);
      ctx.clip();
      ctx.globalCompositeOperation = 'lighter';
      const drive = 1 + aiSm * 5;
      for (let i = 0; i < CLOUDS.length; i += 1) {
        const cl = CLOUDS[i];
        phases[i] += dt * cl.sp * drive;
        const ph = phases[i];
        const x = c + Math.cos(ph) * R * cl.orbit + Math.sin(ph * 1.7) * R * 0.08;
        const y = c + Math.sin(ph * 1.3) * R * cl.orbit * 0.9 + Math.cos(ph * 2.1) * R * 0.07;
        const rr = R * cl.r * (1 + aiSm * 0.3 * Math.sin(ph * 2.3));
        const alpha = 0.45 + aiSm * 0.4;
        const g = ctx.createRadialGradient(x, y, 0, x, y, rr);
        g.addColorStop(0, `hsla(${cl.hue},${cl.sat}%,${cl.light}%,${alpha})`);
        g.addColorStop(1, `hsla(${cl.hue},${cl.sat}%,${cl.light}%,0)`);
        ctx.fillStyle = g;
        ctx.beginPath();
        ctx.arc(x, y, rr, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.restore();

      // グロスと薄いリム
      const gloss = ctx.createRadialGradient(c - R * 0.25, c - R * 0.45, 0, c - R * 0.25, c - R * 0.45, R * 0.7);
      gloss.addColorStop(0, 'rgba(255,255,255,0.5)');
      gloss.addColorStop(1, 'rgba(255,255,255,0)');
      ctx.fillStyle = gloss;
      ctx.beginPath();
      ctx.arc(c, c, R, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = 'rgba(255,255,255,0.35)';
      ctx.lineWidth = dpr;
      ctx.beginPath();
      ctx.arc(c, c, R, 0, Math.PI * 2);
      ctx.stroke();

      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [size]);

  return <canvas ref={canvasRef} style={{ width: size, height: size, display: 'block' }} aria-label="音声アシスタント" />;
}
