"use client";

import * as React from "react";

/**
 * Done ウェイティングリスト登録フォーム（メールのみ）。
 * 既存の /api/v1/inquiries を scope=paina-waitlist で利用し、
 * 送信内容は shub6923@gmail.com へ通知される。
 * tone="dark" は暗色カード上で使う配色。
 */
export function WaitlistForm({ tone = "light" }: { tone?: "light" | "dark" }) {
  const [email, setEmail] = React.useState("");
  const [name, setName] = React.useState("");
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [done, setDone] = React.useState(false);

  const dark = tone === "dark";
  const inputCls = dark
    ? "border-[var(--paina-bg)]/30 placeholder:text-[var(--paina-bg)]/50 text-[var(--paina-bg)] focus:border-[var(--paina-bg)]"
    : "border-[var(--paina-border-strong)] placeholder:text-[var(--paina-faint)] text-[var(--paina-fg)] focus:border-[var(--paina-fg)]";
  const btnCls = dark
    ? "bg-[var(--paina-bg)] text-[var(--paina-fg)]"
    : "bg-[var(--paina-fg)] text-[var(--paina-bg)]";
  const noteCls = dark ? "text-[var(--paina-bg)]/55" : "text-[var(--paina-faint)]";

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (loading) return;
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
      setError("メールアドレスの形式をご確認ください。");
      return;
    }
    setError(null);
    setLoading(true);
    try {
      const res = await fetch("/api/v1/inquiries", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scope: "paina-waitlist",
          name: name.trim() || "（お名前未記入）",
          email: email.trim(),
          message: "Done（ダン）の提供開始の案内を希望します。",
          source_url:
            typeof window !== "undefined" ? window.location.href : undefined,
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      setDone(true);
    } catch {
      setError("送信に失敗しました。時間をおいて再度お試しください。");
    } finally {
      setLoading(false);
    }
  }

  if (done) {
    return (
      <div
        className={
          dark
            ? "rounded-xl border border-[var(--paina-bg)]/25 px-7 py-8"
            : "rounded-xl border border-[var(--paina-border-strong)] bg-[var(--paina-bg)] px-7 py-8"
        }
      >
        <p
          className={`font-serif-jp text-lg ${
            dark ? "text-[var(--paina-bg)]" : "text-[var(--paina-fg)]"
          }`}
        >
          ご登録ありがとうございます。
        </p>
        <p className={`mt-3 text-[14px] leading-[2] ${noteCls}`}>
          Done の提供開始が決まりましたら、このメールアドレスへ最初にご案内します。
        </p>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} className="w-full">
      <div className="flex flex-col gap-3 sm:flex-row">
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="お名前（任意）"
          disabled={loading}
          className={`font-label w-full rounded-full border bg-transparent px-5 py-3 text-[14px] outline-none transition-colors sm:max-w-[180px] ${inputCls}`}
        />
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="メールアドレス"
          disabled={loading}
          required
          className={`font-label w-full flex-1 rounded-full border bg-transparent px-5 py-3 text-[14px] outline-none transition-colors ${inputCls}`}
        />
        <button
          type="submit"
          disabled={loading}
          className={`font-label whitespace-nowrap rounded-full px-7 py-3 text-[13px] tracking-wide transition-opacity hover:opacity-90 disabled:opacity-60 ${btnCls}`}
        >
          {loading ? "送信中…" : "登録する"}
        </button>
      </div>
      {error && <p className="mt-3 text-[13px] text-rose-400">{error}</p>}
      <p className={`mt-3 text-[12px] ${noteCls}`}>
        提供開始のご案内のみにご利用します。営業メールは送りません。
      </p>
    </form>
  );
}
