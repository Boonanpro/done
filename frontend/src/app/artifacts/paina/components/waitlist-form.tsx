"use client";

import * as React from "react";
import { useLang } from "./lang-context";

const L = {
  ja: {
    namePlaceholder: "お名前（任意）",
    emailPlaceholder: "メールアドレス",
    submit: "登録する",
    submitting: "送信中…",
    badEmail: "メールアドレスの形式をご確認ください。",
    failed: "送信に失敗しました。時間をおいて再度お試しください。",
    note: "提供開始のご案内のみにご利用します。営業メールは送りません。",
    thanksTitle: "ご登録ありがとうございます。",
    thanksBody:
      "Done の提供開始が決まりましたら、このメールアドレスへ最初にご案内します。",
  },
  en: {
    namePlaceholder: "Name (optional)",
    emailPlaceholder: "Email address",
    submit: "Register",
    submitting: "Sending…",
    badEmail: "Please check the email format.",
    failed: "Sending failed. Please try again in a moment.",
    note: "Used only to announce the launch. No marketing emails.",
    thanksTitle: "Thank you for registering.",
    thanksBody: "When Done's launch is set, this address will be the first to hear.",
  },
};

/**
 * Done ウェイティングリスト登録フォーム（メールのみ）。
 * /api/v1/inquiries を scope=paina-waitlist で利用し、
 * 送信内容は shub6923@gmail.com へ通知される。
 */
export function WaitlistForm({ tone = "light" }: { tone?: "light" | "dark" }) {
  const { lang } = useLang();
  const t = L[lang];
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
      setError(t.badEmail);
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
      setError(t.failed);
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
          {t.thanksTitle}
        </p>
        <p className={`mt-3 text-[14px] leading-[2] ${noteCls}`}>{t.thanksBody}</p>
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
          placeholder={t.namePlaceholder}
          disabled={loading}
          className={`font-label w-full rounded-full border bg-transparent px-5 py-3 text-[14px] outline-none transition-colors sm:max-w-[180px] ${inputCls}`}
        />
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder={t.emailPlaceholder}
          disabled={loading}
          required
          className={`font-label w-full flex-1 rounded-full border bg-transparent px-5 py-3 text-[14px] outline-none transition-colors ${inputCls}`}
        />
        <button
          type="submit"
          disabled={loading}
          className={`font-label whitespace-nowrap rounded-full px-7 py-3 text-[13px] tracking-wide transition-opacity hover:opacity-90 disabled:opacity-60 ${btnCls}`}
        >
          {loading ? t.submitting : t.submit}
        </button>
      </div>
      {error && <p className="mt-3 text-[13px] text-rose-400">{error}</p>}
      <p className={`mt-3 text-[12px] ${noteCls}`}>{t.note}</p>
    </form>
  );
}
