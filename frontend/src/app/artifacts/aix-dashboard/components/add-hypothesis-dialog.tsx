"use client";

import * as React from "react";
import { Plus, Loader2, Lightbulb } from "lucide-react";
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

export function AddHypothesisDialog({
  defaultClientId,
  trigger,
}: {
  defaultClientId?: string;
  trigger?: React.ReactNode;
}) {
  const { clients, addHypothesis } = useAix();
  const [open, setOpen] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [form, setForm] = React.useState({
    clientId: defaultClientId || "",
    title: "",
    problem: "",
    solution: "",
    confidence: 50,
  });

  const submit = async () => {
    if (!form.title.trim() || !form.clientId) return;
    setBusy(true);
    try {
      await addHypothesis({
        clientId: form.clientId,
        title: form.title.trim(),
        problem: form.problem.trim() || undefined,
        solution: form.solution.trim() || undefined,
        confidence: form.confidence,
      });
      setForm({ clientId: defaultClientId || "", title: "", problem: "", solution: "", confidence: 50 });
      setOpen(false);
    } catch (e) {
      console.error("addHypothesis failed", e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger ?? (
          <Button size="sm" variant="outline" className="rounded-sm">
            <Lightbulb className="h-4 w-4 mr-1" />
            仮説を追加
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>課題仮説を追加</DialogTitle>
          <DialogDescription>クライアントの課題と解決アイデアをセットで記録します。</DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">クライアント <span className="text-rose-500">*</span></Label>
            <select
              value={form.clientId}
              onChange={(e) => setForm((f) => ({ ...f, clientId: e.target.value }))}
              className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
            >
              <option value="">— 選択 —</option>
              {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">仮説タイトル <span className="text-rose-500">*</span></Label>
            <Input
              value={form.title}
              onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
              placeholder="例: 修理進捗の可視化で問い合わせ電話を減らせる"
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">課題（顧客の困りごと）</Label>
            <Textarea
              value={form.problem}
              onChange={(e) => setForm((f) => ({ ...f, problem: e.target.value }))}
              rows={2}
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">解決策</Label>
            <Textarea
              value={form.solution}
              onChange={(e) => setForm((f) => ({ ...f, solution: e.target.value }))}
              rows={2}
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">確度 ({form.confidence}%)</Label>
            <input
              type="range"
              min={0}
              max={100}
              value={form.confidence}
              onChange={(e) => setForm((f) => ({ ...f, confidence: Number(e.target.value) }))}
              className="w-full"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} disabled={busy}>
            キャンセル
          </Button>
          <Button onClick={submit} disabled={busy || !form.title.trim() || !form.clientId}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <Plus className="h-4 w-4 mr-1" />}
            追加
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
