'use client';

/**
 * VoiceEdgeGlow — 音声モードの間、画面全体のふちをぼんやり光らせる（2026-11-22 本人「右下にオーブを出すんじゃなくて
 * UI全体を俺やダンの声に合わせて動くぼんやりとした光で囲ってほしい」）。
 *
 * オーブ（voice-orb.tsx）と同じ決まり:
 * - 本人の声 = 光の帯が太く・明るくなる（ボイスメーター）。静かになると細く戻る。
 * - ダンの声 = 光の玉がふちを流れる速さと揺らめきが増す。話していない時はごくゆっくり漂う。
 * 画面の操作は邪魔しない（pointer-events: none）。描く板は画面の 1/6 の細かさで、拡大してぼかしを出す
 * （毎コマ全画面の blur や box-shadow を描き直すより軽い。エディターの再生と並んで動く）。
 */
import { useEffect, useRef } from 'react';

interface VoiceEdgeGlowProps {
  getUserLevel: () => number;
  getAiLevel: () => number;
  active: boolean;
}

// 玉の色: 本人の声で前に出る青緑と、ダンの声で前に出る青紫を混ぜる
const BLOBS = [
  { hue: 200, sp: 0.018, ph0: 0.0, r: 1.0 },
  { hue: 225, sp: -0.013, ph0: 0.17, r: 0.85 },
  { hue: 260, sp: 0.011, ph0: 0.33, r: 1.1 },
  { hue: 190, sp: -0.016, ph0: 0.5, r: 0.9 },
  { hue: 240, sp: 0.014, ph0: 0.66, r: 1.0 },
  { hue: 280, sp: -0.01, ph0: 0.83, r: 0.8 },
  { hue: 210, sp: 0.02, ph0: 0.08, r: 0.75 },
  { hue: 250, sp: -0.012, ph0: 0.58, r: 0.95 },
];

const SCALE = 1 / 6;

/** ふちの上の位置 t(0〜1、時計回り) → 板の座標 */
function onEdge(t: number, w: number, h: number): [number, number] {
  const p = 2 * (w + h);
  let d = (((t % 1) + 1) % 1) * p;
  if (d < w) return [d, 0];
  d -= w;
  if (d < h) return [w, d];
  d -= h;
  if (d < w) return [w - d, h];
  d -= w;
  return [0, h - d];
}

export function VoiceEdgeGlow({ getUserLevel, getAiLevel, active }: VoiceEdgeGlowProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const getUserRef = useRef(getUserLevel);
  const getAiRef = useRef(getAiLevel);
  const activeRef = useRef(active);
  useEffect(() => {
    getUserRef.current = getUserLevel;
    getAiRef.current = getAiLevel;
    activeRef.current = active;
  });

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const resize = () => {
      canvas.width = Math.max(32, Math.round(window.innerWidth * SCALE));
      canvas.height = Math.max(32, Math.round(window.innerHeight * SCALE));
    };
    resize();
    window.addEventListener('resize', resize);

    let raf = 0;
    let lastT = performance.now();
    let userSm = 0;
    let aiSm = 0;
    let appear = 0; // 開いた時にふわっと出す
    let breath = 0;
    const phases = BLOBS.map((b) => b.ph0);

    const draw = (t: number) => {
      const dt = Math.min(0.05, (t - lastT) / 1000);
      lastT = t;
      const on = activeRef.current;
      const rawUser = on ? Math.min(1, getUserRef.current()) : 0;
      let rawAi = on ? Math.min(1, getAiRef.current()) : 0;
      if (rawAi < 0.07) rawAi = 0; // 無音・雑音では動かさない
      const userGate = rawUser < 0.12 ? 0 : (rawUser - 0.12) / 0.88; // 部屋の雑音で太らない
      userSm += (userGate - userSm) * (userGate > userSm ? 0.35 : 0.08);
      aiSm += (rawAi - aiSm) * (rawAi > aiSm ? 0.3 : 0.06);
      appear += ((on ? 1 : 0.45) - appear) * 0.04;
      breath += dt;

      const w = canvas.width;
      const h = canvas.height;
      const m = Math.min(w, h);
      ctx.clearRect(0, 0, w, h);

      const idle = 0.5 + Math.sin(breath * 1.1) * 0.08;
      // 帯の太さ: 待機は細く、本人の声で太る
      const band = m * (0.03 + userSm * 0.05);
      const glow = appear * (idle * 0.55 + userSm * 0.55 + aiSm * 0.45);

      // ふちの帯（4辺の内向きのグラデーション）
      const edge = (x0: number, y0: number, x1: number, y1: number, rx: number, ry: number, rw: number, rh: number) => {
        const g = ctx.createLinearGradient(x0, y0, x1, y1);
        g.addColorStop(0, `hsla(${215 + aiSm * 30},90%,62%,${Math.min(0.85, glow * 0.9)})`);
        g.addColorStop(1, 'hsla(220,90%,62%,0)');
        ctx.fillStyle = g;
        ctx.fillRect(rx, ry, rw, rh);
      };
      ctx.globalCompositeOperation = 'source-over';
      edge(0, 0, 0, band, 0, 0, w, band);
      edge(0, h, 0, h - band, 0, h - band, w, band);
      edge(0, 0, band, 0, 0, 0, band, h);
      edge(w, 0, w - band, 0, w - band, 0, band, h);

      // ふちを流れる光の玉（ダンの声で速く・揺らめく）
      ctx.globalCompositeOperation = 'lighter';
      const drive = 1 + aiSm * 6;
      for (let i = 0; i < BLOBS.length; i += 1) {
        const b = BLOBS[i];
        phases[i] += dt * b.sp * drive;
        const [x, y] = onEdge(phases[i], w, h);
        const wobble = 1 + Math.sin(breath * 2.2 + i * 1.7) * (0.1 + aiSm * 0.35);
        const rr = band * 1.3 * b.r * wobble;
        const a = Math.min(0.9, appear * (0.22 + userSm * 0.4 + aiSm * 0.5));
        const g = ctx.createRadialGradient(x, y, 0, x, y, rr);
        g.addColorStop(0, `hsla(${b.hue},95%,65%,${a})`);
        g.addColorStop(1, `hsla(${b.hue},95%,65%,0)`);
        ctx.fillStyle = g;
        ctx.beginPath();
        ctx.arc(x, y, rr, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.globalCompositeOperation = 'source-over';
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('resize', resize);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden
      data-voice-edge-glow
      className="pointer-events-none fixed inset-0 z-[60] h-full w-full"
      style={{ width: '100vw', height: '100dvh' }}
    />
  );
}
