"use client";

import * as React from "react";
import { Loader2 } from "lucide-react";

const TOOL_URL = "https://salonboard-styleup-done.vercel.app/";

const BASE = "/lp-mocks";
const MOBILE = [`${BASE}/sb-mobile-1.png`, `${BASE}/sb-mobile-2.png`, `${BASE}/sb-mobile-3.png`];
const DESKTOP = [`${BASE}/sb-desktop-1.png`, `${BASE}/sb-desktop-2.png`, `${BASE}/sb-desktop-3.png`];

type Rect = { top: string; left: string; width: string; height: string };

// 画像内の「空の申し込みカード」と「ヒーローのCTAボタン」の位置(パーセント)。
// 画像が幅100%で拡大縮小しても、パネルの縦横比は画像と同じなので比率指定でズレない。
const POS = {
  mobile: {
    heroCta: { top: "28%", left: "17.5%", width: "64%", height: "7.5%" } as Rect,
    form: { top: "60.5%", left: "7%", width: "86%", height: "29%" } as Rect,
  },
  desktop: {
    heroCta: { top: "68.5%", left: "5.8%", width: "36%", height: "11%" } as Rect,
    form: { top: "22%", left: "53.3%", width: "41.5%", height: "62%" } as Rect,
  },
};

function useApply() {
  const [email, setEmail] = React.useState("");
  const [loading, setLoading] = React.useState(false);
  const [done, setDone] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (loading || done) return;

    const normalizedEmail = email.trim();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalizedEmail)) {
      setError("メールアドレスを入力してください。");
      return;
    }

    setError(null);
    setLoading(true);
    try {
      const res = await fetch("/api/v1/inquiries", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scope: "salonboard-monitor",
          name: "モニターLP申込",
          email: normalizedEmail,
          message:
            "スタイルアップ モニター募集LP(SNS広告版)から申し込み。登録後は実ツールで1件試用する導線。",
          source_url:
            typeof window !== "undefined" ? window.location.href : undefined,
        }),
      });
      if (!res.ok) {
        const body = await res.text();
        throw new Error(body || `HTTP ${res.status}`);
      }
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return { email, setEmail, loading, done, error, submit };
}

type ApplyState = ReturnType<typeof useApply>;

/** 空のカード枠に重ねる、メール入力欄＋送信ボタン。送信後はお礼＋試用導線に切り替わる。 */
function ApplyOverlay({
  rect,
  state,
  formId,
}: {
  rect: Rect;
  state: ApplyState;
  formId: string;
}) {
  const { email, setEmail, loading, done, error, submit } = state;

  if (done) {
    return (
      <div className="absolute" style={rect}>
        <div
          aria-live="polite"
          className="flex h-full flex-col items-center justify-center gap-2 px-[6%] text-center"
        >
          <p className="text-[clamp(14px,3.6vw,18px)] font-bold text-[#13243B]">
            送信しました。まずは1件、無料で試せます。
          </p>
          <p className="text-[clamp(11px,2.8vw,13px)] leading-relaxed text-[#6b6258]">
            続けたい方には、あとから月500円のモニター利用をご案内します。
          </p>
          <a
            href={TOOL_URL}
            className="mt-1 inline-flex min-h-11 items-center justify-center rounded-xl bg-[#E8557F] px-6 text-[clamp(13px,3.4vw,16px)] font-bold text-white shadow-lg shadow-[#E8557F]/30 transition hover:brightness-105 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#13243B]"
          >
            今すぐ1件ためす
          </a>
        </div>
      </div>
    );
  }

  return (
    <form
      id={formId}
      onSubmit={submit}
      className="absolute flex flex-col justify-center gap-[3.5%] px-[5%]"
      style={rect}
    >
      <label className="sr-only" htmlFor={`${formId}-email`}>
        メールアドレス
      </label>
      <input
        id={`${formId}-email`}
        type="email"
        inputMode="email"
        autoComplete="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        disabled={loading}
        placeholder="メールアドレスを入力"
        className="h-[clamp(44px,17%,56px)] w-full rounded-xl border border-[#d9d3ca] bg-white px-4 text-[clamp(13px,3.4vw,16px)] text-[#13243B] shadow-[inset_0_1px_2px_rgba(0,0,0,0.04)] outline-none placeholder:text-[#aaa49b] focus:border-[#E8557F] focus:ring-2 focus:ring-[#E8557F]/25"
      />
      <button
        type="submit"
        disabled={loading}
        aria-label="無料で1件ためす（メールで申し込む）"
        className="flex h-[clamp(46px,18%,58px)] w-full items-center justify-center rounded-xl bg-[#E8557F] text-[clamp(14px,3.6vw,17px)] font-bold text-white shadow-lg shadow-[#E8557F]/30 transition hover:brightness-105 active:scale-[0.99] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#13243B] disabled:cursor-not-allowed disabled:opacity-70"
      >
        {loading ? (
          <>
            <Loader2 className="mr-2 h-5 w-5 animate-spin" />
            送信中...
          </>
        ) : (
          "無料で1件ためす"
        )}
      </button>
      {error && (
        <p className="rounded-md bg-white/95 px-2 py-1 text-center text-xs font-medium text-red-600 shadow">
          {error}
        </p>
      )}
      {!error && (
        <p className="text-center text-[clamp(10px,2.5vw,12px)] text-[#8d857a]">
          入力情報は暗号化して保管します。先着10名・モニター月500円。
        </p>
      )}
    </form>
  );
}

/** ヒーローの焼き込みCTAボタンの上に重ねる、フォームへスクロールする透明ボタン。 */
function CtaOverlay({ rect, targetId }: { rect: Rect; targetId: string }) {
  return (
    <button
      type="button"
      aria-label="申し込みフォームへ移動"
      onClick={() =>
        document
          .getElementById(targetId)
          ?.scrollIntoView({ behavior: "smooth", block: "center" })
      }
      className="absolute rounded-full focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#13243B]"
      style={rect}
    />
  );
}

export default function SalonboardMonitorPage() {
  const state = useApply();

  return (
    <main className="min-h-screen bg-[#FBF8F4] text-[#13243B]">
      <h1 className="sr-only">
        スタイルアップ — 美容師向けサロンボード スタイル投稿支援ツール。写真を選ぶだけで、AIがスタイル名・コメント・ハッシュタグ・項目を自動で下書き。普通5分かかる投稿が約20秒に。先着10名モニター募集（月500円）。
      </h1>

      {/* スマホ用レイアウト */}
      <div className="mx-auto block w-full max-w-[480px] md:hidden">
        <div className="relative">
          <img
            src={MOBILE[0]}
            alt="投稿5分が、たった20秒。写真を選ぶだけでAIがスタイル名・コメント・タグを自動で下書き。"
            className="block h-auto w-full select-none"
            draggable={false}
          />
          <CtaOverlay rect={POS.mobile.heroCta} targetId="apply-mobile" />
        </div>
        <img
          src={MOBILE[1]}
          alt="使い方はかんたん3ステップ。写真をアップロード、AIが項目・コメント・タグを自動生成、確認してそのまま投稿。投稿前に手直しもOK。"
          className="-mt-px block h-auto w-full select-none"
          draggable={false}
        />
        <div className="relative -mt-px">
          <img
            src={MOBILE[2]}
            alt="先着10名 モニター募集。モニター価格 月500円。メールで申し込み。"
            className="block h-auto w-full select-none"
            draggable={false}
          />
          <ApplyOverlay rect={POS.mobile.form} state={state} formId="apply-mobile" />
        </div>
      </div>

      {/* PC用レイアウト */}
      <div className="mx-auto hidden w-full max-w-[1120px] md:block">
        <div className="relative">
          <img
            src={DESKTOP[0]}
            alt="投稿5分が、たった20秒。写真を選ぶだけでAIがスタイル名・コメント・タグを自動で下書き。美容師さんの投稿作業を一気に短縮。"
            className="block h-auto w-full select-none"
            draggable={false}
          />
          <CtaOverlay rect={POS.desktop.heroCta} targetId="apply-desktop" />
        </div>
        <img
          src={DESKTOP[1]}
          alt="使い方はかんたん3ステップ。写真をアップロード、AIが項目・コメント・タグを自動生成、確認してそのまま投稿。AIがつくるもの：スタイル名・メニュー内容・コメント文・ハッシュタグ・カテゴリ。投稿前に手直しもOK。"
          className="-mt-px block h-auto w-full select-none"
          draggable={false}
        />
        <div className="relative -mt-px">
          <img
            src={DESKTOP[2]}
            alt="先着10名 モニター募集。モニター価格 月500円。ホットペッパーによく載せる美容師さんへ。まずは1件、無料で試せます。"
            className="block h-auto w-full select-none"
            draggable={false}
          />
          <ApplyOverlay rect={POS.desktop.form} state={state} formId="apply-desktop" />
        </div>
      </div>
    </main>
  );
}
