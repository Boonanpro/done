"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Loader2, CheckCircle2 } from "lucide-react";

type InquiryFormField =
  | "name"
  | "company"
  | "email"
  | "phone"
  | "message";

type InquiryFormProps = {
  scope: string;
  endpoint?: string;
  fields?: InquiryFormField[];
  labels?: Partial<Record<InquiryFormField, string>>;
  submitLabel?: string;
  successMessage?: React.ReactNode;
  className?: string;
};

const DEFAULT_LABELS: Record<InquiryFormField, string> = {
  name: "お名前",
  company: "会社名",
  email: "メールアドレス",
  phone: "電話番号",
  message: "ご用件",
};

export function InquiryForm({
  scope,
  endpoint = "/api/v1/inquiries",
  fields = ["name", "company", "email", "phone", "message"],
  labels,
  submitLabel = "送信する",
  successMessage = "送信ありがとうございました。担当者より折り返しご連絡いたします。",
  className,
}: InquiryFormProps) {
  const [state, setState] = React.useState<Record<InquiryFormField, string>>({
    name: "",
    company: "",
    email: "",
    phone: "",
    message: "",
  });
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [done, setDone] = React.useState(false);

  const resolvedLabels = { ...DEFAULT_LABELS, ...(labels || {}) };

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (loading) return;
    if (!state.name.trim() || !state.message.trim()) {
      setError("お名前とご用件は必須です。");
      return;
    }
    if (fields.includes("email")) {
      if (!state.email.trim()) {
        setError("メールアドレスは必須です。");
        return;
      }
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(state.email.trim())) {
        setError("メールアドレスの形式が正しくありません。");
        return;
      }
    }
    setError(null);
    setLoading(true);
    try {
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scope,
          name: state.name.trim(),
          company: state.company.trim() || undefined,
          email: state.email.trim() || undefined,
          phone: state.phone.trim() || undefined,
          message: state.message.trim(),
          source_url:
            typeof window !== "undefined" ? window.location.href : undefined,
        }),
      });
      if (!res.ok) {
        const body = await res.text();
        throw new Error(body || `HTTP ${res.status}`);
      }
      setDone(true);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  if (done) {
    return (
      <div
        className={cn(
          "rounded-xl border border-border/60 bg-card p-8 text-center space-y-3",
          className,
        )}
      >
        <CheckCircle2 className="h-10 w-10 text-emerald-500 mx-auto" />
        <p className="text-foreground text-base leading-relaxed">
          {successMessage}
        </p>
      </div>
    );
  }

  return (
    <form
      className={cn("space-y-5", className)}
      onSubmit={onSubmit}
      noValidate
    >
      {fields.map((f) => {
        const isMessage = f === "message";
        const required = f === "name" || f === "message" || f === "email";
        return (
          <div key={f} className="space-y-1.5">
            <Label htmlFor={`inquiry-${f}`}>
              {resolvedLabels[f]}
              {required && <span className="text-rose-500 ml-1">*</span>}
            </Label>
            {isMessage ? (
              <textarea
                id={`inquiry-${f}`}
                value={state[f]}
                onChange={(e) =>
                  setState((s) => ({ ...s, [f]: e.target.value }))
                }
                rows={5}
                disabled={loading}
                className="w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs outline-none focus-visible:ring-2 focus-visible:ring-ring/50 resize-y min-h-[120px]"
              />
            ) : (
              <Input
                id={`inquiry-${f}`}
                type={f === "email" ? "email" : f === "phone" ? "tel" : "text"}
                value={state[f]}
                onChange={(e) =>
                  setState((s) => ({ ...s, [f]: e.target.value }))
                }
                disabled={loading}
                autoComplete={
                  f === "name"
                    ? "name"
                    : f === "email"
                      ? "email"
                      : f === "phone"
                        ? "tel"
                        : f === "company"
                          ? "organization"
                          : undefined
                }
              />
            )}
          </div>
        );
      })}
      {error && (
        <div className="text-sm text-rose-500">エラー: {error}</div>
      )}
      <Button type="submit" disabled={loading} className="w-full sm:w-auto">
        {loading ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin mr-2" />
            送信中…
          </>
        ) : (
          submitLabel
        )}
      </Button>
    </form>
  );
}
