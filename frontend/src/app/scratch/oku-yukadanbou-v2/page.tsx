"use client";

/**
 * 置く床暖房 ドライテストLP v2（画像ファースト方式 / recipes/image-first-lp.md）
 * GPT Image 2 で生成した 9:16 タイル9枚を縦に繋ぎ、操作箇所だけ実HTMLを重ねる。
 * 座標は scripts/lp_image_materialize.py の検出結果（t9の入力欄のみ白領域検出で補完）。
 */

import { useCallback, useEffect, useRef, useState } from "react";

const SCOPE = "oku-yukadanbou-v2-waitlist";
const BASE = "/scratch/oku-yukadanbou-v2";
const TILE_W = 1520;
const TILE_H = 2688;

type Box = [number, number, number, number];

const TILES: {
  file: string;
  alt: string;
  cta?: Box;
  input?: Box;
  submit?: Box;
}[] = [
  {
    file: "t1.png",
    alt: "置く床暖房。コンセントで使える床暖房。工事なし、賃貸でも置くだけ。",
    cta: [104, 2258, 1409, 2531],
  },
  { file: "t2.png", alt: "エアコンの暖房、つらくないですか？風・乾燥・運転音のつらさ。" },
  { file: "t3.png", alt: "工事なし。置いて、挿すだけ。床に広げて家庭用コンセントへ。" },
  { file: "t4.png", alt: "室温18℃でも体感23℃。体感温度は室温と床温のおよそ中間。" },
  { file: "t5.png", alt: "6畳の約80%をこれ1枚で。主暖房の目安は床面積の70%以上。" },
  { file: "t6.png", alt: "床の温度は30℃を超えません。26・28・30℃の3段階、PTCヒーター。" },
  { file: "t7.png", alt: "夏は重ねてしまえる。2枚に分かれて連結、とても薄い。" },
  { file: "t8.png", alt: "仕様。350×230cm、2枚分割・連結式、26/28/30℃、約1000W、家庭用コンセント1口。" },
  {
    file: "t9.png",
    alt: "発売のお知らせをいちばん先に。登録は無料、メールアドレスだけで完了。",
    input: [109, 1346, 1410, 1598],
    submit: [104, 1670, 1413, 1944],
  },
];

function pct(v: number, base: number) {
  return `${(v / base) * 100}%`;
}

function boxStyle(box: Box): React.CSSProperties {
  return {
    position: "absolute",
    left: pct(box[0], TILE_W),
    top: pct(box[1], TILE_H),
    width: pct(box[2] - box[0], TILE_W),
    height: pct(box[3] - box[1], TILE_H),
  };
}

export default function OkuYukadanbouV2() {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<
    "idle" | "sending" | "done" | "error" | "invalid"
  >("idle");
  const [showBar, setShowBar] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const formRef = useRef<HTMLDivElement>(null);

  // 追従CTA: 1画面ぶんスクロールしたら出す。フォームが見えている間は出さない。
  useEffect(() => {
    const onScroll = () => {
      const scrolled = window.scrollY > window.innerHeight * 0.9;
      const rect = formRef.current?.getBoundingClientRect();
      const formVisible = !!rect && rect.top < window.innerHeight && rect.bottom > 0;
      setShowBar(scrolled && !formVisible);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
    };
  }, []);

  const scrollToForm = useCallback(() => {
    formRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    window.setTimeout(() => inputRef.current?.focus({ preventScroll: true }), 600);
  }, []);

  const submit = useCallback(async () => {
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
          message: `置く床暖房 先行登録: ${value}`,
          source_url: window.location.href,
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      setStatus("done");
    } catch {
      setStatus("error");
    }
  }, [email]);

  return (
    <main className="min-h-screen" style={{ background: "#faf3e9" }}>
      <div className="mx-auto w-full max-w-[560px]">
        {TILES.map((tile) => (
          <div key={tile.file} className="relative" ref={tile.input ? formRef : undefined}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={`${BASE}/${tile.file}`}
              alt={tile.alt}
              width={TILE_W}
              height={TILE_H}
              className="block w-full"
              draggable={false}
            />

            {tile.cta && (
              <button
                type="button"
                onClick={scrollToForm}
                aria-label="無料で先行登録する"
                style={{ ...boxStyle(tile.cta), background: "transparent", border: "none", borderRadius: "1.6vw", cursor: "pointer" }}
                className="transition active:brightness-90"
              />
            )}

            {tile.input && (
              <>
                <input
                  ref={inputRef}
                  type="email"
                  inputMode="email"
                  autoComplete="email"
                  value={email}
                  onChange={(e) => {
                    setEmail(e.target.value);
                    if (status !== "idle" && status !== "sending") setStatus("idle");
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") submit();
                  }}
                  placeholder="メールアドレスを入力"
                  aria-label="メールアドレス"
                  style={{
                    ...boxStyle(tile.input),
                    background: "#ffffff",
                    border: status === "invalid" ? "2px solid #c0341a" : "1px solid #e6ded1",
                    borderRadius: "2.2vw",
                    padding: "0 4.5%",
                    color: "#2b2622",
                    fontSize: "clamp(13px, 3.6vw, 18px)",
                    outline: "none",
                  }}
                />
                {(status === "invalid" || status === "error") && tile.submit && (
                  <div
                    style={{
                      position: "absolute",
                      left: pct(tile.input[0], TILE_W),
                      top: pct(tile.submit[3] + 24, TILE_H),
                      width: pct(tile.input[2] - tile.input[0], TILE_W),
                      background: "#c0341a",
                      color: "#fff",
                      borderRadius: "1.4vw",
                      padding: "1.6% 3%",
                      fontSize: "clamp(11px, 3vw, 15px)",
                      lineHeight: 1.5,
                    }}
                  >
                    {status === "invalid"
                      ? "メールアドレスの形式をご確認ください。"
                      : "送信できませんでした。時間をおいて、もう一度お試しください。"}
                  </div>
                )}
              </>
            )}

            {tile.submit && (
              <button
                type="button"
                onClick={submit}
                disabled={status === "sending"}
                aria-label="無料で先行登録する"
                style={{
                  ...boxStyle(tile.submit),
                  background: status === "sending" ? "#d0531a" : "transparent",
                  border: "none",
                  borderRadius: "2.2vw",
                  cursor: status === "sending" ? "wait" : "pointer",
                  color: "#fff",
                  fontSize: "clamp(13px, 3.6vw, 18px)",
                  fontWeight: 700,
                }}
                className="transition active:brightness-90"
              >
                {status === "sending" ? "送信中..." : ""}
              </button>
            )}
          </div>
        ))}

        <footer style={{ background: "#faf3e9", color: "#7d7469" }} className="px-6 pb-10 pt-2 text-center text-[11px] leading-relaxed">
          <p>置く床暖房は現在開発中の製品です。仕様・発売時期・価格は変更になる場合があります。</p>
          <p>暖まり方は住まいの断熱性能や気候によって変わります。</p>
          <p className="mt-2">ご登録いただいたメールアドレスは、本製品のご案内以外には使用しません。</p>
        </footer>
      </div>

      {/* 追従CTA（不透明帯。背後の描き込み文字と被らせない） */}
      <div
        aria-hidden={!showBar}
        style={{
          position: "fixed",
          left: 0,
          right: 0,
          bottom: 0,
          zIndex: 40,
          background: "rgba(250,243,233,0.97)",
          borderTop: "1px solid #e6ded1",
          transform: showBar ? "translateY(0)" : "translateY(120%)",
          transition: "transform .28s ease",
          padding: "10px 16px calc(10px + env(safe-area-inset-bottom))",
        }}
      >
        <div className="mx-auto w-full max-w-[520px]">
          <button
            type="button"
            onClick={scrollToForm}
            tabIndex={showBar ? 0 : -1}
            className="w-full rounded-xl py-3.5 text-base font-bold text-white transition active:brightness-90"
            style={{ background: "#d0531a" }}
          >
            無料で先行登録する
          </button>
        </div>
      </div>

      {status === "done" && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-6" style={{ background: "rgba(43,38,34,0.45)" }}>
          <div className="w-full max-w-sm rounded-2xl bg-white p-8 text-center shadow-xl">
            <p className="text-lg font-bold" style={{ color: "#2b2622" }}>
              先行登録を受け付けました
            </p>
            <p className="mt-3 text-sm leading-relaxed" style={{ color: "#7d7469" }}>
              発売のご案内は、ご登録のメールアドレスへお届けします。
            </p>
            <button
              type="button"
              className="mt-6 w-full rounded-xl py-3 text-sm font-bold text-white"
              style={{ background: "#d0531a" }}
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
    </main>
  );
}
