"use client";

import { useState } from "react";
import { ArrowLeft, FileDown, FileSpreadsheet, Sliders, CheckCircle2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useInspectionStore } from "../store";
import { downloadDocx } from "../docx-generator";
import { downloadExcel } from "../excel-generator";
import { OUTPUT_PAGE_DEFINITIONS, updateReportOutputConfig } from "../output-config";
import type { Judge, ReportData } from "../types";

const JUDGE_OPTIONS: Judge[] = ["良", "不良", "－", ""];
const SUMMARY_JUDGE_LABELS: Record<Judge, string> = {
  良: "出力する（良）",
  不良: "出力する（不良）",
  "－": "出力する（－）",
  "": "出力しない",
};

function JudgeButton({
  value,
  onChange,
  options = JUDGE_OPTIONS,
  labels,
}: {
  value: Judge | string;
  onChange: (v: Judge) => void;
  options?: readonly Judge[];
  labels?: Partial<Record<Judge, string>>;
}) {
  return (
    <div className="inline-flex rounded-md border border-border overflow-hidden text-xs">
      {options.map((o) => (
        <button
          key={o}
          onClick={() => onChange(o)}
          className={`px-2 py-1 transition ${
            value === o
              ? o === "不良"
                ? "bg-destructive text-destructive-foreground"
                : "bg-primary text-primary-foreground"
              : "bg-background hover:bg-secondary"
          }`}
        >
          {labels?.[o] ?? (o === "" ? "出力しない" : o)}
        </button>
      ))}
    </div>
  );
}

export function ConfirmView({
  onBack,
  onComplete,
}: {
  onBack: () => void;
  onComplete: () => void;
}) {
  const report = useInspectionStore((s) => s.currentReport);
  const clientId = useInspectionStore((s) => s.currentClientId);
  const client = useInspectionStore((s) => s.clients.find((c) => c.id === clientId));
  const updateReport = useInspectionStore((s) => s.updateReport);
  const saveDirHandle = useInspectionStore((s) => s.saveDirHandle);

  const [downloading, setDownloading] = useState(false);
  const [downloadMsg, setDownloadMsg] = useState<string | null>(null);

  if (!report || !client) {
    return (
      <div>
        <Button variant="ghost" size="sm" onClick={onBack}>
          <ArrowLeft className="h-4 w-4 mr-2" />戻る
        </Button>
        <p className="mt-8 text-muted-foreground">
          先に「報告書を作る」から生成してください
        </p>
      </div>
    );
  }

  const update = (patch: Partial<ReportData>) => updateReport(patch);
  const updateOutput = (patch: Parameters<typeof updateReportOutputConfig>[1]) => {
    update(updateReportOutputConfig(report, patch));
  };
  const reportKindLabel =
    report.report_kind === "completion"
      ? "電力設備試験結果報告書（竣工報告書）"
      : "自家用電気工作物年次点検試験報告書";

  const handleDownloadWord = async () => {
    setDownloading(true);
    setDownloadMsg(null);
    try {
      const result = await downloadDocx(report, client, saveDirHandle);
      setDownloadMsg(`Word出力完了：${result.savedTo}`);
    } catch (e) {
      console.error(e);
      setDownloadMsg(`エラー：${(e as Error).message}`);
    } finally {
      setDownloading(false);
    }
  };

  const handleDownloadExcel = async () => {
    setDownloading(true);
    setDownloadMsg(null);
    try {
      const result = await downloadExcel(report, client, saveDirHandle);
      setDownloadMsg(`Excel出力完了: ${result.savedTo}`);
    } catch (e) {
      console.error(e);
      setDownloadMsg(`エラー: ${(e as Error).message}`);
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <Button variant="ghost" size="sm" onClick={onBack}>
          <ArrowLeft className="h-4 w-4 mr-2" />クライアント選択に戻る
        </Button>
        <div className="flex gap-2">
          <Button onClick={handleDownloadWord} disabled={downloading}>
            <FileDown className="h-4 w-4 mr-2" />
            Wordをダウンロード
          </Button>
          <Button variant="outline" onClick={handleDownloadExcel} disabled={downloading}>
            <FileSpreadsheet className="h-4 w-4 mr-2" />
            Excelをダウンロード
          </Button>
        </div>
      </div>

      {downloadMsg && (
        <div className="p-3 rounded-md bg-primary/10 text-sm flex items-center gap-2">
          <CheckCircle2 className="h-4 w-4 text-primary" />
          {downloadMsg}
        </div>
      )}

      {/* ヘッダー */}
      <Card>
        <CardContent className="py-4">
          <div className="flex items-center gap-4 text-sm">
            <Badge variant="outline">{client.name}</Badge>
            <Badge variant="secondary">{reportKindLabel}</Badge>
            <span className="text-muted-foreground">{client.facility_name}</span>
            <span className="text-muted-foreground">
              令和{report.year_wareki}年{report.month}月{report.day}日
            </span>
            <span className="text-muted-foreground">
              {report.weather} / {report.temperature}℃ / {report.humidity}%
            </span>
          </div>
        </CardContent>
      </Card>

      <Tabs defaultValue="numbers">
        <TabsList>
          <TabsTrigger value="output">出力ページ</TabsTrigger>
          <TabsTrigger value="numbers">数値（{countNumbers(report)}箇所）</TabsTrigger>
          <TabsTrigger value="judges">判定（{countJudges(report)}箇所）</TabsTrigger>
          <TabsTrigger value="cover">表紙</TabsTrigger>
        </TabsList>

        <TabsContent value="output" className="space-y-4">
          <SectionCard title="出力ページ設定">
            <div className="space-y-3">
              {OUTPUT_PAGE_DEFINITIONS.map((page) => {
                const checked =
                  page.key === "lvInsulation"
                    ? report.outputConfig.lvInsulationPageCount > 0
                    : report.outputConfig.pages[page.key];
                return (
                  <div
                    key={page.key}
                    className="flex items-center justify-between gap-4 rounded-md border border-border px-3 py-2"
                  >
                    <div>
                      <Label className="text-sm font-medium">{page.label}</Label>
                      <p className="text-xs text-muted-foreground">{page.description}</p>
                    </div>
                    <Switch
                      checked={checked}
                      onCheckedChange={(next) => {
                        if (page.key === "lvInsulation") {
                          updateOutput({ lvInsulationPageCount: next ? 1 : 0 });
                          return;
                        }
                        updateOutput({ pages: { [page.key]: next } });
                      }}
                    />
                  </div>
                );
              })}
            </div>
          </SectionCard>

          <SectionCard title="低圧絶縁の枚数">
            <div className="max-w-xs">
              <Label className="text-xs text-muted-foreground">なし / 1〜5枚</Label>
              <Input
                type="number"
                min={0}
                max={5}
                className="mt-1"
                value={report.outputConfig.lvInsulationPageCount}
                onChange={(e) => updateOutput({ lvInsulationPageCount: Number(e.target.value) })}
              />
              <p className="mt-2 text-xs text-muted-foreground">
                0にすると低圧絶縁ページを出力しません。複数枚の実出力はひな形確認後に対応します。
              </p>
            </div>
          </SectionCard>
        </TabsContent>

        {/* 数値タブ */}
        <TabsContent value="numbers" className="space-y-4">
          {/* 接地抵抗 */}
          <SectionCard title="接地抵抗">
            <div className="space-y-2">
              {report.ground.map((g, i) => (
                <div key={i} className="grid grid-cols-12 gap-2 items-center text-sm">
                  <span className="col-span-5 text-muted-foreground">{g.name}</span>
                  <span className="col-span-2 text-xs text-muted-foreground">{g.type}</span>
                  <Input
                    className="col-span-3"
                    value={g.value}
                    onChange={(e) => {
                      const next = [...report.ground];
                      next[i] = { ...g, value: e.target.value };
                      update({ ground: next });
                    }}
                  />
                  <span className="col-span-2 text-xs text-muted-foreground">Ω</span>
                </div>
              ))}
            </div>
          </SectionCard>

          {/* 高圧絶縁抵抗 */}
          <SectionCard title="高圧関係 絶縁抵抗試験">
            <div className="space-y-2">
              {report.hv.map((h, i) => (
                <div key={i} className="grid grid-cols-12 gap-2 items-center text-sm">
                  <span className="col-span-7 text-muted-foreground truncate">{h.name}</span>
                  <Input
                    className="col-span-5"
                    value={h.value}
                    onChange={(e) => {
                      const next = [...report.hv];
                      next[i] = { ...h, value: e.target.value };
                      update({ hv: next });
                    }}
                  />
                </div>
              ))}
            </div>
          </SectionCard>

          {/* DGR */}
          <SectionCard title="地絡方向継電器試験（DGR）">
            <div className="grid grid-cols-2 gap-3 text-sm">
              <NumField label="動作電圧 最小値 (V)" value={report.dgr.v_min} onChange={(v) => update({ dgr: { ...report.dgr, v_min: v } })} />
              <NumField label="動作電流 最小値 (A)" value={report.dgr.i_min} onChange={(v) => update({ dgr: { ...report.dgr, i_min: v } })} />
              <NumField label="位相角 進み" value={report.dgr.phase_lead} onChange={(v) => update({ dgr: { ...report.dgr, phase_lead: v } })} />
              <NumField label="位相角 遅れ" value={report.dgr.phase_lag} onChange={(v) => update({ dgr: { ...report.dgr, phase_lag: v } })} />
              <NumField label="動作時間 試験電流A" value={report.dgr.t_i_a} onChange={(v) => update({ dgr: { ...report.dgr, t_i_a: v } })} />
              <NumField label="動作時間 試験電流B" value={report.dgr.t_i_b} onChange={(v) => update({ dgr: { ...report.dgr, t_i_b: v } })} />
              <NumField label="動作時間 a (秒)" value={report.dgr.t_a} onChange={(v) => update({ dgr: { ...report.dgr, t_a: v } })} />
              <NumField label="動作時間 b (秒)" value={report.dgr.t_b} onChange={(v) => update({ dgr: { ...report.dgr, t_b: v } })} />
              <NumField label="連動試験 動作時間" value={report.dgr.linked_time} onChange={(v) => update({ dgr: { ...report.dgr, linked_time: v } })} />
            </div>
          </SectionCard>

          {/* OCR */}
          <SectionCard title="過電流継電器試験（OCR）">
            <div className="grid grid-cols-2 gap-3 text-sm">
              <NumField label="動作電流 R相 (A)" value={report.ocr.r_current} onChange={(v) => update({ ocr: { ...report.ocr, r_current: v } })} />
              <NumField label="動作電流 T相 (A)" value={report.ocr.t_current} onChange={(v) => update({ ocr: { ...report.ocr, t_current: v } })} />
              <NumField label="連動300% R相" value={report.ocr.r_300} onChange={(v) => update({ ocr: { ...report.ocr, r_300: v } })} />
              <NumField label="連動300% T相" value={report.ocr.t_300} onChange={(v) => update({ ocr: { ...report.ocr, t_300: v } })} />
              <NumField label="VCB連動動作時間 (秒)" value={report.ocr.vcb_time} onChange={(v) => update({ ocr: { ...report.ocr, vcb_time: v } })} />
            </div>
          </SectionCard>

          {/* OVGR */}
          <SectionCard title="地絡過電圧継電器試験（OVGR）">
            <div className="grid grid-cols-2 gap-3 text-sm">
              <NumField label="零相電圧3.5% A" value={report.ovgr.v_op_3_5_a} onChange={(v) => update({ ovgr: { ...report.ovgr, v_op_3_5_a: v } })} />
              <NumField label="零相電圧3.5% B" value={report.ovgr.v_op_3_5_b} onChange={(v) => update({ ovgr: { ...report.ovgr, v_op_3_5_b: v } })} />
              <NumField label="動作時間 3% (S)" value={report.ovgr.t_op_3} onChange={(v) => update({ ovgr: { ...report.ovgr, t_op_3: v } })} />
            </div>
          </SectionCard>

          {/* アレイ */}
          <SectionCard title={`太陽電池アレイ（${report.array.length}台）`}>
            <div className="grid grid-cols-4 gap-2 text-sm">
              {report.array.map((a, i) => (
                <div key={i} className="flex items-center gap-1">
                  <span className="text-xs text-muted-foreground w-6">#{a.id}</span>
                  <Input
                    className="h-8"
                    value={a.value}
                    onChange={(e) => {
                      const next = [...report.array];
                      next[i] = { ...a, value: e.target.value };
                      update({ array: next });
                    }}
                  />
                </div>
              ))}
            </div>
          </SectionCard>

          {/* 低圧 */}
          <SectionCard title={`低圧絶縁抵抗（${report.lv.length}回路）`}>
            <div className="space-y-1 text-sm">
              <div className="grid grid-cols-12 gap-2 text-xs text-muted-foreground border-b pb-1">
                <span className="col-span-2">回路</span>
                <span className="col-span-5">rp</span>
                <span className="col-span-5">rn</span>
              </div>
              {report.lv.map((l, i) => (
                <div key={i} className="grid grid-cols-12 gap-2 items-center">
                  <span className="col-span-2 text-muted-foreground">{l.id}</span>
                  <Input
                    className="col-span-5 h-8"
                    value={l.rp}
                    onChange={(e) => {
                      const next = [...report.lv];
                      next[i] = { ...l, rp: e.target.value };
                      update({ lv: next });
                    }}
                  />
                  <Input
                    className="col-span-5 h-8"
                    value={l.rn}
                    onChange={(e) => {
                      const next = [...report.lv];
                      next[i] = { ...l, rn: e.target.value };
                      update({ lv: next });
                    }}
                  />
                </div>
              ))}
            </div>
          </SectionCard>
        </TabsContent>

        {/* 判定タブ */}
        <TabsContent value="judges" className="space-y-4">
          <SectionCard title="総括チェック表（23項目）">
            <p className="text-xs text-muted-foreground mb-3">
              「出力しない」を選ぶと、総括表では空欄になり、対応する詳細ページやExcelシートも出力対象から外れます。
            </p>
            <div className="space-y-2 text-sm">
              {report.summary.map((s, i) => (
                <div
                  key={s.id}
                  className={`flex items-center justify-between gap-3 ${
                    s.result === "" ? "opacity-40" : ""
                  }`}
                >
                  <span className="text-muted-foreground">
                    {s.no}. {s.label}
                    {s.result === "" && <span className="ml-2 text-xs">（出力されません）</span>}
                  </span>
                  <JudgeButton
                    value={s.result}
                    labels={SUMMARY_JUDGE_LABELS}
                    onChange={(v) => {
                      const next = [...report.summary];
                      next[i] = { ...s, result: v };
                      update({ summary: next });
                    }}
                  />
                </div>
              ))}
            </div>
          </SectionCard>

          <SectionCard title="外観点検">
            <div className="space-y-2 text-sm">
              {report.external.map((e, i) => (
                <div key={e.id} className="flex items-center justify-between gap-3">
                  <span className="text-muted-foreground">{e.label}</span>
                  <JudgeButton
                    value={e.result}
                    onChange={(v) => {
                      const next = [...report.external];
                      next[i] = { ...e, result: v };
                      update({ external: next });
                    }}
                  />
                </div>
              ))}
            </div>
          </SectionCard>

          <SectionCard title="接地抵抗 / 高圧絶縁抵抗 / 試験 結果">
            <div className="space-y-2 text-sm">
              {report.ground.map((g, i) => (
                <div key={i} className="flex items-center justify-between gap-3">
                  <span className="text-muted-foreground">接地：{g.name}</span>
                  <JudgeButton
                    value={g.judge}
                    onChange={(v) => {
                      const next = [...report.ground];
                      next[i] = { ...g, judge: v };
                      update({ ground: next });
                    }}
                  />
                </div>
              ))}
              <div className="flex items-center justify-between gap-3 pt-2 border-t">
                <span className="text-muted-foreground">DGR 結果</span>
                <JudgeButton
                  value={report.dgr.judge}
                  onChange={(v) => update({ dgr: { ...report.dgr, judge: v } })}
                />
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-muted-foreground">OCR 結果</span>
                <JudgeButton
                  value={report.ocr.judge}
                  onChange={(v) => update({ ocr: { ...report.ocr, judge: v } })}
                />
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-muted-foreground">OVGR 結果</span>
                <JudgeButton
                  value={report.ovgr.judge}
                  onChange={(v) => update({ ovgr: { ...report.ovgr, judge: v } })}
                />
              </div>
            </div>
          </SectionCard>

          <SectionCard title={`太陽電池アレイ判定（${report.array.length}台）`}>
            <div className="grid grid-cols-4 gap-2 text-sm">
              {report.array.map((a, i) => (
                <div key={i} className="flex items-center gap-2">
                  <span className="text-xs text-muted-foreground w-8">#{a.id}</span>
                  <JudgeButton
                    value={a.judge}
                    options={["良", "不良"]}
                    onChange={(v) => {
                      const next = [...report.array];
                      next[i] = { ...a, judge: v };
                      update({ array: next });
                    }}
                  />
                </div>
              ))}
            </div>
          </SectionCard>

          <SectionCard title={`低圧 判定（${report.lv.length}回路）`}>
            <div className="grid grid-cols-4 gap-2 text-sm">
              {report.lv.map((l, i) => (
                <div key={i} className="flex items-center gap-2">
                  <span className="text-xs text-muted-foreground w-12">#{l.id}</span>
                  <JudgeButton
                    value={l.judge}
                    options={["良", "不良"]}
                    onChange={(v) => {
                      const next = [...report.lv];
                      next[i] = { ...l, judge: v };
                      update({ lv: next });
                    }}
                  />
                </div>
              ))}
            </div>
          </SectionCard>
        </TabsContent>

        {/* 表紙タブ */}
        <TabsContent value="cover" className="space-y-4">
          <SectionCard title="実施日・気象条件">
            <div className="grid grid-cols-3 gap-3 text-sm">
              <div>
                <span className="text-xs text-muted-foreground">令和</span>
                <Input
                  type="number"
                  className="mt-1"
                  value={report.year_wareki}
                  onChange={(e) => update({ year_wareki: Number(e.target.value) })}
                />
              </div>
              <div>
                <span className="text-xs text-muted-foreground">月</span>
                <Input
                  type="number"
                  className="mt-1"
                  value={report.month}
                  onChange={(e) => update({ month: Number(e.target.value) })}
                />
              </div>
              <div>
                <span className="text-xs text-muted-foreground">日</span>
                <Input
                  type="number"
                  className="mt-1"
                  value={report.day}
                  onChange={(e) => update({ day: Number(e.target.value) })}
                />
              </div>
              <div>
                <span className="text-xs text-muted-foreground">天候</span>
                <Input
                  className="mt-1"
                  value={report.weather}
                  onChange={(e) => update({ weather: e.target.value })}
                />
              </div>
              <div>
                <span className="text-xs text-muted-foreground">温度 (℃)</span>
                <Input
                  type="number"
                  className="mt-1"
                  value={report.temperature}
                  onChange={(e) => update({ temperature: Number(e.target.value) })}
                />
              </div>
              <div>
                <span className="text-xs text-muted-foreground">湿度 (%)</span>
                <Input
                  type="number"
                  className="mt-1"
                  value={report.humidity}
                  onChange={(e) => update({ humidity: Number(e.target.value) })}
                />
              </div>
              <div className="col-span-3">
                <span className="text-xs text-muted-foreground">点検者</span>
                <Input
                  className="mt-1"
                  value={report.inspector}
                  onChange={(e) => update({ inspector: e.target.value })}
                />
              </div>
            </div>
          </SectionCard>
        </TabsContent>
      </Tabs>
    </div>
  );
}

function SectionCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm flex items-center gap-2">
          <Sliders className="h-3.5 w-3.5 text-muted-foreground" />
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

function NumField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div>
      <span className="text-xs text-muted-foreground">{label}</span>
      <Input className="mt-1 h-8" value={value} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

function countNumbers(r: ReportData): number {
  return (
    r.ground.length +
    r.hv.length +
    9 + // dgr
    5 + // ocr
    3 + // ovgr
    r.array.length +
    r.lv.length * 2
  );
}

function countJudges(r: ReportData): number {
  return r.summary.length + r.external.length + r.ground.length + r.array.length + r.lv.length + 3;
}
