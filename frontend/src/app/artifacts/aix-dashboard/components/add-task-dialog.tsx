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

export function AddTaskDialog({
  defaultClientId,
  trigger,
}: {
  defaultClientId?: string;
  trigger?: React.ReactNode;
}) {
  const { clients, addOpsTask } = useAix();
  const [open, setOpen] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [form, setForm] = React.useState({
    clientId: defaultClientId || "",
    title: "",
    detail: "",
    priority: "mid" as "high" | "mid" | "low",
    dueDate: "",
  });

  const submit = async () => {
    if (!form.title.trim()) return;
    setBusy(true);
    try {
      await addOpsTask({
        clientId: form.clientId || undefined,
        title: form.title.trim(),
        detail: form.detail.trim() || undefined,
        priority: form.priority,
        dueDate: form.dueDate || undefined,
      });
      setForm({ clientId: defaultClientId || "", title: "", detail: "", priority: "mid", dueDate: "" });
      setOpen(false);
    } catch (e) {
      console.error("addOpsTask failed", e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger ?? (
          <Button size="sm" variant="outline" className="rounded-sm">
            <Plus className="h-4 w-4 mr-1" />
            タスクを追加
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>運用タスクを追加</DialogTitle>
          <DialogDescription>
            着手するタスクを未着手列に追加します。
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">クライアント</Label>
            <select
              value={form.clientId}
              onChange={(e) => setForm((f) => ({ ...f, clientId: e.target.value }))}
              className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
            >
              <option value="">— 未指定 —</option>
              {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">タイトル <span className="text-rose-500">*</span></Label>
            <Input
              value={form.title}
              onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
              placeholder="例: HPの問い合わせ件数を集計"
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">詳細</Label>
            <Textarea
              value={form.detail}
              onChange={(e) => setForm((f) => ({ ...f, detail: e.target.value }))}
              rows={3}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">優先度</Label>
              <select
                value={form.priority}
                onChange={(e) => setForm((f) => ({ ...f, priority: e.target.value as "high" | "mid" | "low" }))}
                className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
              >
                <option value="high">高</option>
                <option value="mid">中</option>
                <option value="low">低</option>
              </select>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">期限</Label>
              <Input
                type="date"
                value={form.dueDate}
                onChange={(e) => setForm((f) => ({ ...f, dueDate: e.target.value }))}
              />
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} disabled={busy}>
            キャンセル
          </Button>
          <Button onClick={submit} disabled={busy || !form.title.trim()}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <Plus className="h-4 w-4 mr-1" />}
            追加
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
