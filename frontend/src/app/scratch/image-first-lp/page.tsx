"use client";

/**
 * 画像ファーストLP 試作 v2（3タイル繋ぎ合わせ版）
 * GPT Image 2 (Higgsfield経由) で 9:16 の画面を3枚生成して縦に繋ぎ、
 * 操作が必要な箇所（CTA・メール入力・送信・LINE）だけを実HTMLで重ねる。
 * - t1: ヒーロー+悩み（CTAボタンは「再生成→変更領域だけ合成」で文言差し替え済み）
 * - t2: 製品説明+80%カバー+体感比較
 * - t3: 仕様+登録フォーム+FAQ+最終CTA
 * 各タイルは 1520x2688。座標は色検出で特定したピクセル値を%に変換して配置。
 */

import { useRef, useState } from "react";

const TILE_W = 1520;
const TILE_H = 2688;

function box(x0: number, y0: number, x1: number, y1: number) {
  return {
    left: `${(x0 / TILE_W) * 100}%`,
    top: `${(y0 / TILE_H) * 100}%`,
    width: `${((x1 - x0) / TILE_W) * 100}%`,
    height: `${((y1 - y0) / TILE_H) * 100}%`,
  } as const;
}

// タイル1（ヒーロー面）
const T1_CTA = box(50, 1615, 1465, 1830);
// タイル3（登録面）
const T3_EMAIL = box(680, 1448, 1400, 1538);
const T3_LINE = box(679, 1545, 1401, 1651);
const T3_SUBMIT = box(659, 1666, 1427, 1781);
const T3_BOTTOM_CTA = box(67, 2481, 1067, 2606);

export default function ImageFirstLpPage() {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<
    "idle" | "sending" | "done" | "error" | "invalid"
  >("idle");
  const [showBoxes, setShowBoxes] = useState(false);
  const [lineNote, setLineNote] = useState(false);
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
          scope: "oku-yukadanbou-waitlist",
          name: "先行登録（画像ファーストLP試作v2）",
          email: value,
          message: `先行登録希望: ${value}（scratch/image-first-lp v2 からの送信テスト）`,
          source_url: window.location.href,
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      setStatus("done");
    } catch {
      setStatus("error");
    }
  };

  const hotspotBase: React.CSSProperties = {
    position: "absolute",
    cursor: "pointer",
    background: "transparent",
    border: showBoxes ? "2px dashed rgba(220,40,40,0.8)" : "none",
    borderRadius: 12,
    padding: 0,
  };

  return (
    <main className="min-h-screen bg-[#f6f1e7]">
      <div className="mx-auto w-full max-w-[560px]">
        {/* ─ タイル1: ヒーロー + 悩み ─ */}
        <div className="relative">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/scratch/image-first-lp/t1.png"
            alt="置く床暖房 — コンセントで使える床暖房。工事なし・賃貸OK。無料で先行登録受付中"
            className="block w-full"
            draggable={false}
          />
          <button
            type="button"
            aria-label="先行登録フォームへ移動"
            style={{ ...hotspotBase, ...T1_CTA }}
            className="transition hover:bg-white/15 active:bg-black/10"
            onClick={scrollToForm}
          />
        </div>

        {/* ─ タイル2: 製品説明 + 根拠 ─ */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src="/scratch/image-first-lp/t2.png"
          alt="置くだけで使える床暖房。6畳間で床の約80%をカバー。体感23℃の快適さ"
          className="block w-full"
          draggable={false}
        />

        {/* ─ タイル3: 仕様 + 登録フォーム + FAQ ─ */}
        <div className="relative">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/scratch/image-first-lp/t3.png"
            alt="仕様と先行登録。メールアドレス・LINEで先行案内を受け取る"
            className="block w-full"
            draggable={false}
          />

          {/* メール入力欄: 描き込みの上に実inputを不透明で重ねる */}
          <input
            ref={inputRef}
            type="email"
            value={email}
            onChange={(e) => {
              setEmail(e.target.value);
              if (status === "invalid" || status === "error") setStatus("idle");
            }}
            placeholder="メールアドレスを入力してください"
            style={{
              position: "absolute",
              ...T3_EMAIL,
              background: "#ffffff",
              border:
                status === "invalid"
                  ? "2px solid #d43c2a"
                  : "1px solid #e2dccf",
              borderRadius: 12,
              paddingLeft: "1em",
              paddingRight: "1em",
              fontSize: "clamp(11px, 3.3vw, 15px)",
              color: "#3a332b",
              outline: "none",
            }}
          />

          <button
            type="button"
            aria-label="LINEで受け取る"
            style={{ ...hotspotBase, ...T3_LINE }}
            className="transition hover:bg-white/15 active:bg-black/10"
            onClick={() => setLineNote(true)}
          />

          <button
            type="button"
            aria-label="先行登録して、開発を後押しする"
            disabled={status === "sending"}
            style={{ ...hotspotBase, ...T3_SUBMIT }}
            className="transition hover:bg-white/15 active:bg-black/10"
            onClick={submit}
          />

          <button
            type="button"
            aria-label="先行登録フォームへ移動"
            style={{ ...hotspotBase, ...T3_BOTTOM_CTA }}
            className="transition hover:bg-white/15 active:bg-black/10"
            onClick={scrollToForm}
          />

          {/* 送信中/エラー表示（送信ボタン直下・不透明の帯） */}
          {(status === "invalid" ||
            status === "error" ||
            status === "sending") && (
            <p
              style={{
                position: "absolute",
                left: T3_SUBMIT.left,
                top: `${((1790 / TILE_H) * 100).toFixed(3)}%`,
                width: T3_SUBMIT.width,
                fontSize: "clamp(10px, 2.8vw, 13px)",
                padding: "0.5em 0.9em",
                borderRadius: 8,
                boxShadow: "0 2px 8px rgba(0,0,0,0.12)",
                zIndex: 10,
              }}
              className={
                status === "sending"
                  ? "bg-white text-neutral-600"
                  : "bg-[#fdeeec] text-red-700"
              }
            >
              {status === "sending" && "送信中…"}
              {status === "invalid" && "メールアドレスの形式を確認してください"}
              {status === "error" &&
                "送信に失敗しました。時間をおいて再度お試しください"}
            </p>
          )}
        </div>
      </div>

      {/* 送信完了モーダル */}
      {status === "done" && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-6">
          <div className="max-w-sm rounded-2xl bg-white p-8 text-center shadow-xl">
            <p className="text-lg font-bold text-[#3a332b]">
              先行登録を受け付けました
            </p>
            <p className="mt-3 text-sm text-neutral-600">
              発売時の特別価格のご案内をお送りします。
            </p>
            <button
              type="button"
              className="mt-6 rounded-full bg-[#e06a1f] px-8 py-2.5 text-sm font-bold text-white transition hover:brightness-110"
              onClick={() => {
                setStatus("idle");
                setEmail("");
              }}
            >
              閉じる
            </button>
          </div>
        </div>
      )}

      {/* LINE未接続の注記 */}
      {lineNote && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-6">
          <div className="max-w-sm rounded-2xl bg-white p-8 text-center shadow-xl">
            <p className="text-sm text-neutral-700">
              LINE連携は試作のため未接続です。
              <br />
              本番ではLINE友だち追加リンクを開きます。
            </p>
            <button
              type="button"
              className="mt-6 rounded-full bg-neutral-800 px-8 py-2.5 text-sm font-bold text-white"
              onClick={() => setLineNote(false)}
            >
              閉じる
            </button>
          </div>
        </div>
      )}

      {/* 検証用: ホットスポット枠の表示切替 */}
      <button
        type="button"
        className="fixed bottom-3 right-3 z-40 rounded-full bg-black/60 px-3 py-1.5 text-xs text-white"
        onClick={() => setShowBoxes((v) => !v)}
      >
        {showBoxes ? "枠を隠す" : "操作領域を表示"}
      </button>
    </main>
  );
}
