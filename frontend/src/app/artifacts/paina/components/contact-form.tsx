"use client";

import * as React from "react";

type Field = {
  key: "name" | "company" | "email" | "phone" | "message";
  label: string;
  type: "text" | "email" | "tel" | "textarea";
  required?: boolean;
  autoComplete?: string;
};

const FIELDS: Field[] = [
  { key: "name", label: "お名前", type: "text", required: true, autoComplete: "name" },
  { key: "company", label: "会社名", type: "text", autoComplete: "organization" },
  { key: "email", label: "メールアドレス", type: "email", required: true, autoComplete: "email" },
  { key: "phone", label: "電話番号", type: "tel", autoComplete: "tel" },
  { key: "message", label: "ご相談内容", type: "textarea", required: true },
];

const inputCls =
  "font-label w-full rounded-xl border border-[var(--paina-border-strong)] bg-transparent px-4 py-3 text-[15px] text-[var(--paina-fg)] outline-none transition-colors placeholder:text-[var(--paina-faint)] focus:border-[var(--paina-fg)]";

/** 株式会社パイナ ブランドに合わせた問い合わせフォーム。scope=paina-contact。 */
export function ContactForm() {
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

  function set(k: string, v: string) {
    setState((s) => ({ ...s, [k]: v }));
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (loading) return;
    if (!state.name.trim() || !state.message.trim()) {
      setError("お名前とご相談内容は必須です。");
      return;
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(state.email.trim())) {
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
      setError("送信に失敗しました。時間をおいて再度お試しください。");
    } finally {
      setLoading(false);
    }
  }

  if (done) {
    return (
      <div className="rounded-2xl border border-[var(--paina-border-strong)] bg-[var(--paina-bg)] px-8 py-12 text-center">
        <p className="font-serif-jp text-xl text-[var(--paina-fg)]">
          お問い合わせありがとうございます。
        </p>
        <p className="lead mt-4 text-[14px]">
          内容を確認のうえ、担当より折り返しご連絡いたします。
        </p>
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
            {f.label}
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
        {loading ? "送信中…" : "送信する"}
      </button>
    </form>
  );
}
