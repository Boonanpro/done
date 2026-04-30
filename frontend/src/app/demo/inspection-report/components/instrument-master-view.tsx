"use client";

import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { useInspectionStore } from "../store";
import type { MeasuringInstrument } from "../types";

const empty = (): MeasuringInstrument => ({
  id: `mi-${Date.now()}`,
  name: "",
  maker: "",
  model: "",
  serial: "",
});

export function InstrumentMasterView() {
  const list = useInspectionStore((s) => s.instruments);
  const upsert = useInspectionStore((s) => s.upsertInstrument);
  const remove = useInspectionStore((s) => s.removeInstrument);
  const [editing, setEditing] = useState<MeasuringInstrument | null>(null);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-semibold">計測器</h2>
          <p className="text-muted-foreground text-sm">
            点検で使う試験機の一覧。報告書の最後の表に印字されます。
          </p>
        </div>
        <Button onClick={() => setEditing(empty())}>
          <Plus className="h-4 w-4 mr-2" />新規追加
        </Button>
      </div>

      <div className="space-y-2">
        {list.map((m) => (
          <Card
            key={m.id}
            className="cursor-pointer hover:bg-secondary/30 transition"
            onClick={() => setEditing({ ...m })}
          >
            <CardContent className="py-3 flex items-center gap-4">
              <div className="flex-1">
                <p className="font-medium">{m.name}</p>
                <p className="text-sm text-muted-foreground">
                  {m.maker} / {m.model}
                </p>
              </div>
              <div className="text-xs text-muted-foreground">{m.serial}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Dialog open={!!editing} onOpenChange={(v) => !v && setEditing(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>計測器の{list.some((x) => x.id === editing?.id) ? "編集" : "追加"}</DialogTitle>
          </DialogHeader>
          {editing && (
            <div className="space-y-4 py-4">
              <div>
                <Label>機器名</Label>
                <Input className="mt-2" value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })} placeholder="例: 接地抵抗計" />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label>製造者名</Label>
                  <Input className="mt-2" value={editing.maker} onChange={(e) => setEditing({ ...editing, maker: e.target.value })} />
                </div>
                <div>
                  <Label>型式</Label>
                  <Input className="mt-2" value={editing.model} onChange={(e) => setEditing({ ...editing, model: e.target.value })} />
                </div>
              </div>
              <div>
                <Label>製造番号</Label>
                <Input className="mt-2" value={editing.serial} onChange={(e) => setEditing({ ...editing, serial: e.target.value })} />
              </div>
            </div>
          )}
          <DialogFooter className="flex justify-between">
            <div>
              {editing && list.some((x) => x.id === editing.id) && (
                <Button
                  variant="outline"
                  onClick={() => {
                    if (confirm("この計測器を削除しますか？")) {
                      remove(editing.id);
                      setEditing(null);
                    }
                  }}
                >
                  <Trash2 className="h-4 w-4 mr-2" />削除
                </Button>
              )}
            </div>
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => setEditing(null)}>キャンセル</Button>
              <Button
                onClick={() => {
                  if (editing) {
                    upsert(editing);
                    setEditing(null);
                  }
                }}
              >
                保存
              </Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
