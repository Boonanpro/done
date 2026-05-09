"use client";

import { useState } from "react";
import { Plus, Trash2, X } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useInspectionStore } from "../store";
import type { Equipment } from "../types";

const CATEGORIES: { value: Equipment["category"]; label: string }[] = [
  { value: "pas", label: "開閉器（PAS）" },
  { value: "dgr_relay", label: "地絡方向継電器（DGR）" },
  { value: "ocr", label: "過電流継電器（OCR）" },
  { value: "ovgr", label: "地絡過電圧継電器（OVGR）" },
  { value: "transformer", label: "変圧器" },
  { value: "other", label: "その他" },
];

const empty = (): Equipment => ({
  id: `eq-${Date.now()}`,
  category: "pas",
  category_label: "開閉器（PAS）",
  maker: "",
  model: "",
  serial: "",
  mfg_date: "",
});

export function EquipmentMasterView() {
  const equipments = useInspectionStore((s) => s.equipments);
  const upsert = useInspectionStore((s) => s.upsertEquipment);
  const remove = useInspectionStore((s) => s.removeEquipment);

  const [editing, setEditing] = useState<Equipment | null>(null);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-semibold">機器マスタ</h2>
          <p className="text-muted-foreground text-sm">
            継電器・PASなど。複数のクライアントで共有できます。
          </p>
        </div>
        <Button onClick={() => setEditing(empty())}>
          <Plus className="h-4 w-4 mr-2" />新規追加
        </Button>
      </div>

      <div className="space-y-2">
        {equipments.map((e) => (
          <Card
            key={e.id}
            className="cursor-pointer hover:bg-secondary/30 transition"
            onClick={() => setEditing({ ...e })}
          >
            <CardContent className="py-3 flex items-center gap-4">
              <Badge variant="outline">
                {CATEGORIES.find((c) => c.value === e.category)?.label ?? e.category_label}
              </Badge>
              <div className="flex-1">
                <p className="font-medium">{e.maker} / {e.model}</p>
                <p className="text-sm text-muted-foreground">製番 {e.serial} ／ {e.mfg_date}</p>
              </div>
              {e.setting && (
                <div className="text-xs text-muted-foreground max-w-xs truncate">{e.setting}</div>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      <Dialog open={!!editing} onOpenChange={(v) => !v && setEditing(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>機器の{equipments.some((x) => x.id === editing?.id) ? "編集" : "追加"}</DialogTitle>
          </DialogHeader>
          {editing && (
            <div className="space-y-4 py-4">
              <div>
                <Label>分類</Label>
                <Select
                  value={editing.category}
                  onValueChange={(v) =>
                    setEditing({
                      ...editing,
                      category: v as Equipment["category"],
                      category_label: CATEGORIES.find((c) => c.value === v)?.label ?? "",
                    })
                  }
                >
                  <SelectTrigger className="mt-2">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {CATEGORIES.map((c) => (
                      <SelectItem key={c.value} value={c.value}>{c.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
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
                <div>
                  <Label>型番</Label>
                  <Input className="mt-2" value={editing.model_no ?? ""} onChange={(e) => setEditing({ ...editing, model_no: e.target.value })} />
                </div>
                <div>
                  <Label>製造番号</Label>
                  <Input className="mt-2" value={editing.serial} onChange={(e) => setEditing({ ...editing, serial: e.target.value })} />
                </div>
                <div>
                  <Label>製造年月</Label>
                  <Input className="mt-2" value={editing.mfg_date} onChange={(e) => setEditing({ ...editing, mfg_date: e.target.value })} placeholder="例: 2013年4月" />
                </div>
              </div>
              <div>
                <Label>整定値（限時 / メイン）</Label>
                <Input className="mt-2" value={editing.setting ?? ""} onChange={(e) => setEditing({ ...editing, setting: e.target.value })} />
              </div>
              <div>
                <Label>整定値2（瞬時 / サブ）</Label>
                <Input className="mt-2" value={editing.setting2 ?? ""} onChange={(e) => setEditing({ ...editing, setting2: e.target.value })} />
              </div>
            </div>
          )}
          <DialogFooter className="flex justify-between">
            <div>
              {editing && equipments.some((x) => x.id === editing.id) && (
                <Button
                  variant="outline"
                  onClick={() => {
                    if (confirm("この機器を削除しますか？")) {
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
