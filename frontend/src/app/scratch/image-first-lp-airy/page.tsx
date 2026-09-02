"use client";

/**
 * 画像ファーストLP（自動生成雛形: scripts/lp_image_materialize.py）
 * タイル画像を縦に繋ぎ、検出された操作箇所に実HTMLを重ねる。
 * TODO: 送信先API・ボタンの遷移先を案件に合わせて調整すること。
 */

import { useRef, useState } from "react";

const TILES = [
  {
    "file": "a1.png",
    "width": 1520,
    "height": 2688,
    "buttons": [
      {
        "bbox": [
          69,
          2261,
          1451,
          2469
        ],
        "hue": 20,
        "role": "cta"
      }
    ],
    "inputs": [],
    "alt": "image-first-lp-airy LP"
  },
  {
    "file": "a2.png",
    "width": 1520,
    "height": 2688,
    "buttons": [],
    "inputs": [],
    "alt": "image-first-lp-airy LP"
  },
  {
    "file": "a3.png",
    "width": 1520,
    "height": 2688,
    "buttons": [],
    "inputs": [],
    "alt": "image-first-lp-airy LP"
  },
  {
    "file": "a4.png",
    "width": 1520,
    "height": 2688,
    "buttons": [],
    "inputs": [],
    "alt": "image-first-lp-airy LP"
  },
  {
    "file": "a5.png",
    "width": 1520,
    "height": 2688,
    "buttons": [],
    "inputs": [],
    "alt": "image-first-lp-airy LP"
  },
  {
    "file": "a6.png",
    "width": 1520,
    "height": 2688,
    "buttons": [
      {
        "bbox": [
          90,
          1552,
          1428,
          1796
        ],
        "hue": 144,
        "role": "line"
      },
      {
        "bbox": [
          90,
          1867,
          1427,
          2112
        ],
        "hue": 20,
        "role": "submit"
      }
    ],
    "inputs": [
      {
        "bbox": [
          86,
          1238,
          1435,
          1472
        ]
      }
    ],
    "alt": "image-first-lp-airy LP"
  }
];

function pct(v: number, base: number) {
  return `${(v / base) * 100}%`;
}

export default function ImageFirstLp() {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<"idle" | "sending" | "done" | "error" | "invalid">("idle");
  const inputRef = useRef<HTMLInputElement>(null);

  const scrollToForm = () => {
    inputRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    setTimeout(() => inputRef.current?.focus(), 500);
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
          scope: "image-first-lp-airy-waitlist", // TODO: 案件のscopeに変更
          name: "LP登録",
          email: value,
          message: `登録: ${value}`,
          source_url: window.location.href,
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      setStatus("done");
    } catch {
      setStatus("error");
    }
  };

  return (
    <main className="min-h-screen" style={{ background: "#f9f3e9" }}>
      <div className="mx-auto w-full max-w-[560px]">
        {TILES.map((tile, ti) => (
          <div key={ti} className="relative">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={`/scratch/image-first-lp-airy/${tile.file}`} alt={tile.alt} className="block w-full" draggable={false} />
            {tile.inputs.map((box, i) => (
              <input
                key={`in-${i}`}
                ref={inputRef}
                type="email"
                value={email}
                onChange={(e) => { setEmail(e.target.value); if (status !== "idle") setStatus("idle"); }}
                placeholder="メールアドレスを入力してください"
                style={{
                  position: "absolute",
                  left: pct(box.bbox[0], tile.width),
                  top: pct(box.bbox[1], tile.height),
                  width: pct(box.bbox[2] - box.bbox[0], tile.width),
                  height: pct(box.bbox[3] - box.bbox[1], tile.height),
                  background: "#fff",
                  border: status === "invalid" ? "2px solid #d43c2a" : "1px solid #ddd",
                  borderRadius: 12,
                  padding: "0 1em",
                  fontSize: "clamp(11px, 3.3vw, 15px)",
                  outline: "none",
                }}
              />
            ))}
            {tile.buttons.map((box, i) => (
              <button
                key={`bt-${i}`}
                type="button"
                aria-label={box.role}
                style={{
                  position: "absolute",
                  left: pct(box.bbox[0], tile.width),
                  top: pct(box.bbox[1], tile.height),
                  width: pct(box.bbox[2] - box.bbox[0], tile.width),
                  height: pct(box.bbox[3] - box.bbox[1], tile.height),
                  background: "transparent",
                  border: "none",
                  borderRadius: 12,
                  cursor: "pointer",
                }}
                className="transition hover:bg-white/15 active:bg-black/10"
                onClick={box.role === "submit" ? submit : scrollToForm} // TODO: lineボタンはLINE友だち追加URLへ
              />
            ))}
          </div>
        ))}
      </div>
      {status === "done" && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-6">
          <div className="max-w-sm rounded-2xl bg-white p-8 text-center shadow-xl">
            <p className="text-lg font-bold">登録を受け付けました</p>
            <button type="button" className="mt-6 rounded-full bg-neutral-800 px-8 py-2.5 text-sm font-bold text-white" onClick={() => { setStatus("idle"); setEmail(""); }}>閉じる</button>
          </div>
        </div>
      )}
    </main>
  );
}
