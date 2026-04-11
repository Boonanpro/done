import {
  AbsoluteFill,
  Audio,
  Easing,
  Img,
  Sequence,
  interpolate,
  staticFile,
  useCurrentFrame,
} from "remotion";

// --- カーソルコンポーネント ---
const Cursor = ({ x, y, visible }: { x: number; y: number; visible: boolean }) => {
  if (!visible) return null;
  return (
    <svg
      style={{
        position: "absolute",
        left: x,
        top: y,
        width: 60,
        height: 60,
        zIndex: 100,
        filter: "drop-shadow(3px 3px 5px rgba(0,0,0,0.4))",
      }}
      viewBox="0 0 320 320"
    >
      <path
        d="M 50 50 L 100 250 L 140 180 L 220 180 Z"
        fill="black"
        stroke="white"
        strokeWidth="10"
        strokeLinejoin="round"
      />
    </svg>
  );
};

// --- テキストオーバーレイコンポーネント ---
const TextOverlay = ({ text, startFrame, duration }: { text: string; startFrame: number; duration: number }) => {
  const frame = useCurrentFrame();

  const opacity = interpolate(
    frame,
    [startFrame, startFrame + 15, startFrame + duration - 15, startFrame + duration],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.bezier(0.25, 0.1, 0.25, 1) }
  );

  if (frame < startFrame || frame > startFrame + duration) return null;

  return (
    <AbsoluteFill style={{ backgroundColor: "#0f172a", opacity, justifyContent: "center", alignItems: "center" }}>
      {text.split("\n").map((line, i) => (
        <h1 key={i} style={{ color: "white", fontSize: 64, fontWeight: "bold", margin: "10px 0", fontFamily: "'Yu Gothic UI', sans-serif" }}>
          {line}
        </h1>
      ))}
    </AbsoluteFill>
  );
};

// --- メインコンポーネント ---
export const YoshikawaProposal = () => {
  const frame = useCurrentFrame();

  // ==========================================
  // 1. ズーム（Scale & Translate Y）の計算
  // ==========================================
  const scale = interpolate(
    frame,
    [
      0, 40, 70,       // Scene1: 検索窓→リンクへズームイン
      80, 110,         // Scene1: HP遷移後ズームアウト
      165, 195,        // Scene2: キャッチコピーズームイン
      240, 269,        // Scene2: ズームアウト
      330,
      390, 420,        // Scene4: サービス一覧ズームイン
      490, 520,        // Scene4: ズームアウト
      600,
      645, 675,        // Scene6: 電話番号ズームイン
      720, 749         // Scene6: ズームアウト
    ],
    [
      1, 1, 1.4,
      1.4, 1,
      1, 1.3,
      1.3, 1,
      1,
      1, 1.3,
      1.3, 1,
      1,
      1, 1.5,
      1.5, 1
    ],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.bezier(0.25, 0.1, 0.25, 1) }
  );

  const translateY = interpolate(
    frame,
    [
      0, 40, 70,
      80, 110,
      165, 195,
      240, 269,
      330,
      390, 420,
      490, 520,
      600,
      645, 675,
      720, 749
    ],
    [
      0, 0, 200,
      200, 0,
      0, 100,
      100, 0,
      0,
      0, 0,
      0, 0,
      0,
      0, -150,
      -150, 0
    ],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.bezier(0.25, 0.1, 0.25, 1) }
  );

  // ==========================================
  // 2. カーソルの制御
  // ==========================================
  // Scene1: 検索結果のリンククリック
  const showCursor1 = frame >= 30 && frame <= 65;
  const cursorX1 = interpolate(frame, [30, 50], [1200, 600], { extrapolateRight: "clamp", easing: Easing.bezier(0.25, 0.1, 0.25, 1) });
  const cursorY1 = interpolate(frame, [30, 50], [800, 310], { extrapolateRight: "clamp", easing: Easing.bezier(0.25, 0.1, 0.25, 1) });

  // Scene6: 電話番号クリック
  const showCursor2 = frame >= 630 && frame <= 710;
  const cursorX2 = interpolate(frame, [630, 670], [1200, 960], { extrapolateRight: "clamp", easing: Easing.bezier(0.25, 0.1, 0.25, 1) });
  const cursorY2 = interpolate(frame, [630, 670], [1000, 750], { extrapolateRight: "clamp", easing: Easing.bezier(0.25, 0.1, 0.25, 1) });

  // 現在のフレームに該当する画像
  const frameString = String(Math.floor(frame)).padStart(5, "0");
  const imgSrc = staticFile(`frames/f_${frameString}.png`);

  return (
    <AbsoluteFill style={{ backgroundColor: "black" }}>

      {/* 録画フレームとズーム */}
      <AbsoluteFill
        style={{
          transform: `scale(${scale}) translateY(${translateY}px)`,
          transformOrigin: "center center",
          willChange: "transform",
        }}
      >
        <Img src={imgSrc} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        <Cursor x={cursorX1} y={cursorY1} visible={showCursor1} />
        <Cursor x={cursorX2} y={cursorY2} visible={showCursor2} />
      </AbsoluteFill>

      {/* テキスト挿入 */}
      <TextOverlay text="特装車のトラブル、ネットで探すお客様に選ばれるために。" startFrame={270} duration={60} />
      <TextOverlay text="専門技術と実績を、一目で伝わる形に。" startFrame={540} duration={60} />
      <TextOverlay text={"吉川特装自動車\n新しいWebサイトのご提案"} startFrame={750} duration={90} />

      {/* BGM */}
      <Audio src={staticFile("bgm.mp3")} volume={0.15} />

    </AbsoluteFill>
  );
};
