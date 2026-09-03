"use client";

/**
 * 窓に貼る透明断熱シート（冬用）ドライテストLP
 * T0 画像ファースト方式（recipes/image-first-lp.md）。
 * GPT Image 2 で生成した 9:16 タイルを縦に繋ぎ、操作箇所だけ実HTMLを重ねている。
 * 座標は各タイル画像の実寸(1520x2688)基準。%指定なので拡大縮小に追従する。
 */

import { useRef, useState } from "react";

const SCOPE = "mado-dannetsu-waitlist";
const PREFIX = "/scratch/mado-dannetsu";

type Tile = {
  file: string;
  width: number;
  height: number;
  alt: string;
  buttons?: { bbox: [number, number, number, number]; role: "cta" | "submit" }[];
  inputs?: { bbox: [number, number, number, number] }[];
};

const TILES: Tile[] = [
  {
    file: "t1.png",
    width: 1520,
    height: 2688,
    alt: "窓の冷気を、貼るだけで止める。窓に貼る、透明断熱シート（冬用）。賃貸OK・工事不要・電気代ゼロ",
    buttons: [{ bbox: [102, 2296, 1416, 2492], role: "cta" }],
  },
  {
    file: "t2.png",
    width: 1520,
    height: 2688,
    alt: "暖房をつけても、窓際だけ、寒い。部屋の熱は、その多くが窓から逃げていきます",
  },
  {
    file: "t3.png",
    width: 1520,
    height: 2688,
    alt: "窓が、そのまま断熱材になる。透明なシートを窓の内側に一枚貼ると、空気の層が冷気をさえぎります",
  },
  {
    file: "t4.png",
    width: 1520,
    height: 2688,
    alt: "窓ぎわの冷気を約40%カット。同じ暖房設定でも、窓ぎわの体感が変わります",
  },
  {
    file: "t5.png",
    width: 1520,
    height: 2688,
    alt: "透明度92%。景色は、そのまま。白くくもるプチプチとは違い、外の景色も部屋の明るさも変わりません",
  },
  {
    file: "t6.png",
    width: 1520,
    height: 2688,
    alt: "水だけで貼れて、跡は残らない。ハサミで切って霧吹きの水で貼るだけ。賃貸でも使えます",
  },
  {
    file: "t7.png",
    width: 1520,
    height: 2688,
    alt: "結露が減って、電気代はゼロ。ガラスが冷えにくくなるので朝の結露やカビも減ります",
  },
  {
    file: "t8.png",
    width: 1520,
    height: 2688,
    alt: "想定価格3,980円。掃き出し窓2枚分（1セット）。1枚90cm×180cm、厚み約1.5mm、透明度92%、水貼り",
  },
  {
    file: "t9.png",
    width: 1520,
    height: 2688,
    alt: "発売の日を、いちばん先に。メールアドレスを登録すると発売のご案内を優先してお送りします",
    inputs: [{ bbox: [95, 1309, 1425, 1599] }],
    buttons: [{ bbox: [94, 1696, 1424, 1990], role: "submit" }],
  },
];

function pct(v: number, base: number) {
  return `${(v / base) * 100}%`;
}

export default function MadoDannetsuLp() {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<
    "idle" | "sending" | "done" | "error" | "invalid"
  >("idle");
  const [showBoxes, setShowBoxes] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const scrollToForm = () => {
    inputRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    window.setTimeout(() => inputRef.current?.focus(), 600);
  };

  const submit = async () => {
    const value = email.trim();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) {
      setStatus("invalid");
      inputRef.current?.focus();
      return;
    }
    setStatus("sending");
    try {
      const res = await fetch("/api/v1/inquiries", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scope: SCOPE,
          name: "先行登録",
          email: value,
          message: `窓に貼る透明断熱シート（冬用）先行登録: ${value}`,
          source_url: window.location.href,
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      setStatus("done");
    } catch {
      setStatus("error");
    }
  };

  const boxStyle = (
    bbox: [number, number, number, number],
    tile: Tile,
  ): React.CSSProperties => ({
    position: "absolute",
    left: pct(bbox[0], tile.width),
    top: pct(bbox[1], tile.height),
    width: pct(bbox[2] - bbox[0], tile.width),
    height: pct(bbox[3] - bbox[1], tile.height),
  });

  return (
    <main style={{ background: "#F6F2EC", minHeight: "100vh" }}>
      {/* 画像に描かれたプレースホルダと同じ見え方に揃える */}
      <style>{`
        .mado-mail-input::placeholder {
          color: #A9A49B;
          letter-spacing: 0.06em;
        }
      `}</style>
      <div style={{ margin: "0 auto", width: "100%", maxWidth: 560 }}>
        {TILES.map((tile) => (
          <div key={tile.file} style={{ position: "relative" }}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={`${PREFIX}/${tile.file}`}
              alt={tile.alt}
              width={tile.width}
              height={tile.height}
              style={{ display: "block", width: "100%", height: "auto" }}
              draggable={false}
            />

            {tile.inputs?.map((box, i) => (
              <input
                key={`in-${i}`}
                ref={inputRef}
                type="email"
                inputMode="email"
                autoComplete="email"
                aria-label="メールアドレス"
                placeholder="メールアドレス"
                className="mado-mail-input"
                value={email}
                onChange={(e) => {
                  setEmail(e.target.value);
                  if (status !== "idle") setStatus("idle");
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") submit();
                }}
                style={{
                  ...boxStyle(box.bbox, tile),
                  background: "#fff",
                  border:
                    status === "invalid"
                      ? "2px solid #C0392B"
                      : showBoxes
                        ? "2px solid red"
                        : "1px solid #E4E0D8",
                  borderRadius: "3.2%",
                  padding: "0 1.1em",
                  color: "#2A2A28",
                  fontSize: "clamp(13px, 3.6vw, 17px)",
                  letterSpacing: "0.02em",
                  outline: "none",
                }}
              />
            ))}

            {tile.buttons?.map((box, i) => (
              <button
                key={`bt-${i}`}
                type="button"
                aria-label={
                  box.role === "submit" ? "先行登録する（無料）" : "先行登録フォームへ移動"
                }
                onClick={box.role === "submit" ? submit : scrollToForm}
                disabled={box.role === "submit" && status === "sending"}
                style={{
                  ...boxStyle(box.bbox, tile),
                  background: "transparent",
                  border: showBoxes ? "2px solid red" : "none",
                  borderRadius: "3.2%",
                  cursor: "pointer",
                  transition: "background 160ms ease",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = "rgba(255,255,255,0.14)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = "transparent";
                }}
              />
            ))}
          </div>
        ))}

        {/* 送信状態の表示（背後の描き込み文字と被らないよう不透明の帯にする） */}
        {(status === "invalid" || status === "error" || status === "sending") && (
          <div
            role="status"
            style={{
              position: "fixed",
              left: 0,
              right: 0,
              bottom: 0,
              zIndex: 40,
              background: status === "sending" ? "#1F3A5F" : "#C0392B",
              color: "#fff",
              padding: "14px 18px",
              textAlign: "center",
              fontSize: 14,
              lineHeight: 1.5,
            }}
          >
            {status === "sending" && "送信しています…"}
            {status === "invalid" && "メールアドレスの形式をご確認ください。"}
            {status === "error" &&
              "送信できませんでした。時間をおいて、もう一度お試しください。"}
          </div>
        )}
      </div>

      {/* 検証用: 操作領域（赤枠）の表示トグル */}
      <button
        type="button"
        onClick={() => setShowBoxes((v) => !v)}
        style={{
          position: "fixed",
          right: 12,
          bottom: 12,
          zIndex: 50,
          background: "rgba(31,58,95,0.85)",
          color: "#fff",
          border: "none",
          borderRadius: 999,
          padding: "8px 14px",
          fontSize: 12,
          cursor: "pointer",
        }}
      >
        {showBoxes ? "操作領域を隠す" : "操作領域を表示"}
      </button>

      {status === "done" && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 60,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            background: "rgba(30,28,25,0.45)",
            padding: 24,
          }}
        >
          <div
            style={{
              maxWidth: 380,
              width: "100%",
              background: "#F4F1EB",
              borderRadius: 18,
              padding: "36px 28px",
              textAlign: "center",
              boxShadow: "0 24px 60px rgba(0,0,0,0.18)",
            }}
          >
            <p style={{ fontSize: 19, fontWeight: 600, color: "#2A2A28" }}>
              先行登録を受け付けました
            </p>
            <p
              style={{
                marginTop: 14,
                fontSize: 14,
                lineHeight: 1.8,
                color: "#6B6862",
              }}
            >
              発売が決まりましたら、ご登録のメールアドレスへ
              優先してご案内をお送りします。
            </p>
            <button
              type="button"
              onClick={() => {
                setStatus("idle");
                setEmail("");
              }}
              style={{
                marginTop: 26,
                background: "#1F3A5F",
                color: "#fff",
                border: "none",
                borderRadius: 999,
                padding: "12px 34px",
                fontSize: 14,
                cursor: "pointer",
              }}
            >
              閉じる
            </button>
          </div>
        </div>
      )}
    </main>
  );
}
