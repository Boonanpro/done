"use client";

import { useState } from "react";
import { Plus, Building2, ChevronRight } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  DialogFooter,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { useInspectionStore } from "../store";

export function ClientsView({ onSelect }: { onSelect: (id: string) => void }) {
  const clients = useInspectionStore((s) => s.clients);
  const upsertClient = useInspectionStore((s) => s.upsertClient);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [facility, setFacility] = useState("");

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-semibold">クライアント</h2>
          <p className="text-muted-foreground text-sm">{clients.length}件 登録中</p>
        </div>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button><Plus className="h-4 w-4 mr-2" />新規追加</Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>新しいクライアントを追加</DialogTitle>
            </DialogHeader>
            <div className="space-y-4 py-4">
              <div>
                <Label>会社名</Label>
                <Input
                  className="mt-2"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="例: 株式会社 〇〇"
                />
              </div>
              <div>
                <Label>設備名</Label>
                <Input
                  className="mt-2"
                  value={facility}
                  onChange={(e) => setFacility(e.target.value)}
                  placeholder="例: 〇〇太陽光発電所"
                />
              </div>
              <p className="text-xs text-muted-foreground">
                設備の詳細（接地対象物・回路数・機器など）は追加後の編集画面で設定します。
              </p>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setOpen(false)}>キャンセル</Button>
              <Button
                onClick={() => {
                  if (!name) return;
                  const id = `client-${Date.now()}`;
                  upsertClient({
                    id,
                    name,
                    facility_name: facility,
                    inspector: "本田修",
                    ground_items: [],
                    hv_circuits: [],
                    array_count: 0,
                    array_value_min: 3,
                    array_value_max: 5,
                    box_count: 0,
                    box_measure: false,
                    box_value_min: 3,
                    box_value_max: 5,
                    lv_circuit_count: 0,
                    lv_circuit_start: 101,
                    lv_rp_min: 0.8,
                    lv_rp_max: 1.6,
                    lv_rn_min: 0.7,
                    lv_rn_max: 1.3,
                    pas_equipment_id: "",
                    dgr_relay_id: "",
                    ocr_equipment_id: "",
                    ovgr_equipment_id: "",
                    measuring_instrument_ids: [],
                  });
                  setOpen(false);
                  setName("");
                  setFacility("");
                }}
              >
                追加
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      <div className="space-y-2">
        {clients.length === 0 ? (
          <Card>
            <CardContent className="py-12 text-center text-muted-foreground">
              <Building2 className="h-10 w-10 mx-auto mb-3 opacity-40" />
              まだクライアントがありません
            </CardContent>
          </Card>
        ) : (
          clients.map((c) => (
            <Card
              key={c.id}
              className="cursor-pointer hover:bg-secondary/30 transition"
              onClick={() => onSelect(c.id)}
            >
              <CardContent className="py-4 flex items-center gap-4">
                <Building2 className="h-5 w-5 text-muted-foreground" />
                <div className="flex-1">
                  <p className="font-medium">{c.name}</p>
                  <p className="text-sm text-muted-foreground">{c.facility_name || "（設備名未設定）"}</p>
                </div>
                <div className="text-xs text-muted-foreground">
                  接地{c.ground_items.length} / 回路{c.lv_circuit_count} / アレイ{c.array_count}
                </div>
                <ChevronRight className="h-4 w-4 text-muted-foreground" />
              </CardContent>
            </Card>
          ))
        )}
      </div>
    </div>
  );
}
