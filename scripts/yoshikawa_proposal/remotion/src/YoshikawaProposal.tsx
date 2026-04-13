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

const TOTAL_REC = 1022;
const TOTAL = 1382;

// Timeline:
// 0-89:       Intro text
// 90-509:     Rec 0-419 (HP top → 選ばれる理由 → サービス → 対応車種)
// 510-599:    Text 1 "新明和認定のプロフェッショナルを、Webで伝える。"
// 600-1021:   Rec 420-841 (お問い合わせクリック → フォーム入力)
// 1022-1111:  Text 2 "お客様からの問い合わせを、24時間受け付ける。"
// 1112-1291:  Rec 842-1021 (フォーム後半 → 送信)
// 1292-1381:  Outro

const recToGlobal = (rf: number): number => {
  if (rf < 420) return 90 + rf;
  if (rf < 842) return 180 + rf;     // +90 for intro, +90 for text1
  return 270 + rf;                    // +90 for intro, +90 for text1, +90 for text2
};

const getRecFrame = (frame: number): number | null => {
  if (frame >= 90 && frame < 510) return frame - 90;
  if (frame >= 600 && frame < 1022) return 420 + (frame - 600);
  if (frame >= 1112 && frame < 1292) return 842 + (frame - 1112);
  return null;
};

// Events from recording
const CLICK_EVENTS = [440, 555, 615, 657, 726, 813, 848, 932];
const TYPE_RANGES = [
  [560, 590], [620, 632], [662, 701], [731, 788], [853, 907],
];

const TextSlide: React.FC<{ text: string; sub?: string }> = ({ text, sub }) => (
  <AbsoluteFill style={{
    background: "#0f172a", justifyContent: "center", alignItems: "center",
    fontFamily: "'Yu Gothic UI', 'Hiragino Sans', sans-serif",
  }}>
    <div style={{ textAlign: "center", maxWidth: 1200, padding: "0 80px" }}>
      <div style={{ fontSize: 52, fontWeight: 700, color: "#ebebeb", lineHeight: 1.6, whiteSpace: "pre-line" }}>{text}</div>
      {sub && <div style={{ fontSize: 24, color: "#999", marginTop: 20 }}>{sub}</div>}
    </div>
  </AbsoluteFill>
);

export const YoshikawaProposal: React.FC = () => {
  const frame = useCurrentFrame();
  const recFrame = getRecFrame(frame);
  const showRec = recFrame !== null;

  const fade = (start: number, end: number) =>
    interpolate(frame, [start, start + 12, end - 12, end], [0, 1, 1, 0], {
      extrapolateRight: "clamp", extrapolateLeft: "clamp",
    });

  const clampedRec = showRec ? Math.min(Math.max(0, recFrame!), TOTAL_REC - 1) : 0;
  const padded = String(clampedRec).padStart(5, "0");

  return (
    <AbsoluteFill style={{ background: "#0a0a0a" }}>
      {/* BGM */}
      <Audio
        src={staticFile("bgm.mp3")}
        volume={(f) => interpolate(f, [0, 60, TOTAL - 60, TOTAL], [0, 0.15, 0.15, 0], {
          extrapolateLeft: "clamp", extrapolateRight: "clamp",
        })}
      />

      {/* Intro */}
      {frame < 90 && (
        <AbsoluteFill style={{ opacity: fade(0, 90) }}>
          <TextSlide text="吉川特装自動車" sub="ホームページのご提案" />
        </AbsoluteFill>
      )}

      {/* Recording */}
      {showRec && (
        <AbsoluteFill>
          <Img src={staticFile(`frames/f_${padded}.png`)} style={{ width: 1920, height: 1080 }} />
        </AbsoluteFill>
      )}

      {/* Text 1 */}
      {frame >= 510 && frame < 600 && (
        <AbsoluteFill style={{ opacity: fade(510, 600) }}>
          <TextSlide text={"新明和認定のプロフェッショナルを、\nWebで伝える。"} />
        </AbsoluteFill>
      )}

      {/* Text 2 */}
      {frame >= 1022 && frame < 1112 && (
        <AbsoluteFill style={{ opacity: fade(1022, 1112) }}>
          <TextSlide text={"お客様からの問い合わせを、\n24時間受け付ける。"} />
        </AbsoluteFill>
      )}

      {/* Outro */}
      {frame >= 1292 && (
        <AbsoluteFill style={{ opacity: fade(1292, TOTAL) }}>
          <TextSlide text="吉川特装自動車" sub="yoshikawa-tokuso.vercel.app" />
        </AbsoluteFill>
      )}

      {/* Click SE */}
      {CLICK_EVENTS.map((rf, i) => (
        <Sequence key={`click-${i}`} from={recToGlobal(rf)} durationInFrames={15}>
          <Audio src={staticFile("click.mp3")} volume={0.5} />
        </Sequence>
      ))}

      {/* Typing SE */}
      {TYPE_RANGES.map(([start, end], i) => (
        <Sequence key={`type-${i}`} from={recToGlobal(start)} durationInFrames={end - start}>
          <Audio src={staticFile("typing.mp3")} volume={0.3} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};
