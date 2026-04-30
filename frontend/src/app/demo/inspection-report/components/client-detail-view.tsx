"use client";

import { useState } from "react";
import { ArrowLeft, Trash2, Plus, X } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useInspectionStore } from "../store";
import type { Client, GroundItem, HvCircuit } from "../types";

export function ClientDetailView({
  clientId,
  onBack,
}: {
  clientId: string;
  onBack: () => void;
}) {
  const client = useInspectionStore((s) => s.clients.find((c) => c.id === clientId));
  const equipments = useInspectionStore((s) => s.equipments);
  const instruments = useInspectionStore((s) => s.instruments);
  const upsertClient = useInspectionStore((s) => s.upsertClient);
  const removeClient = useInspectionStore((s) => s.removeClient);

  const [draft, setDraft] = useState<Client | undefined>(client);

  if (!draft) {
    return (
      <div>
        <Button variant="ghost" size="sm" onClick={onBack}>
          <ArrowLeft className="h-4 w-4 mr-2" />戻る
        </Button>
        <p className="mt-8 text-muted-foreground">クライアントが見つかりません</p>
      </div>
    );
  }

  const update = (patch: Partial<Client>) => setDraft((d) => (d ? { ...d, ...patch } : d));

  const save = () => {
    upsertClient(draft);
    onBack();
  };

  const equipByCategory = (cat: string) => equipments.filter((e) => e.category === cat);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <Button variant="ghost" size="sm" onClick={onBack}>
          <ArrowLeft className="h-4 w-4 mr-2" />クライアント一覧に戻る
        </Button>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              if (confirm("このクライアントを削除しますか？")) {
                removeClient(draft.id);
                onBack();
              }
            }}
          >
            <Trash2 className="h-4 w-4 mr-2" />削除
          </Button>
          <Button onClick={save}>保存</Button>
        </div>
      </div>

      {/* 基本情報 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">基本情報</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label>会社名</Label>
              <Input className="mt-2" value={draft.name} onChange={(e) => update({ name: e.target.value })} />
            </div>
            <div>
              <Label>設備名</Label>
              <Input
                className="mt-2"
                value={draft.facility_name}
                onChange={(e) => update({ facility_name: e.target.value })}
              />
            </div>
            <div>
              <Label>点検者</Label>
              <Input
                className="mt-2"
                value={draft.inspector}
                onChange={(e) => update({ inspector: e.target.value })}
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* 機器の紐付け */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">この設備で使う機器</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <EquipmentSelect
            label="開閉器（PAS）"
            value={draft.pas_equipment_id}
            options={equipByCategory("pas")}
            onChange={(v) => update({ pas_equipment_id: v })}
          />
          <EquipmentSelect
            label="地絡方向継電器（DGR）"
            value={draft.dgr_relay_id}
            options={equipByCategory("dgr_relay")}
            onChange={(v) => update({ dgr_relay_id: v })}
          />
          <EquipmentSelect
            label="過電流継電器（OCR）"
            value={draft.ocr_equipment_id}
            options={equipByCategory("ocr")}
            onChange={(v) => update({ ocr_equipment_id: v })}
          />
          <EquipmentSelect
            label="地絡過電圧継電器（OVGR）"
            value={draft.ovgr_equipment_id}
            options={equipByCategory("ovgr")}
            onChange={(v) => update({ ovgr_equipment_id: v })}
          />
        </CardContent>
      </Card>

      {/* 接地抵抗 対象物 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">接地抵抗 対象物</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {draft.ground_items.map((g, idx) => (
            <div key={idx} className="grid grid-cols-12 gap-2 items-end">
              <div className="col-span-4">
                <Label className="text-xs">対象物名</Label>
                <Input
                  className="mt-1"
                  value={g.name}
                  onChange={(e) => {
                    const next = [...draft.ground_items];
                    next[idx] = { ...g, name: e.target.value };
                    update({ ground_items: next });
                  }}
                />
              </div>
              <div className="col-span-2">
                <Label className="text-xs">種別</Label>
                <Input
                  className="mt-1"
                  value={g.type}
                  onChange={(e) => {
                    const next = [...draft.ground_items];
                    next[idx] = { ...g, type: e.target.value };
                    update({ ground_items: next });
                  }}
                />
              </div>
              <div className="col-span-2">
                <Label className="text-xs">最小</Label>
                <Input
                  className="mt-1"
                  type="number"
                  value={g.range_min}
                  onChange={(e) => {
                    const next = [...draft.ground_items];
                    next[idx] = { ...g, range_min: Number(e.target.value) };
                    update({ ground_items: next });
                  }}
                />
              </div>
              <div className="col-span-2">
                <Label className="text-xs">最大</Label>
                <Input
                  className="mt-1"
                  type="number"
                  value={g.range_max}
                  onChange={(e) => {
                    const next = [...draft.ground_items];
                    next[idx] = { ...g, range_max: Number(e.target.value) };
                    update({ ground_items: next });
                  }}
                />
              </div>
              <div className="col-span-2 flex">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    update({ ground_items: draft.ground_items.filter((_, i) => i !== idx) });
                  }}
                >
                  <X className="h-4 w-4" />
                </Button>
              </div>
            </div>
          ))}
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              const next: GroundItem = { name: "", type: "EA", range_min: 5, range_max: 9, note: "" };
              update({ ground_items: [...draft.ground_items, next] });
            }}
          >
            <Plus className="h-4 w-4 mr-2" />対象物を追加
          </Button>
        </CardContent>
      </Card>

      {/* 構成（数） */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">設備規模</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-3 gap-4">
          <div>
            <Label>太陽電池アレイ数</Label>
            <Input
              type="number"
              className="mt-2"
              value={draft.array_count}
              onChange={(e) => update({ array_count: Number(e.target.value) })}
            />
            <div className="grid grid-cols-2 gap-2 mt-2">
              <Input
                type="number"
                placeholder="最小"
                value={draft.array_value_min}
                onChange={(e) => update({ array_value_min: Number(e.target.value) })}
              />
              <Input
                type="number"
                placeholder="最大"
                value={draft.array_value_max}
                onChange={(e) => update({ array_value_max: Number(e.target.value) })}
              />
            </div>
            <p className="text-xs text-muted-foreground mt-1">測定値の正常範囲（Ω）</p>
          </div>

          <div>
            <Label>接続箱数</Label>
            <Input
              type="number"
              className="mt-2"
              value={draft.box_count}
              onChange={(e) => update({ box_count: Number(e.target.value) })}
            />
            <div className="flex items-center gap-2 mt-2 text-xs">
              <input
                type="checkbox"
                checked={draft.box_measure}
                onChange={(e) => update({ box_measure: e.target.checked })}
              />
              <span>接続箱を測定する（チェックなし＝「－」固定）</span>
            </div>
          </div>

          <div>
            <Label>低圧回路数</Label>
            <Input
              type="number"
              className="mt-2"
              value={draft.lv_circuit_count}
              onChange={(e) => update({ lv_circuit_count: Number(e.target.value) })}
            />
            <Input
              type="number"
              className="mt-2"
              placeholder="開始番号"
              value={draft.lv_circuit_start}
              onChange={(e) => update({ lv_circuit_start: Number(e.target.value) })}
            />
            <p className="text-xs text-muted-foreground mt-1">回路番号 例:101〜</p>
          </div>
        </CardContent>
      </Card>

      {/* 計測器の紐付け */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">使用する計測器</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {instruments.map((m) => {
            const checked = draft.measuring_instrument_ids.includes(m.id);
            return (
              <label key={m.id} className="flex items-center gap-3 text-sm">
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={(e) => {
                    const ids = e.target.checked
                      ? [...draft.measuring_instrument_ids, m.id]
                      : draft.measuring_instrument_ids.filter((x) => x !== m.id);
                    update({ measuring_instrument_ids: ids });
                  }}
                />
                <span className="font-medium">{m.name}</span>
                <span className="text-muted-foreground">{m.maker} / {m.model}</span>
              </label>
            );
          })}
          <p className="text-xs text-muted-foreground mt-2">最大8台まで使われます（雛形の表が8行）</p>
        </CardContent>
      </Card>
    </div>
  );
}

function EquipmentSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: { id: string; maker: string; model: string }[];
  onChange: (v: string) => void;
}) {
  return (
    <div className="grid grid-cols-3 gap-4 items-center">
      <Label>{label}</Label>
      <div className="col-span-2">
        <Select value={value || "__none__"} onValueChange={(v) => onChange(v === "__none__" ? "" : v)}>
          <SelectTrigger>
            <SelectValue placeholder="未選択" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__none__">未選択</SelectItem>
            {options.map((o) => (
              <SelectItem key={o.id} value={o.id}>
                {o.maker} / {o.model}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}
