"use client";

import { useState } from "react";
import { Sparkles, Building2, FileText } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useInspectionStore } from "../store";
import { generateReport } from "../random";
import { applySavedConfig } from "../output-config";
import type { ReportKind } from "../types";

export function GenerateView({ onGenerated }: { onGenerated: () => void }) {
  const clients = useInspectionStore((s) => s.clients);
  const equipments = useInspectionStore((s) => s.equipments);
  const instruments = useInspectionStore((s) => s.instruments);
  const setCurrentReport = useInspectionStore((s) => s.setCurrentReport);
  const getLastReportConfig = useInspectionStore((s) => s.getLastReportConfig);

  const [selectedId, setSelectedId] = useState<string>(clients[0]?.id ?? "");
  const [reportKind, setReportKind] = useState<ReportKind>("annual");
  const today = new Date();
  const [year, setYear] = useState<number>(today.getFullYear() - 2018); // 令和=西暦-2018
  const [month, setMonth] = useState<number>(today.getMonth() + 1);
  const [day, setDay] = useState<number>(today.getDate());

  const client = clients.find((c) => c.id === selectedId);

  const handleGenerate = () => {
    if (!client) return;
    const eqMap = new Map(equipments.map((e) => [e.id, e]));
    const instMap = new Map(instruments.map((m) => [m.id, m]));
    const r = applySavedConfig(
      generateReport(client, eqMap, instMap, year, month, day, reportKind),
      getLastReportConfig(client.id, reportKind),
    );
    setCurrentReport(r, client.id);
    onGenerated();
  };

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h2 className="text-2xl font-semibold mb-1">報告書を作る</h2>
        <p className="text-muted-foreground text-sm">
          クライアントを選んで「生成」を押すと、検査項目の値が正常範囲内で自動生成されます。
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">報告書の種類を選ぶ</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {[
            {
              value: "annual" as const,
              title: "自家用電気工作物年次点検試験報告書",
              note: "毎年1回の年次点検。Wordは島津組ひな形、Excelは倉吉第1ひな形を使います。",
            },
            {
              value: "completion" as const,
              title: "電力設備試験結果報告書（竣工報告書）",
              note: "新設時など初回用。Excelは大崎1ひな形を使います。Wordはひな形追加後に出力できます。",
            },
          ].map((item) => (
            <label
              key={item.value}
              className={`flex items-start gap-3 p-3 rounded-md cursor-pointer border ${
                reportKind === item.value
                  ? "border-primary bg-primary/5"
                  : "border-border hover:bg-secondary/30"
              }`}
            >
              <input
                type="radio"
                name="reportKind"
                className="sr-only"
                checked={reportKind === item.value}
                onChange={() => setReportKind(item.value)}
              />
              <FileText className="h-5 w-5 text-muted-foreground mt-0.5" />
              <div>
                <p className="font-medium">{item.title}</p>
                <p className="text-sm text-muted-foreground">{item.note}</p>
              </div>
            </label>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">クライアントを選ぶ</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {clients.length === 0 ? (
            <p className="text-sm text-muted-foreground py-4">
              まずクライアントを登録してください
            </p>
          ) : (
            clients.map((c) => (
              <label
                key={c.id}
                className={`flex items-center gap-3 p-3 rounded-md cursor-pointer border ${
                  selectedId === c.id
                    ? "border-primary bg-primary/5"
                    : "border-border hover:bg-secondary/30"
                }`}
              >
                <input
                  type="radio"
                  name="client"
                  className="sr-only"
                  checked={selectedId === c.id}
                  onChange={() => setSelectedId(c.id)}
                />
                <Building2 className="h-5 w-5 text-muted-foreground" />
                <div className="flex-1">
                  <p className="font-medium">{c.name}</p>
                  <p className="text-sm text-muted-foreground">{c.facility_name}</p>
                </div>
                <div className="text-xs text-muted-foreground">
                  接地{c.ground_items.length} / 回路{c.lv_circuit_count} / アレイ{c.array_count}
                </div>
              </label>
            ))
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">実施日</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-3 gap-4 max-w-md">
            <div>
              <Label className="text-xs">令和</Label>
              <Input type="number" className="mt-1" value={year} onChange={(e) => setYear(Number(e.target.value))} />
            </div>
            <div>
              <Label className="text-xs">月</Label>
              <Input type="number" className="mt-1" value={month} onChange={(e) => setMonth(Number(e.target.value))} />
            </div>
            <div>
              <Label className="text-xs">日</Label>
              <Input type="number" className="mt-1" value={day} onChange={(e) => setDay(Number(e.target.value))} />
            </div>
          </div>
          <p className="text-xs text-muted-foreground mt-2">
            天候・温度・湿度はランダム生成されます（後で変更可能）
          </p>
        </CardContent>
      </Card>

      <div className="flex justify-end">
        <Button size="lg" disabled={!client} onClick={handleGenerate}>
          <Sparkles className="h-4 w-4 mr-2" />
          報告書を生成する
        </Button>
      </div>
    </div>
  );
}
