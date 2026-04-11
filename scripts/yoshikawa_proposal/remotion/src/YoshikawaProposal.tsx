import React from "react";
import {
  AbsoluteFill,
  Audio,
  Img,
  Sequence,
  interpolate,
  staticFile,
  useCurrentFrame,
} from "remotion";

const TOTAL_REC = 1060;

// Timeline:
// 0-89:      Intro text
// 90-189:    Rec 0-99 (Google search + typing)
// 190-364:   Rec 100-174 (search results) — hold longer with zoom on first result
// 365-454:   Text: "新明和認定のプロフェッショナルを、Webで伝える。"
// 455-694:   Rec 175-414 (HP hero + 選ばれる理由 + scroll to service start)
// 695-934:   Rec 475-714 (service + 対応車種)
// 935-1024:  Text: "お客様からの問い合わせを、24時間受け付ける。"
// 1025-1234: Rec 775-954 (contact section — phone, form, map) + Rec 955-1059 (footer)
// 1235-1324: Outro text
const TOTAL_FRAMES = 1325;

// Cursor events: [frame, x, y, visible]
// Based on actual frame content coordinates (verified from screenshots)
const CURSOR: Array<{f: number; x: number; y: number; v: boolean}> = [
  // Google search: click search bar
  {f: 90, x: 960, y: 600, v: false},
  {f: 100, x: 880, y: 540, v: true},     // appear near search bar
  {f: 108, x: 880, y: 540, v: true},     // click
  {f: 112, x: 880, y: 540, v: false},    // hide during typing

  // Search results: move to first result link and click
  {f: 190, x: 600, y: 300, v: false},
  {f: 210, x: 350, y: 130, v: true},     // appear at result title
  {f: 240, x: 350, y: 130, v: true},     // hover
  {f: 250, x: 350, y: 130, v: true},     // click
  {f: 255, x: 350, y: 130, v: false},    // hide

  // HP hero: no cursor (just looking)

  // 選ばれる理由: hover on a card
  {f: 580, x: 960, y: 500, v: false},
  {f: 590, x: 350, y: 650, v: true},     // appear at first card
  {f: 610, x: 700, y: 650, v: true},     // move to second card
  {f: 625, x: 700, y: 650, v: false},    // hide

  // Contact: hover phone number then form button
  {f: 1025, x: 400, y: 400, v: false},
  {f: 1060, x: 400, y: 200, v: true},    // phone number
  {f: 1090, x: 400, y: 200, v: true},
  {f: 1110, x: 1100, y: 200, v: true},   // form button
  {f: 1130, x: 1100, y: 200, v: true},
  {f: 1140, x: 1100, y: 200, v: false},  // hide
];

const getCursor = (frame: number): {x: number; y: number; visible: boolean} => {
  let prev = CURSOR[0];
  let next = CURSOR[CURSOR.length - 1];
  for (let i = 0; i < CURSOR.length - 1; i++) {
    if (frame >= CURSOR[i].f && frame <= CURSOR[i + 1].f) {
      prev = CURSOR[i];
      next = CURSOR[i + 1];
      break;
    }
    if (frame < CURSOR[i].f) {
      return {x: 0, y: 0, visible: false};
    }
  }
  if (!prev.v && !next.v) return {x: 0, y: 0, visible: false};
  if (!prev.v) return {x: next.x, y: next.y, visible: false};

  const x = interpolate(frame, [prev.f, next.f], [prev.x, next.x], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  const y = interpolate(frame, [prev.f, next.f], [prev.y, next.y], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  return {x, y, visible: prev.v};
};

// Zoom keyframes based on verified frame content
const getZoom = (frame: number): {x: number; y: number; scale: number} | undefined => {
  // Search bar typing zoom
  if (frame >= 100 && frame < 145) {
    const s = interpolate(frame, [100, 110, 135, 145], [1, 1.6, 1.6, 1], {extrapolateRight: "clamp", extrapolateLeft: "clamp"});
    return {x: 880, y: 540, scale: s};
  }
  // Search result first link zoom
  if (frame >= 220 && frame < 260) {
    const s = interpolate(frame, [220, 230, 248, 260], [1, 1.5, 1.5, 1], {extrapolateRight: "clamp", extrapolateLeft: "clamp"});
    return {x: 400, y: 140, scale: s};
  }
  // Hero catchphrase zoom
  if (frame >= 480 && frame < 530) {
    const s = interpolate(frame, [480, 495, 518, 530], [1, 1.3, 1.3, 1], {extrapolateRight: "clamp", extrapolateLeft: "clamp"});
    return {x: 960, y: 350, scale: s};
  }
  // 選ばれる理由 card hover zoom
  if (frame >= 588 && frame < 630) {
    const s = interpolate(frame, [588, 598, 620, 630], [1, 1.35, 1.35, 1], {extrapolateRight: "clamp", extrapolateLeft: "clamp"});
    return {x: 500, y: 650, scale: s};
  }
  // Contact phone number zoom
  if (frame >= 1055 && frame < 1100) {
    const s = interpolate(frame, [1055, 1065, 1088, 1100], [1, 1.6, 1.6, 1], {extrapolateRight: "clamp", extrapolateLeft: "clamp"});
    return {x: 400, y: 200, scale: s};
  }
  // Contact form button zoom
  if (frame >= 1105 && frame < 1145) {
    const s = interpolate(frame, [1105, 1115, 1133, 1145], [1, 1.5, 1.5, 1], {extrapolateRight: "clamp", extrapolateLeft: "clamp"});
    return {x: 1100, y: 200, scale: s};
  }
  return undefined;
};

const RecFrame: React.FC<{recFrame: number; zoom?: {x: number; y: number; scale: number}}> = ({recFrame, zoom}) => {
  const f = Math.min(Math.max(0, recFrame), TOTAL_REC - 1);
  const style: React.CSSProperties = {
    width: 1920, height: 1080, position: "absolute", top: 0, left: 0,
  };
  if (zoom) {
    style.transform = `scale(${zoom.scale})`;
    style.transformOrigin = `${zoom.x}px ${zoom.y}px`;
  }
  return <Img src={staticFile(`frames/f_${String(f).padStart(5, "0")}.png`)} style={style} />;
};

const TextSlide: React.FC<{text: string; sub?: string}> = ({text, sub}) => (
  <AbsoluteFill style={{
    background: "#0a0a0a", justifyContent: "center", alignItems: "center",
    fontFamily: "'Yu Gothic UI', 'Hiragino Sans', sans-serif",
  }}>
    <div style={{textAlign: "center", maxWidth: 1200, padding: "0 80px"}}>
      <div style={{fontSize: 48, fontWeight: 700, color: "#ebebeb", lineHeight: 1.6}}>{text}</div>
      {sub && <div style={{fontSize: 26, color: "#888", marginTop: 16}}>{sub}</div>}
    </div>
  </AbsoluteFill>
);

const CursorSvg: React.FC<{x: number; y: number}> = ({x, y}) => (
  <svg width="32" height="40" viewBox="0 0 28 36" style={{
    position: "absolute", left: x, top: y, zIndex: 9999,
    filter: "drop-shadow(1px 2px 3px rgba(0,0,0,0.5))", pointerEvents: "none",
  }}>
    <path d="M2 1 L2 26 L8 20 L14 32 L18 30 L12 18 L20 18 Z"
      fill="white" stroke="black" strokeWidth="2" strokeLinejoin="round" />
  </svg>
);

export const YoshikawaProposal: React.FC = () => {
  const frame = useCurrentFrame();

  const getRecFrame = (): number => {
    if (frame >= 90 && frame < 190) return frame - 90;               // rec 0-99
    if (frame >= 190 && frame < 365) return 100 + (frame - 190);     // rec 100-274
    if (frame >= 455 && frame < 695) return 175 + (frame - 455);     // rec 175-414 (hero+reasons+service start)
    if (frame >= 695 && frame < 935) return 475 + (frame - 695);     // rec 475-714 (service+vehicles)
    if (frame >= 1025 && frame < 1235) return 775 + (frame - 1025);  // rec 775-984
    return 0;
  };

  const isRec = (frame >= 90 && frame < 190) ||
                (frame >= 190 && frame < 365) ||
                (frame >= 455 && frame < 695) ||
                (frame >= 695 && frame < 935) ||
                (frame >= 1025 && frame < 1235);

  const fade = (start: number, end: number) => {
    const dur = end - start;
    return interpolate(frame, [start, start + 15, end - 15, end], [0, 1, 1, 0], {extrapolateRight: "clamp", extrapolateLeft: "clamp"});
  };

  const cursor = getCursor(frame);
  const zoom = getZoom(frame);

  return (
    <AbsoluteFill style={{background: "#0a0a0a"}}>
      <Audio
        src={staticFile("bgm.mp3")}
        volume={(f) => interpolate(f, [0, 45, TOTAL_FRAMES - 60, TOTAL_FRAMES], [0, 0.22, 0.22, 0], {
          extrapolateLeft: "clamp", extrapolateRight: "clamp",
        })}
      />

      {/* Intro */}
      {frame < 90 && (
        <AbsoluteFill style={{opacity: fade(0, 90)}}>
          <TextSlide text="吉川特装自動車" sub="ホームページのご提案" />
        </AbsoluteFill>
      )}

      {/* Recording with zoom and cursor */}
      {isRec && (
        <AbsoluteFill style={{overflow: "hidden"}}>
          <RecFrame recFrame={getRecFrame()} zoom={zoom} />
          {cursor.visible && <CursorSvg x={cursor.x} y={cursor.y} />}
        </AbsoluteFill>
      )}

      {/* Text 1 */}
      {frame >= 365 && frame < 455 && (
        <AbsoluteFill style={{opacity: fade(365, 455)}}>
          <TextSlide text="新明和認定のプロフェッショナルを、" sub="Webで伝える。" />
        </AbsoluteFill>
      )}

      {/* Text 2 */}
      {frame >= 935 && frame < 1025 && (
        <AbsoluteFill style={{opacity: fade(935, 1025)}}>
          <TextSlide text="お客様からの問い合わせを、" sub="24時間受け付ける。" />
        </AbsoluteFill>
      )}

      {/* Outro */}
      {frame >= 1235 && (
        <AbsoluteFill style={{opacity: fade(1235, TOTAL_FRAMES)}}>
          <TextSlide text="吉川特装自動車" sub="yoshikawa-tokuso.vercel.app" />
        </AbsoluteFill>
      )}
    </AbsoluteFill>
  );
};
