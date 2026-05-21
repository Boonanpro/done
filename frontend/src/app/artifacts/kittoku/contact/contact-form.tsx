"use client";

import * as React from "react";
import { Upload, Send, CheckCircle2, X, AlertCircle } from "lucide-react";

type Status = "idle" | "submitting" | "submitted" | "error";

type ServiceKey =
  | "parts"
  | "repair"
  | "inspection"
  | "bodywork"
  | "retrofit"
  | "lease"
  | "paint"
  | "sales"
  | "tow";

type ServiceDef = {
  key: ServiceKey;
  label: string;
  hint: string;
  /** 専用フィールドの種類 (お問い合わせ内容/お名前/連絡先以外) */
  fields: FieldKey[];
  comingSoon?: boolean;
};

type FieldKey =
  | "kasou"          // 架装番号
  | "seizou"         // 製造番号 / 車台番号
  | "vehicleType"    // 車種・型式
  | "media"          // 修理箇所/状態の画像・動画
  | "preferredDate"  // 希望日程
  | "lastService"   // 前回の点検/整備時期
  | "leasePeriod"    // 希望リース期間
  | "leasePurpose"   // 利用用途
  | "modContent"     // 改造希望内容
  | "towLocation";   // 引取場所

const SERVICES: ServiceDef[] = [
  {
    key: "parts",
    label: "部品注文",
    hint: "純正部品の見積・手配",
    fields: ["kasou", "seizou", "media"],
  },
  {
    key: "repair",
    label: "整備・修理",
    hint: "油圧・電装・架装まわりの不具合",
    fields: ["vehicleType", "seizou", "media"],
  },
  {
    key: "inspection",
    label: "点検",
    hint: "法定点検・特装系の定期点検",
    fields: ["vehicleType", "seizou", "lastService", "preferredDate"],
  },
  {
    key: "bodywork",
    label: "板金",
    hint: "事故修理・凹み補修・溶接",
    fields: ["vehicleType", "media"],
  },
  {
    key: "retrofit",
    label: "架装・改造",
    hint: "パワーゲート架装・載せ替え・改造",
    fields: ["vehicleType", "modContent", "media"],
  },
  {
    key: "lease",
    label: "リース",
    hint: "業務車両のリース相談",
    fields: ["vehicleType", "leasePeriod", "leasePurpose"],
  },
  {
    key: "paint",
    label: "塗装",
    hint: "車体全塗装・部分塗装",
    fields: ["vehicleType", "media"],
    comingSoon: true,
  },
  {
    key: "sales",
    label: "新車・中古車販売",
    hint: "整備済み特装車の販売",
    fields: ["vehicleType", "leasePurpose"],
    comingSoon: true,
  },
  {
    key: "tow",
    label: "レッカー",
    hint: "現場からの牽引・搬送",
    fields: ["vehicleType", "towLocation"],
    comingSoon: true,
  },
];

const FIELD_META: Record<FieldKey, { label: string }> = {
  kasou: { label: "架装番号" },
  seizou: { label: "製造番号 / 車台番号" },
  vehicleType: { label: "車種・型式" },
  media: { label: "状態がわかる画像・動画" },
  preferredDate: { label: "希望日程" },
  lastService: { label: "前回の点検・整備時期" },
  leasePeriod: { label: "希望リース期間" },
  leasePurpose: { label: "利用用途" },
  modContent: { label: "ご希望の改造内容" },
  towLocation: { label: "現在地・引取希望場所" },
};

export function PartsOrderForm() {
  const [serviceKey, setServiceKey] = React.useState<ServiceKey>("parts");
  const [content, setContent] = React.useState("");
  const [contentError, setContentError] = React.useState(false);
  const [name, setName] = React.useState("");
  const [email, setEmail] = React.useState("");
  const [emailError, setEmailError] = React.useState<string | null>(null);
  const [files, setFiles] = React.useState<File[]>([]);
  const [status, setStatus] = React.useState<Status>("idle");
  const [serverError, setServerError] = React.useState<string | null>(null);
  const [customFieldValues, setCustomFieldValues] = React.useState<
    Record<string, string>
  >({});
  const fileInputRef = React.useRef<HTMLInputElement>(null);

  const currentService = SERVICES.find((s) => s.key === serviceKey)!;

  const addFiles = (newFiles: FileList | null) => {
    if (!newFiles) return;
    setFiles((prev) => [...prev, ...Array.from(newFiles)]);
  };
  const removeFile = (i: number) => {
    setFiles((prev) => prev.filter((_, idx) => idx !== i));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    let ok = true;
    if (!content.trim()) {
      setContentError(true);
      ok = false;
    } else {
      setContentError(false);
    }
    if (!email.trim()) {
      setEmailError("メールアドレスを入力してください。");
      ok = false;
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
      setEmailError("メールアドレスの形式が正しくありません。");
      ok = false;
    } else {
      setEmailError(null);
    }
    if (!ok) return;

    setServerError(null);
    setStatus("submitting");

    const customFields: Record<string, string> = {};
    for (const f of currentService.fields) {
      if (f === "media") continue;
      const val = customFieldValues[f];
      if (val && val.trim()) {
        customFields[FIELD_META[f].label] = val.trim();
      }
    }

    try {
      const res = await fetch("/api/kittoku/contact", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          service: currentService.key,
          serviceLabel: currentService.label,
          name: name.trim(),
          email: email.trim(),
          content: content.trim(),
          customFields,
          fileNames: files.map((f) => f.name),
          sourceUrl:
            typeof window !== "undefined" ? window.location.href : undefined,
        }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setServerError(
          (data && (data.error as string)) ||
            "送信に失敗しました。時間をおいて再度お試しください。",
        );
        setStatus("error");
        return;
      }

      setStatus("submitted");
    } catch {
      setServerError(
        "ネットワークエラーが発生しました。通信状況をご確認の上、再度お試しください。",
      );
      setStatus("error");
    }
  };

  if (status === "submitted") {
    return (
      <div className="rounded-sm border border-[var(--yk-gold)]/40 bg-[var(--yk-gold)]/[0.06] p-8 sm:p-10 text-center">
        <CheckCircle2 className="h-12 w-12 text-[var(--yk-gold-dark)] mx-auto mb-4" />
        <div className="font-headline text-xl sm:text-2xl font-black text-[var(--yk-navy)] mb-2">
          送信ありがとうございました
        </div>
        <p className="text-sm text-[var(--yk-steel)] leading-relaxed">
          内容を確認のうえ、 営業時間内に折り返しご連絡いたします。
          <br />
          急ぎの場合は{" "}
          <a
            href="tel:0859-27-4885"
            className="font-mono-data text-[var(--yk-navy)] font-bold underline underline-offset-4"
          >
            0859-27-4885
          </a>
          {" "}までお電話ください。
        </p>
      </div>
    );
  }

  const submitting = status === "submitting";

  return (
    <form onSubmit={handleSubmit} className="space-y-6 sm:space-y-7">
      {/* 問い合わせ種別 (ドロップダウン) */}
      <Field label="問い合わせ種別">
        <select
          value={serviceKey}
          onChange={(e) => setServiceKey(e.target.value as ServiceKey)}
          className="w-full h-11 px-3 rounded-sm border border-border bg-white text-sm focus:outline-none focus:border-[var(--yk-navy)] focus:ring-1 focus:ring-[var(--yk-navy)]/30 transition"
        >
          {SERVICES.map((s) => (
            <option key={s.key} value={s.key}>
              {s.label}
              {s.comingSoon ? " (準備中)" : ""}
            </option>
          ))}
        </select>
        {currentService.comingSoon && (
          <p className="mt-1.5 inline-flex items-center gap-1 text-xs text-[var(--yk-gold-dark)]">
            <AlertCircle className="h-3.5 w-3.5" />
            現在準備中のため、 個別に対応可否をご相談ください
          </p>
        )}
      </Field>

      {/* 専用フィールド (サービスごとに変化) */}
      {currentService.fields.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 sm:gap-5">
          {currentService.fields.map((f) => {
            if (f === "media") {
              return (
                <div key={f} className="sm:col-span-2">
                  <Field label={FIELD_META[f].label} hint="複数添付可">
                    <div>
                      <input
                        ref={fileInputRef}
                        type="file"
                        accept="image/*,video/*"
                        multiple
                        className="sr-only"
                        onChange={(e) => addFiles(e.target.files)}
                      />
                      <button
                        type="button"
                        onClick={() => fileInputRef.current?.click()}
                        className="w-full sm:w-auto inline-flex items-center justify-center gap-2 h-11 px-4 rounded-sm border border-dashed border-[var(--yk-navy)]/40 text-[var(--yk-navy)] hover:bg-[var(--yk-navy)]/5 transition-colors text-sm"
                      >
                        <Upload className="h-4 w-4" />
                        ファイルを選択
                      </button>
                      {files.length > 0 && (
                        <ul className="mt-3 space-y-1.5">
                          {files.map((file, i) => (
                            <li
                              key={`${file.name}-${i}`}
                              className="flex items-center gap-2 text-xs text-[var(--yk-steel)] bg-[var(--yk-navy)]/[0.04] rounded-sm px-2.5 py-1.5"
                            >
                              <span className="truncate flex-1">{file.name}</span>
                              <span className="text-[10px] text-[var(--yk-steel)]/70 whitespace-nowrap">
                                {(file.size / 1024).toFixed(0)} KB
                              </span>
                              <button
                                type="button"
                                onClick={() => removeFile(i)}
                                aria-label="削除"
                                className="text-[var(--yk-steel)]/60 hover:text-[var(--yk-navy)]"
                              >
                                <X className="h-3.5 w-3.5" />
                              </button>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  </Field>
                </div>
              );
            }
            const meta = FIELD_META[f];
            return (
              <Field key={f} label={meta.label}>
                <input
                  type="text"
                  name={f}
                  value={customFieldValues[f] || ""}
                  onChange={(e) =>
                    setCustomFieldValues((prev) => ({
                      ...prev,
                      [f]: e.target.value,
                    }))
                  }
                  className="w-full h-11 px-3 rounded-sm border border-border bg-white text-sm focus:outline-none focus:border-[var(--yk-navy)] focus:ring-1 focus:ring-[var(--yk-navy)]/30 transition"
                />
              </Field>
            );
          })}
        </div>
      )}

      {/* お問い合わせ内容 (必須) */}
      <Field label="お問い合わせ内容" required>
        <textarea
          name="content"
          rows={5}
          value={content}
          onChange={(e) => {
            setContent(e.target.value);
            if (contentError && e.target.value.trim()) setContentError(false);
          }}
          className={`w-full px-3 py-2.5 rounded-sm border bg-white text-sm leading-relaxed focus:outline-none focus:ring-1 transition ${
            contentError
              ? "border-red-500 focus:border-red-500 focus:ring-red-500/30"
              : "border-border focus:border-[var(--yk-navy)] focus:ring-[var(--yk-navy)]/30"
          }`}
        />
        {contentError && (
          <p className="mt-1.5 text-xs text-red-600">お問い合わせ内容を入力してください。</p>
        )}
      </Field>

      {/* お名前 / メールアドレス */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 sm:gap-5">
        <Field label="お名前">
          <input
            type="text"
            name="name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full h-11 px-3 rounded-sm border border-border bg-white text-sm focus:outline-none focus:border-[var(--yk-navy)] focus:ring-1 focus:ring-[var(--yk-navy)]/30 transition"
          />
        </Field>
        <Field label="メールアドレス" required>
          <input
            type="email"
            name="email"
            value={email}
            onChange={(e) => {
              setEmail(e.target.value);
              if (emailError) setEmailError(null);
            }}
            className={`w-full h-11 px-3 rounded-sm border bg-white text-sm focus:outline-none focus:ring-1 transition ${
              emailError
                ? "border-red-500 focus:border-red-500 focus:ring-red-500/30"
                : "border-border focus:border-[var(--yk-navy)] focus:ring-[var(--yk-navy)]/30"
            }`}
          />
          {emailError && (
            <p className="mt-1.5 text-xs text-red-600">{emailError}</p>
          )}
        </Field>
      </div>

      {/* 送信エラー */}
      {serverError && (
        <div className="rounded-sm border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700 flex items-start gap-2">
          <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
          <span>{serverError}</span>
        </div>
      )}

      {/* 送信 */}
      <div className="pt-2">
        <button
          type="submit"
          disabled={submitting}
          className="inline-flex items-center gap-2 h-12 px-7 rounded-sm bg-[var(--yk-navy)] hover:bg-[var(--yk-navy-dark)] disabled:bg-[var(--yk-navy)]/60 text-white font-bold text-sm transition-colors"
        >
          {submitting ? "送信中..." : "送信する"}
          {!submitting && <Send className="h-4 w-4" />}
        </button>
        <p className="text-xs text-[var(--yk-steel)] mt-3">
          ※ 送信内容は営業時間内に確認し、 折り返しご連絡いたします。
        </p>
      </div>
    </form>
  );
}

function Field({
  label,
  hint,
  required,
  children,
}: {
  label: string;
  hint?: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <div className="flex items-baseline gap-2 mb-1.5">
        <span className="font-headline text-sm font-bold text-[var(--yk-navy)]">{label}</span>
        {required && (
          <span className="text-[10px] text-red-600 font-mono-data tracking-wider">必須</span>
        )}
        {hint && <span className="text-[10px] text-[var(--yk-steel)]/70 ml-auto">{hint}</span>}
      </div>
      {children}
    </label>
  );
}

