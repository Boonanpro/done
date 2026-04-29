"use client";

import * as React from "react";
import { Plus, Loader2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useAix } from "../data/store";
import type { ClientStage, Priority } from "../data/mock";

const STAGES: { value: ClientStage; label: string }[] = [
  { value: "prospect", label: "見込み" },
  { value: "proposed", label: "提案中" },
  { value: "meeting", label: "商談中" },
  { value: "contracted", label: "契約済" },
  { value: "running", label: "運用中" },
];

const PRIORITIES: { value: Priority; label: string }[] = [
  { value: "high", label: "高" },
  { value: "mid", label: "中" },
  { value: "low", label: "低" },
];

export function AddClientDialog({
  trigger,
}: {
  trigger?: React.ReactNode;
}) {
  const { addClient } = useAix();
  const [open, setOpen] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [form, setForm] = React.useState({
    name: "",
    industry: "",
    location: "",
    contactName: "",
    contactPhone: "",
    contactEmail: "",
    summary: "",
    tags: "",
    stage: "prospect" as ClientStage,
    priority: "mid" as Priority,
  });

  const reset = () => setForm({
    name: "", industry: "", location: "", contactName: "",
    contactPhone: "", contactEmail: "", summary: "", tags: "",
    stage: "prospect", priority: "mid",
  });

  const submit = async () => {
    if (!form.name.trim()) return;
    setBusy(true);
    try {
      await addClient({
        name: form.name.trim(),
        industry: form.industry.trim() || undefined,
        location: form.location.trim() || undefined,
        contactName: form.contactName.trim() || undefined,
        contactPhone: form.contactPhone.trim() || undefined,
        contactEmail: form.contactEmail.trim() || undefined,
        summary: form.summary.trim() || undefined,
        tags: form.tags.split(/[,、\s]+/).map((t) => t.trim()).filter(Boolean),
        stage: form.stage,
        priority: form.priority,
      });
      reset();
      setOpen(false);
    } catch (e) {
      console.error("addClient failed", e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger ?? (
          <Button size="sm" className="rounded-sm">
            <Plus className="h-4 w-4 mr-1" />
            企業を追加
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>クライアント企業を追加</DialogTitle>
          <DialogDescription>
            最低限「会社名」だけあればOK。詳細はあとから編集できます。
          </DialogDescription>
        </DialogHeader>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 py-2">
          <FieldFull label="会社名" required>
            <Input
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              placeholder="例: 有限会社 ○○製作所"
            />
          </FieldFull>
          <Field label="業種">
            <Input
              value={form.industry}
              onChange={(e) => setForm((f) => ({ ...f, industry: e.target.value }))}
              placeholder="例: 自動車整備"
            />
          </Field>
          <Field label="所在地">
            <Input
              value={form.location}
              onChange={(e) => setForm((f) => ({ ...f, location: e.target.value }))}
              placeholder="例: 鳥取県米子市"
            />
          </Field>
          <Field label="担当者名">
            <Input
              value={form.contactName}
              onChange={(e) => setForm((f) => ({ ...f, contactName: e.target.value }))}
            />
          </Field>
          <Field label="担当者電話">
            <Input
              value={form.contactPhone}
              onChange={(e) => setForm((f) => ({ ...f, contactPhone: e.target.value }))}
              placeholder="0000-00-0000"
            />
          </Field>
          <Field label="担当者メール">
            <Input
              value={form.contactEmail}
              onChange={(e) => setForm((f) => ({ ...f, contactEmail: e.target.value }))}
              placeholder="example@company.jp"
            />
          </Field>
          <Field label="ステージ">
            <select
              value={form.stage}
              onChange={(e) => setForm((f) => ({ ...f, stage: e.target.value as ClientStage }))}
              className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
            >
              {STAGES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </Field>
          <Field label="優先度">
            <select
              value={form.priority}
              onChange={(e) => setForm((f) => ({ ...f, priority: e.target.value as Priority }))}
              className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
            >
              {PRIORITIES.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
            </select>
          </Field>
          <FieldFull label="タグ（カンマ区切り）">
            <Input
              value={form.tags}
              onChange={(e) => setForm((f) => ({ ...f, tags: e.target.value }))}
              placeholder="例: 物流, 中国地方, DX初期"
            />
          </FieldFull>
          <FieldFull label="メモ・課題サマリ">
            <Textarea
              value={form.summary}
              onChange={(e) => setForm((f) => ({ ...f, summary: e.target.value }))}
              rows={3}
              placeholder="現状の課題・初期仮説など"
            />
          </FieldFull>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} disabled={busy}>
            キャンセル
          </Button>
          <Button onClick={submit} disabled={busy || !form.name.trim()}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <Plus className="h-4 w-4 mr-1" />}
            追加する
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      {children}
    </div>
  );
}

function FieldFull({ label, required, children }: { label: string; required?: boolean; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5 sm:col-span-2">
      <Label className="text-xs text-muted-foreground flex items-center gap-1">
        {label}
        {required && <span className="text-rose-500">*</span>}
      </Label>
      {children}
    </div>
  );
}
