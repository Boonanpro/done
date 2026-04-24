"use client";

import * as React from "react";
import Image from "next/image";
import {
  Upload,
  X,
  CheckCircle2,
  Loader2,
  Phone,
  ChevronRight,
  ChevronLeft,
  Info,
  FileText,
  Camera,
  Wrench,
  Send,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

type VehicleInfo = {
  chassisNumber: string;
  model: string;
  classificationNumber: string;
  registrationYear: string;
  bodyMaker: string;
  bodyModel: string;
};

type ContactInfo = {
  company: string;
  name: string;
  phone: string;
  email: string;
};

type TroubleInfo = {
  part: string;
  symptom: string;
  freeText: string;
};

type PreferenceInfo = {
  urgency: string;
  preferredContact: string;
  notes: string;
};

type UploadedImage = {
  name: string;
  size: number;
  dataUrl: string;
  kind: "document" | "trouble";
};

const STEPS = [
  { n: 1, icon: FileText, label: "連絡先" },
  { n: 2, icon: Camera, label: "車両情報" },
  { n: 3, icon: Wrench, label: "不具合内容" },
  { n: 4, icon: Send, label: "確認・送信" },
];

const PART_OPTIONS = [
  "車体（キャビン・フレーム）",
  "架装（荷台・パッカー・タンク等）",
  "油圧系統（シリンダ・ポンプ・ホース）",
  "PTO・サブエンジン",
  "電装系（配線・スイッチ・ランプ）",
  "安全装置（リミットスイッチ・非常停止）",
  "その他",
];

const URGENCY_OPTIONS = [
  { value: "emergency", label: "至急（今日・明日中に修理）" },
  { value: "this_week", label: "今週中" },
  { value: "next_week", label: "来週中" },
  { value: "discuss", label: "応相談" },
];

const CONTACT_METHOD_OPTIONS = [
  { value: "phone", label: "電話で折り返し" },
  { value: "email", label: "メールで返信" },
  { value: "either", label: "どちらでも" },
];

const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10MB

export function MultiStepInquiry() {
  const [step, setStep] = React.useState(1);
  const [contact, setContact] = React.useState<ContactInfo>({
    company: "",
    name: "",
    phone: "",
    email: "",
  });
  const [vehicle, setVehicle] = React.useState<VehicleInfo>({
    chassisNumber: "",
    model: "",
    classificationNumber: "",
    registrationYear: "",
    bodyMaker: "",
    bodyModel: "",
  });
  const [trouble, setTrouble] = React.useState<TroubleInfo>({
    part: "",
    symptom: "",
    freeText: "",
  });
  const [preference, setPreference] = React.useState<PreferenceInfo>({
    urgency: "",
    preferredContact: "",
    notes: "",
  });
  const [images, setImages] = React.useState<UploadedImage[]>([]);
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [receiptNumber, setReceiptNumber] = React.useState<string | null>(null);

  const canProceed = {
    1: contact.company.trim() && contact.name.trim() && contact.phone.trim(),
    2: true, // 車両情報は全部必須にすると離脱増えるので任意（画像推奨）
    3: trouble.part && trouble.freeText.trim(),
    4: true,
  }[step];

  function handleImageUpload(
    files: FileList | null,
    kind: UploadedImage["kind"],
  ) {
    if (!files) return;
    Array.from(files).forEach((file) => {
      if (file.size > MAX_FILE_SIZE) {
        setError(`「${file.name}」は10MBを超えています`);
        return;
      }
      const reader = new FileReader();
      reader.onload = (e) => {
        const dataUrl = e.target?.result as string;
        setImages((prev) => [
          ...prev,
          { name: file.name, size: file.size, dataUrl, kind },
        ]);
      };
      reader.readAsDataURL(file);
    });
  }

  function removeImage(idx: number) {
    setImages((prev) => prev.filter((_, i) => i !== idx));
  }

  async function submit() {
    setSubmitting(true);
    setError(null);
    try {
      const message = JSON.stringify(
        {
          contact,
          vehicle,
          trouble,
          preference,
          image_count: images.length,
          image_names: images.map((i) => `[${i.kind}] ${i.name}`),
        },
        null,
        2,
      );
      const res = await fetch("/api/v1/inquiries", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scope: "yoshikawa-tokuso",
          name: contact.name,
          company: contact.company,
          email: contact.email || undefined,
          phone: contact.phone,
          message,
          source_url:
            typeof window !== "undefined" ? window.location.href : undefined,
        }),
      });
      if (!res.ok) {
        const body = await res.text();
        throw new Error(body || `HTTP ${res.status}`);
      }
      // 受付番号生成（本来はサーバが返すが、フロント生成でも十分）
      const now = new Date();
      const num = `YT-${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, "0")}${String(now.getDate()).padStart(2, "0")}-${Math.floor(
        1000 + Math.random() * 9000,
      )}`;
      setReceiptNumber(num);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(`送信に失敗しました: ${msg}`);
    } finally {
      setSubmitting(false);
    }
  }

  if (receiptNumber) {
    return <SuccessView receiptNumber={receiptNumber} contact={contact} />;
  }

  return (
    <div className="space-y-8">
      <StepIndicator current={step} />

      <Card className="border-border rounded-sm">
        <CardContent className="p-6 sm:p-10 space-y-6">
          {step === 1 && (
            <Step1Contact contact={contact} onChange={setContact} />
          )}
          {step === 2 && (
            <Step2Vehicle
              vehicle={vehicle}
              onChange={setVehicle}
              images={images.filter((i) => i.kind === "document")}
              onImageAdd={(files) => handleImageUpload(files, "document")}
              onImageRemove={(idx) => {
                const docImages = images.filter((i) => i.kind === "document");
                const target = docImages[idx];
                const globalIdx = images.indexOf(target);
                removeImage(globalIdx);
              }}
            />
          )}
          {step === 3 && (
            <Step3Trouble
              trouble={trouble}
              onChange={setTrouble}
              images={images.filter((i) => i.kind === "trouble")}
              onImageAdd={(files) => handleImageUpload(files, "trouble")}
              onImageRemove={(idx) => {
                const trImages = images.filter((i) => i.kind === "trouble");
                const target = trImages[idx];
                const globalIdx = images.indexOf(target);
                removeImage(globalIdx);
              }}
            />
          )}
          {step === 4 && (
            <Step4Review
              contact={contact}
              vehicle={vehicle}
              trouble={trouble}
              preference={preference}
              onPreferenceChange={setPreference}
              imageCount={images.length}
            />
          )}
        </CardContent>
      </Card>

      {error && (
        <div className="rounded-sm border border-destructive/30 bg-destructive/5 text-destructive text-sm p-4">
          {error}
        </div>
      )}

      <div className="flex items-center justify-between gap-3">
        <Button
          type="button"
          variant="outline"
          className="rounded-sm border-[var(--yk-navy)]/30 text-[var(--yk-navy)]"
          onClick={() => {
            setError(null);
            setStep((s) => Math.max(1, s - 1));
          }}
          disabled={step === 1 || submitting}
        >
          <ChevronLeft className="h-4 w-4 mr-1" />
          戻る
        </Button>
        {step < 4 ? (
          <Button
            type="button"
            className="rounded-sm bg-[var(--yk-navy)] hover:bg-[var(--yk-navy-dark)] text-white"
            onClick={() => {
              if (!canProceed) {
                setError("必須項目を入力してください");
                return;
              }
              setError(null);
              setStep((s) => Math.min(4, s + 1));
            }}
          >
            次へ
            <ChevronRight className="h-4 w-4 ml-1" />
          </Button>
        ) : (
          <Button
            type="button"
            className="rounded-sm bg-[var(--yk-gold)] hover:bg-[var(--yk-gold-dark)] text-[var(--yk-navy-dark)] font-bold h-11 px-6"
            onClick={submit}
            disabled={submitting}
          >
            {submitting ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin mr-2" />
                送信中...
              </>
            ) : (
              <>
                送信する
                <Send className="h-4 w-4 ml-2" />
              </>
            )}
          </Button>
        )}
      </div>
    </div>
  );
}

/* ───────────────── Step Indicator ───────────────── */

function StepIndicator({ current }: { current: number }) {
  return (
    <div className="relative">
      <div className="absolute top-5 left-[5%] right-[5%] h-px bg-border" />
      <div className="relative grid grid-cols-4 gap-2">
        {STEPS.map((s) => {
          const active = s.n === current;
          const done = s.n < current;
          const Icon = s.icon;
          return (
            <div key={s.n} className="flex flex-col items-center gap-2">
              <div
                className={cn(
                  "h-10 w-10 rounded-sm flex items-center justify-center font-mono-data font-bold text-sm transition-colors",
                  active &&
                    "bg-[var(--yk-navy)] text-white ring-4 ring-[var(--yk-navy)]/15",
                  done && "bg-[var(--yk-gold)] text-[var(--yk-navy-dark)]",
                  !active && !done && "bg-white border border-border text-[var(--yk-steel)]",
                )}
              >
                {done ? <CheckCircle2 className="h-5 w-5" /> : <Icon className="h-4 w-4" />}
              </div>
              <span
                className={cn(
                  "text-xs font-medium text-center",
                  active ? "text-[var(--yk-navy)]" : "text-[var(--yk-steel)]",
                )}
              >
                {s.label}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ───────────────── Steps ───────────────── */

function Step1Contact({
  contact,
  onChange,
}: {
  contact: ContactInfo;
  onChange: React.Dispatch<React.SetStateAction<ContactInfo>>;
}) {
  return (
    <div className="space-y-6">
      <SectionHeading
        num="01"
        title="ご連絡先"
        desc="折り返しご連絡するための基本情報です。"
      />
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
        <FieldLabel label="会社名・屋号" required>
          <Input
            value={contact.company}
            onChange={(e) => onChange((c) => ({ ...c, company: e.target.value }))}
            placeholder="例: 株式会社 ○○運輸"
            className="rounded-sm"
          />
        </FieldLabel>
        <FieldLabel label="ご担当者名" required>
          <Input
            value={contact.name}
            onChange={(e) => onChange((c) => ({ ...c, name: e.target.value }))}
            placeholder="例: 山田 太郎"
            className="rounded-sm"
          />
        </FieldLabel>
        <FieldLabel label="電話番号" required>
          <Input
            type="tel"
            value={contact.phone}
            onChange={(e) => onChange((c) => ({ ...c, phone: e.target.value }))}
            placeholder="0859-XX-XXXX"
            className="rounded-sm font-mono-data"
          />
        </FieldLabel>
        <FieldLabel label="メールアドレス" hint="画像送付の案内にも使います">
          <Input
            type="email"
            value={contact.email}
            onChange={(e) => onChange((c) => ({ ...c, email: e.target.value }))}
            placeholder="example@company.jp"
            className="rounded-sm"
          />
        </FieldLabel>
      </div>
    </div>
  );
}

function Step2Vehicle({
  vehicle,
  onChange,
  images,
  onImageAdd,
  onImageRemove,
}: {
  vehicle: VehicleInfo;
  onChange: React.Dispatch<React.SetStateAction<VehicleInfo>>;
  images: UploadedImage[];
  onImageAdd: (files: FileList | null) => void;
  onImageRemove: (idx: number) => void;
}) {
  return (
    <div className="space-y-7">
      <SectionHeading
        num="02"
        title="車両情報"
        desc="特装車の部品発注には、車台番号と型式指定番号が必須です。分からない項目は車検証の写真だけでもOKです。"
      />

      <div className="rounded-sm bg-[var(--yk-navy)]/5 border border-[var(--yk-navy)]/10 p-5 flex gap-3">
        <Info className="h-5 w-5 text-[var(--yk-navy)] shrink-0 mt-0.5" />
        <div className="text-sm text-[var(--yk-navy-dark)] leading-relaxed">
          <div className="font-bold mb-1">なぜ車台番号が必要？</div>
          同じ車種でも年式や仕様で部品が異なります。車台番号と型式指定番号を先にいただければ、
          折り返し時に部品在庫と概算見積まで即お伝えできます。
        </div>
      </div>

      <ImageUploader
        label="車検証の写真"
        hint="助手席前のダッシュボードや運転席ドア内側のシールをそのまま撮影いただけばOKです。"
        images={images}
        onAdd={onImageAdd}
        onRemove={onImageRemove}
      />

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
        <FieldLabel label="車台番号">
          <Input
            value={vehicle.chassisNumber}
            onChange={(e) =>
              onChange((v) => ({ ...v, chassisNumber: e.target.value }))
            }
            placeholder="例: FU2AKGA-000001"
            className="rounded-sm font-mono-data"
          />
        </FieldLabel>
        <FieldLabel label="型式">
          <Input
            value={vehicle.model}
            onChange={(e) => onChange((v) => ({ ...v, model: e.target.value }))}
            placeholder="例: QKG-FU2AKGA"
            className="rounded-sm font-mono-data"
          />
        </FieldLabel>
        <FieldLabel label="類別区分番号">
          <Input
            value={vehicle.classificationNumber}
            onChange={(e) =>
              onChange((v) => ({
                ...v,
                classificationNumber: e.target.value,
              }))
            }
            placeholder="例: 0001"
            className="rounded-sm font-mono-data"
          />
        </FieldLabel>
        <FieldLabel label="初度登録年月">
          <Input
            value={vehicle.registrationYear}
            onChange={(e) =>
              onChange((v) => ({ ...v, registrationYear: e.target.value }))
            }
            placeholder="例: 2018年4月"
            className="rounded-sm"
          />
        </FieldLabel>
        <FieldLabel label="架装メーカー">
          <Input
            value={vehicle.bodyMaker}
            onChange={(e) =>
              onChange((v) => ({ ...v, bodyMaker: e.target.value }))
            }
            placeholder="例: 新明和工業"
            className="rounded-sm"
          />
        </FieldLabel>
        <FieldLabel label="架装の型式">
          <Input
            value={vehicle.bodyModel}
            onChange={(e) =>
              onChange((v) => ({ ...v, bodyModel: e.target.value }))
            }
            placeholder="例: G-PH23 (塵芥車)"
            className="rounded-sm font-mono-data"
          />
        </FieldLabel>
      </div>
    </div>
  );
}

function Step3Trouble({
  trouble,
  onChange,
  images,
  onImageAdd,
  onImageRemove,
}: {
  trouble: TroubleInfo;
  onChange: React.Dispatch<React.SetStateAction<TroubleInfo>>;
  images: UploadedImage[];
  onImageAdd: (files: FileList | null) => void;
  onImageRemove: (idx: number) => void;
}) {
  return (
    <div className="space-y-7">
      <SectionHeading
        num="03"
        title="不具合の内容"
        desc="どこが、どう壊れているか。文章だけでなく、画像や動画をいただけると診断が一気に進みます。"
      />
      <FieldLabel label="不具合のある部位" required>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {PART_OPTIONS.map((opt) => (
            <button
              key={opt}
              type="button"
              onClick={() => onChange((t) => ({ ...t, part: opt }))}
              className={cn(
                "flex items-center gap-2 rounded-sm border px-4 py-2.5 text-sm text-left transition-colors",
                trouble.part === opt
                  ? "border-[var(--yk-navy)] bg-[var(--yk-navy)]/5 text-[var(--yk-navy)]"
                  : "border-border bg-white text-[var(--yk-steel)] hover:border-[var(--yk-navy)]/50",
              )}
            >
              <span
                className={cn(
                  "h-4 w-4 rounded-sm border shrink-0",
                  trouble.part === opt
                    ? "bg-[var(--yk-navy)] border-[var(--yk-navy)]"
                    : "border-border",
                )}
              >
                {trouble.part === opt && (
                  <CheckCircle2 className="h-full w-full text-white" />
                )}
              </span>
              <span>{opt}</span>
            </button>
          ))}
        </div>
      </FieldLabel>
      <FieldLabel
        label="症状（どのような不具合ですか？）"
        required
        hint="例: 荷台を上げると途中で止まる / 異音がする / 油が漏れている"
      >
        <textarea
          value={trouble.freeText}
          onChange={(e) =>
            onChange((t) => ({ ...t, freeText: e.target.value }))
          }
          rows={5}
          placeholder="症状が出始めた時期や、どんな時に症状が出るかも書いていただけると助かります。"
          className="w-full rounded-sm border border-input bg-transparent px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-[var(--yk-navy)]/40 resize-y min-h-[140px]"
        />
      </FieldLabel>
      <ImageUploader
        label="破損箇所・異常箇所の画像・動画"
        hint="遠景（全体）と近景（壊れた箇所）を2〜3枚ずつ。動画も可（10MB以内）"
        images={images}
        onAdd={onImageAdd}
        onRemove={onImageRemove}
        accept="image/*,video/*"
      />
    </div>
  );
}

function Step4Review({
  contact,
  vehicle,
  trouble,
  preference,
  onPreferenceChange,
  imageCount,
}: {
  contact: ContactInfo;
  vehicle: VehicleInfo;
  trouble: TroubleInfo;
  preference: PreferenceInfo;
  onPreferenceChange: React.Dispatch<React.SetStateAction<PreferenceInfo>>;
  imageCount: number;
}) {
  return (
    <div className="space-y-7">
      <SectionHeading
        num="04"
        title="ご希望 ・ 確認"
        desc="最後にご希望の納期と連絡方法をお聞かせください。"
      />

      <FieldLabel label="ご希望の納期">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {URGENCY_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() =>
                onPreferenceChange((p) => ({ ...p, urgency: opt.value }))
              }
              className={cn(
                "rounded-sm border px-4 py-2.5 text-sm text-left transition-colors",
                preference.urgency === opt.value
                  ? "border-[var(--yk-navy)] bg-[var(--yk-navy)]/5 text-[var(--yk-navy)]"
                  : "border-border bg-white text-[var(--yk-steel)] hover:border-[var(--yk-navy)]/50",
              )}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </FieldLabel>

      <FieldLabel label="希望の連絡方法">
        <div className="grid grid-cols-3 gap-2">
          {CONTACT_METHOD_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() =>
                onPreferenceChange((p) => ({
                  ...p,
                  preferredContact: opt.value,
                }))
              }
              className={cn(
                "rounded-sm border px-4 py-2.5 text-sm transition-colors",
                preference.preferredContact === opt.value
                  ? "border-[var(--yk-navy)] bg-[var(--yk-navy)]/5 text-[var(--yk-navy)]"
                  : "border-border bg-white text-[var(--yk-steel)] hover:border-[var(--yk-navy)]/50",
              )}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </FieldLabel>

      <FieldLabel label="自由記入欄（任意）">
        <textarea
          value={preference.notes}
          onChange={(e) =>
            onPreferenceChange((p) => ({ ...p, notes: e.target.value }))
          }
          rows={3}
          placeholder="過去の修理歴、気になっている他の箇所、出張修理の可否など"
          className="w-full rounded-sm border border-input bg-transparent px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-[var(--yk-navy)]/40 resize-y min-h-[80px]"
        />
      </FieldLabel>

      <div className="rounded-sm bg-[var(--yk-navy)]/5 p-5 space-y-3">
        <div className="font-headline font-bold text-[var(--yk-navy)]">
          送信内容の確認
        </div>
        <ReviewRow
          label="ご連絡先"
          value={`${contact.company} / ${contact.name} / ${contact.phone}${
            contact.email ? ` / ${contact.email}` : ""
          }`}
        />
        <ReviewRow
          label="車両"
          value={
            [vehicle.chassisNumber, vehicle.model, vehicle.bodyMaker]
              .filter(Boolean)
              .join(" / ") || "（未入力）"
          }
        />
        <ReviewRow label="不具合部位" value={trouble.part || "（未選択）"} />
        <ReviewRow
          label="症状"
          value={
            trouble.freeText.length > 60
              ? trouble.freeText.slice(0, 60) + "..."
              : trouble.freeText || "（未記入）"
          }
        />
        <ReviewRow label="添付画像" value={`${imageCount} 枚`} />
      </div>
    </div>
  );
}

/* ───────────────── Sub components ───────────────── */

function SectionHeading({
  num,
  title,
  desc,
}: {
  num: string;
  title: string;
  desc?: string;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-3">
        <span className="font-mono-data text-lg font-black text-[var(--yk-gold-dark)]">
          {num}
        </span>
        <div className="h-px flex-1 bg-border" />
      </div>
      <h2 className="font-headline text-2xl font-black text-[var(--yk-navy)]">
        {title}
      </h2>
      {desc && (
        <p className="text-sm text-[var(--yk-steel)] leading-relaxed">{desc}</p>
      )}
    </div>
  );
}

function FieldLabel({
  label,
  required,
  hint,
  children,
}: {
  label: string;
  required?: boolean;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <Label className="text-sm font-medium text-[var(--yk-navy-dark)] flex items-center gap-1.5">
        {label}
        {required && (
          <span className="text-[var(--yk-gold-dark)] text-xs font-mono-data">
            REQUIRED
          </span>
        )}
      </Label>
      {hint && <div className="text-xs text-[var(--yk-steel)]">{hint}</div>}
      {children}
    </div>
  );
}

function ImageUploader({
  label,
  hint,
  images,
  onAdd,
  onRemove,
  accept = "image/*",
}: {
  label: string;
  hint: string;
  images: UploadedImage[];
  onAdd: (files: FileList | null) => void;
  onRemove: (idx: number) => void;
  accept?: string;
}) {
  const inputId = React.useId();
  return (
    <FieldLabel label={label} hint={hint}>
      <label
        htmlFor={inputId}
        className="block rounded-sm border-2 border-dashed border-border hover:border-[var(--yk-navy)]/50 bg-[var(--yk-navy)]/[0.02] hover:bg-[var(--yk-navy)]/5 transition-colors cursor-pointer p-8 text-center"
      >
        <Upload className="h-8 w-8 mx-auto text-[var(--yk-navy)]/60" />
        <div className="mt-3 text-sm font-medium text-[var(--yk-navy)]">
          クリックで写真・動画を選択
        </div>
        <div className="text-xs text-[var(--yk-steel)] mt-1">
          または、ここにドラッグ＆ドロップ
        </div>
        <input
          id={inputId}
          type="file"
          accept={accept}
          multiple
          className="hidden"
          onChange={(e) => {
            onAdd(e.target.files);
            e.target.value = "";
          }}
        />
      </label>
      {images.length > 0 && (
        <div className="mt-3 grid grid-cols-3 sm:grid-cols-4 gap-2">
          {images.map((img, idx) => (
            <div
              key={idx}
              className="relative aspect-square rounded-sm overflow-hidden border border-border group bg-[var(--yk-navy)]/5"
            >
              {img.dataUrl.startsWith("data:video") ? (
                <video
                  src={img.dataUrl}
                  className="w-full h-full object-cover"
                  muted
                />
              ) : (
                <Image
                  src={img.dataUrl}
                  alt={img.name}
                  fill
                  className="object-cover"
                  unoptimized
                />
              )}
              <button
                type="button"
                onClick={() => onRemove(idx)}
                className="absolute top-1 right-1 h-6 w-6 rounded-sm bg-black/60 text-white opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center"
              >
                <X className="h-3 w-3" />
              </button>
              <div className="absolute bottom-0 left-0 right-0 bg-black/60 text-white text-[10px] px-1.5 py-0.5 truncate">
                {img.name}
              </div>
            </div>
          ))}
        </div>
      )}
    </FieldLabel>
  );
}

function ReviewRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-3 gap-3 text-sm">
      <div className="text-[var(--yk-steel)] text-xs uppercase tracking-wide">
        {label}
      </div>
      <div className="col-span-2 text-[var(--yk-navy-dark)]">{value}</div>
    </div>
  );
}

function SuccessView({
  receiptNumber,
  contact,
}: {
  receiptNumber: string;
  contact: ContactInfo;
}) {
  return (
    <div className="space-y-6">
      <Card className="border-[var(--yk-gold)]/50 border-2 rounded-sm bg-gradient-to-br from-[var(--yk-navy)]/5 to-transparent">
        <CardContent className="p-10 text-center space-y-5">
          <div className="inline-flex h-16 w-16 rounded-sm bg-[var(--yk-gold)] text-[var(--yk-navy-dark)] items-center justify-center mx-auto">
            <CheckCircle2 className="h-8 w-8" />
          </div>
          <h2 className="font-headline text-3xl font-black text-[var(--yk-navy)]">
            お問い合わせを受け付けました
          </h2>
          <div className="inline-block rounded-sm bg-[var(--yk-navy)] text-white px-6 py-3">
            <div className="text-xs font-eyebrow text-[var(--yk-gold)]">
              受付番号
            </div>
            <div className="font-mono-data text-2xl font-bold tracking-wider">
              {receiptNumber}
            </div>
          </div>
          <p className="text-[var(--yk-steel)] leading-relaxed max-w-lg mx-auto">
            {contact.name} 様、ありがとうございます。
            <br />
            内容を確認の上、
            <strong className="text-[var(--yk-navy)]">1営業日以内</strong>
            に担当者より折り返しご連絡いたします。
          </p>
        </CardContent>
      </Card>
      <Card className="border-border rounded-sm">
        <CardContent className="p-8 space-y-5">
          <h3 className="font-headline text-lg font-bold text-[var(--yk-navy)]">
            お急ぎの場合
          </h3>
          <div className="flex flex-col sm:flex-row gap-4">
            <a
              href="tel:0859-27-4885"
              className="flex items-center gap-3 bg-[var(--yk-navy)] text-white rounded-sm px-5 py-4 hover:bg-[var(--yk-navy-dark)] transition-colors"
            >
              <Phone className="h-5 w-5" />
              <div className="text-left">
                <div className="text-xs text-white/70">直接お電話ください</div>
                <div className="font-mono-data text-xl font-bold">
                  0859-27-4885
                </div>
              </div>
            </a>
            <div className="flex-1 text-sm text-[var(--yk-steel)] leading-relaxed">
              受付後も、追加の画像や情報がございましたら上記電話番号までお知らせください。受付番号
              <span className="font-mono-data font-bold text-[var(--yk-navy)]">
                {" "}
                {receiptNumber}{" "}
              </span>
              をお伝えいただくと、即座に対応履歴を参照できます。
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
