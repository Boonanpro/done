"use client";

import * as React from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { CheckCircle2, Loader2 } from "lucide-react";

/**
 * 先行登録フォーム。ドライテストの主要指標（登録CPA）と副指標（価格受容性）を同時に取る。
 *
 * 質問は3つに絞る。設問を増やすほど登録率が落ち、CPAの測定精度そのものが下がる。
 * - 今の対処 … 代替品からの乗り換え余地があるか
 * - デスクの脚 … マグネット固定という設計判断が実際に効くか
 * - 出せる金額 … 想定価格9,800円の受容度
 */

const CURRENT_OPTIONS = [
  "とくに何もしていない",
  "電気ひざ掛け・毛布",
  "小型の電気ヒーター",
  "こたつ・足温器",
  "厚着や靴下でしのいでいる",
] as const;

const DESK_OPTIONS = [
  "金属の脚",
  "木や樹脂の脚",
  "わからない",
] as const;

const PRICE_OPTIONS = [
  "5,000円まで",
  "8,000円まで",
  "9,800円なら買う",
  "12,000円でも欲しい",
] as const;

type ChoiceRowProps = {
  label: string;
  options: readonly string[];
  value: string | null;
  onChange: (v: string) => void;
  editId: string;
  hint?: string;
};

function ChoiceRow({
  label,
  options,
  value,
  onChange,
  editId,
  hint,
}: ChoiceRowProps) {
  return (
    <fieldset className="space-y-2.5">
      <legend className="text-sm font-medium text-foreground" data-edit-id={editId}>
        {label}
      </legend>
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      <div className="flex flex-wrap gap-2">
        {options.map((opt) => {
          const active = value === opt;
          return (
            <Button
              key={opt}
              type="button"
              size="sm"
              variant={active ? "default" : "outline"}
              onClick={() => onChange(opt)}
              className={cn(
                "rounded-full px-4 text-sm transition",
                !active && "text-muted-foreground hover:text-foreground",
              )}
              aria-pressed={active}
            >
              {opt}
            </Button>
          );
        })}
      </div>
    </fieldset>
  );
}

export function WaitlistForm({ formId = "waitlist" }: { formId?: string }) {
  const [email, setEmail] = React.useState("");
  const [current, setCurrent] = React.useState<string | null>(null);
  const [desk, setDesk] = React.useState<string | null>(null);
  const [price, setPrice] = React.useState<string | null>(null);
  const [note, setNote] = React.useState("");
  const [loading, setLoading] = React.useState(false);
  const [done, setDone] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (loading || done) return;

    const normalized = email.trim();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalized)) {
      setError("メールアドレスを入力してください。");
      return;
    }

    setError(null);
    setLoading(true);
    try {
      const lines = [
        "足元パネルヒーター 先行登録（ドライテストLP）",
        `今の足元対策: ${current ?? "未回答"}`,
        `デスクの脚: ${desk ?? "未回答"}`,
        `出せる金額: ${price ?? "未回答"}`,
        note.trim() ? `足元の困りごと: ${note.trim()}` : "足元の困りごと: 未記入",
      ];
      const res = await fetch("/api/v1/inquiries", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scope: "ashimoto-heater-waitlist",
          name: "足元パネルヒーター 先行登録",
          email: normalized,
          message: lines.join("\n"),
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

  if (done) {
    return (
      <div
        className="rounded-sm border border-primary/40 bg-card p-8 text-center space-y-3 shadow-[0_2px_24px_-12px_oklch(0.565_0.168_41/0.4)]"
        aria-live="polite"
      >
        <CheckCircle2 className="mx-auto h-10 w-10 text-primary" />
        <p className="font-headline text-xl text-foreground">
          登録ありがとうございます。
        </p>
        <p className="text-sm leading-relaxed text-muted-foreground">
          発売の見通しが立ち次第、いちばんに、このメールアドレスへご連絡します。
          <br />
          先行登録の方には、最初のロットを優先してご案内する予定です。
        </p>
      </div>
    );
  }

  return (
    <form
      id={formId}
      onSubmit={submit}
      className="space-y-6 rounded-sm border border-border bg-card p-6 shadow-[0_2px_24px_-14px_oklch(0.22_0.01_60/0.5)] sm:p-8"
      noValidate
    >
      <div className="space-y-2">
        <Label htmlFor={`${formId}-email`} className="text-foreground">
          メールアドレス
          <span className="ml-1 text-primary">*</span>
        </Label>
        <Input
          id={`${formId}-email`}
          type="email"
          inputMode="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          disabled={loading}
          placeholder="you@example.com"
          className="h-12 text-base"
        />
      </div>

      <ChoiceRow
        label="いまは足元の寒さをどうしていますか？"
        options={CURRENT_OPTIONS}
        value={current}
        onChange={setCurrent}
        editId="ashimoto-form-q-current"
      />
      <ChoiceRow
        label="お使いのデスクの脚は？"
        options={DESK_OPTIONS}
        value={desk}
        onChange={setDesk}
        editId="ashimoto-form-q-desk"
        hint="マグネットで付くかどうかの参考にします。木や樹脂でもスタンドで立てて使えます。"
      />
      <ChoiceRow
        label="いくらまでなら出せますか？"
        options={PRICE_OPTIONS}
        value={price}
        onChange={setPrice}
        editId="ashimoto-form-q-price"
      />

      <div className="space-y-2">
        <Label htmlFor={`${formId}-note`} className="text-foreground">
          足元の寒さで困っていること（任意）
        </Label>
        <textarea
          id={`${formId}-note`}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          disabled={loading}
          rows={3}
          placeholder="例：夕方になると足の指先が痛い／ヒーターの風で顔が乾く"
          className="min-h-[88px] w-full resize-y rounded-md border border-input bg-transparent px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
        />
      </div>

      {error && <p className="text-sm text-destructive">エラー: {error}</p>}

      <Button
        type="submit"
        size="lg"
        disabled={loading}
        className="h-12 w-full text-base font-bold"
        data-edit-id="ashimoto-form-submit"
      >
        {loading ? (
          <>
            <Loader2 className="mr-2 h-5 w-5 animate-spin" />
            送信中…
          </>
        ) : (
          "発売のお知らせを受け取る"
        )}
      </Button>

      <p className="text-center text-xs leading-relaxed text-muted-foreground">
        登録は無料です。この時点でのお支払いは一切ありません。
        <br />
        いただいたメールアドレスは、この製品のご連絡以外には使いません。
      </p>
    </form>
  );
}
