"use client";

import * as React from "react";
import { useLang } from "./lang-context";

type FieldKey = "name" | "company" | "email" | "phone" | "message";

const LABELS = {
  ja: {
    name: "お名前",
    company: "会社名",
    email: "メールアドレス",
    phone: "電話番号",
    message: "ご相談内容",
    submit: "送信する",
    submitting: "送信中…",
    required: "お名前とご相談内容は必須です。",
    badEmail: "メールアドレスの形式をご確認ください。",
    failed: "送信に失敗しました。時間をおいて再度お試しください。",
    thanksTitle: "お問い合わせありがとうございます。",
    thanksBody: "内容を確認のうえ、折り返しご連絡いたします。",
  },
  en: {
    name: "Name",
    company: "Company",
    email: "Email",
    phone: "Phone",
    message: "Your message",
    submit: "Send",
    submitting: "Sending…",
    required: "Name and message are required.",
    badEmail: "Please check the email format.",
    failed: "Sending failed. Please try again in a moment.",
    thanksTitle: "Thank you for your message.",
    thanksBody: "After reviewing it, I'll get back to you.",
  },
};

const FIELDS: { key: FieldKey; type: string; required?: boolean; autoComplete?: string }[] = [
  { key: "name", type: "text", required: true, autoComplete: "name" },
  { key: "company", type: "text", autoComplete: "organization" },
  { key: "email", type: "email", required: true, autoComplete: "email" },
  { key: "phone", type: "tel", autoComplete: "tel" },
  { key: "message", type: "textarea", required: true },
];

const inputCls =
  "font-label w-full rounded-xl border border-[var(--paina-border-strong)] bg-transparent px-4 py-3 text-[15px] text-[var(--paina-fg)] outline-none transition-colors placeholder:text-[var(--paina-faint)] focus:border-[var(--paina-fg)]";

export function ContactForm() {
  const { lang } = useLang();
  const L = LABELS[lang];
  const [state, setState] = React.useState({
    name: "",
    company: "",
    email: "",
    phone: "",
    message: "",
  });
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [done, setDone] = React.useState(false);

  function set(k: FieldKey, v: string) {
    setState((s) => ({ ...s, [k]: v }));
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (loading) return;
    if (!state.name.trim() || !state.message.trim()) {
      setError(L.required);
      return;
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(state.email.trim())) {
      setError(L.badEmail);
      return;
    }
    setError(null);
    setLoading(true);
    try {
      const res = await fetch("/api/v1/inquiries", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scope: "paina-contact",
          name: state.name.trim(),
          company: state.company.trim() || undefined,
          email: state.email.trim(),
          phone: state.phone.trim() || undefined,
          message: state.message.trim(),
          source_url:
            typeof window !== "undefined" ? window.location.href : undefined,
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      setDone(true);
    } catch {
      setError(L.failed);
    } finally {
      setLoading(false);
    }
  }

  if (done) {
    return (
      <div className="rounded-2xl border border-[var(--paina-border-strong)] bg-[var(--paina-bg)] px-8 py-12 text-center">
        <p className="font-serif-jp text-xl text-[var(--paina-fg)]">
          {L.thanksTitle}
        </p>
        <p className="lead mt-4 text-[14px]">{L.thanksBody}</p>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-6">
      {FIELDS.map((f) => (
        <div key={f.key} className="space-y-2">
          <label
            htmlFor={`cf-${f.key}`}
            className="font-label flex items-center gap-1 text-[12px] tracking-wide text-[var(--paina-muted)]"
          >
            {L[f.key]}
            {f.required && <span className="text-[var(--paina-gold)]">*</span>}
          </label>
          {f.type === "textarea" ? (
            <textarea
              id={`cf-${f.key}`}
              value={state[f.key]}
              onChange={(e) => set(f.key, e.target.value)}
              disabled={loading}
              rows={5}
              className={`${inputCls} min-h-[140px] resize-y`}
            />
          ) : (
            <input
              id={`cf-${f.key}`}
              type={f.type}
              value={state[f.key]}
              onChange={(e) => set(f.key, e.target.value)}
              disabled={loading}
              autoComplete={f.autoComplete}
              className={inputCls}
            />
          )}
        </div>
      ))}

      {error && <p className="text-[13px] text-rose-600">{error}</p>}

      <button
        type="submit"
        disabled={loading}
        className="font-label w-full rounded-full bg-[var(--paina-fg)] px-8 py-3.5 text-[13px] tracking-wide text-[var(--paina-bg)] transition-opacity hover:opacity-90 disabled:opacity-60 sm:w-auto"
      >
        {loading ? L.submitting : L.submit}
      </button>
    </form>
  );
}
