"use client";

import { useState } from "react";
import { ArrowLeft, CheckCircle2, Eye, Sliders } from "lucide-react";
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
import {
  getOutputPageKeyForSummaryId,
  getOutputPagesForReportKind,
  updateReportOutputConfig,
} from "../output-config";
import type { Client, Judge, ReportData } from "../types";

const JUDGE_OPTIONS: Judge[] = ["良", "不良", "－"];

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
  const [previewIndex, setPreviewIndex] = useState(0);

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
          <Button
            onClick={handleDownloadWord}
            disabled={downloading}
            className="bg-[#185ABD] text-white hover:bg-[#2B579A]"
          >
            <span className="mr-2 inline-flex h-5 w-5 items-center justify-center rounded-sm bg-white text-xs font-bold text-[#185ABD]">
              W
            </span>
            Wordで出力
          </Button>
          <Button
            onClick={handleDownloadExcel}
            disabled={downloading}
            className="bg-[#107C41] text-white hover:bg-[#217346]"
          >
            <span className="mr-2 inline-flex h-5 w-5 items-center justify-center rounded-sm bg-white text-xs font-bold text-[#107C41]">
              X
            </span>
            Excelで出力
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

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_430px]">
        <Tabs defaultValue="output" className="min-w-0">
          <TabsList>
            <TabsTrigger value="output">提出するページ</TabsTrigger>
            <TabsTrigger value="details">検査内容（{countDetails(report)}箇所）</TabsTrigger>
            <TabsTrigger value="cover">表紙</TabsTrigger>
          </TabsList>

        <TabsContent value="output" className="space-y-4">
          <div className="rounded-md border border-primary/30 bg-primary/5 px-4 py-3">
            <p className="text-sm font-medium">Excel・Wordに含めるページを選びます</p>
            <p className="mt-1 text-xs text-muted-foreground">
              ONのページだけを出力します。OFFにしたページは総括チェック表と詳細シートの両方から外れます。
            </p>
          </div>

          <SectionCard title="提出する詳細ページ">
            <div className="space-y-3">
              {getOutputPagesForReportKind(report.report_kind).map((page) => {
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
                    <div className="flex items-center gap-3">
                      <span className={`text-xs ${checked ? "text-primary" : "text-muted-foreground"}`}>
                        {checked ? "出力する" : "出力しない"}
                      </span>
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
                  </div>
                );
              })}
            </div>
          </SectionCard>

          <SectionCard title="低圧絶縁の枚数">
            <div>
              <Label className="text-xs text-muted-foreground">なし / 1〜5枚</Label>
              <div className="mt-2 inline-flex rounded-md border border-border overflow-hidden text-sm">
                {[0, 1, 2, 3, 4, 5].map((count) => (
                  <button
                    key={count}
                    type="button"
                    className={`px-3 py-2 transition ${
                      report.outputConfig.lvInsulationPageCount === count
                        ? "bg-primary text-primary-foreground"
                        : "bg-background hover:bg-secondary"
                    }`}
                    onClick={() => updateOutput({ lvInsulationPageCount: count })}
                  >
                    {count === 0 ? "なし" : `${count}枚`}
                  </button>
                ))}
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                同じ低圧絶縁測定記録を、提出先に合わせて必要枚数分出力します。
              </p>
            </div>
          </SectionCard>

          <SectionCard title="総括チェック表だけの項目">
            <div className="space-y-2">
              {report.summary
                .filter((item) => !getOutputPageKeyForSummaryId(item.id))
                .map((item) => {
                  const checked = report.outputConfig.summaryVisibility[item.id] ?? item.result !== "";
                  return (
                    <div
                      key={item.id}
                      className="flex items-center justify-between gap-4 rounded-md border border-border px-3 py-2"
                    >
                      <div>
                        <Label className="text-sm font-medium">
                          {item.no}. {item.label}
                        </Label>
                        <p className="text-xs text-muted-foreground">総括チェック表への表示</p>
                      </div>
                      <Switch
                        checked={checked}
                        onCheckedChange={(next) =>
                          updateOutput({ summaryVisibility: { [item.id]: next } })
                        }
                      />
                    </div>
                  );
                })}
            </div>
          </SectionCard>
        </TabsContent>

        {/* 検査内容タブ */}
        <TabsContent value="details" className="space-y-4">
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

          <SectionCard title="総括チェック表（23項目）">
            <p className="text-xs text-muted-foreground mb-3">
              出す/出さないは「提出するページ」タブで変更します。ここでは表示する項目の判定だけを編集します。
            </p>
            <div className="space-y-2 text-sm">
              {report.summary.filter((s) => s.result !== "").map((s) => {
                const i = report.summary.findIndex((item) => item.id === s.id);
                return (
                <div
                  key={s.id}
                  className="flex items-center justify-between gap-3"
                >
                  <span className="text-muted-foreground">
                    {s.no}. {s.label}
                  </span>
                  <JudgeButton
                    value={s.result}
                    onChange={(v) => {
                      const next = [...report.summary];
                      next[i] = { ...s, result: v };
                      update({ summary: next });
                    }}
                  />
                </div>
                );
              })}
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

        <LiveReportPreview
          report={report}
          client={client}
          reportKindLabel={reportKindLabel}
          selectedIndex={previewIndex}
          onSelectIndex={setPreviewIndex}
        />
      </div>
    </div>
  );
}

function LiveReportPreview({
  report,
  client,
  reportKindLabel,
  selectedIndex,
  onSelectIndex,
}: {
  report: ReportData;
  client: Client;
  reportKindLabel: string;
  selectedIndex: number;
  onSelectIndex: (index: number) => void;
}) {
  const pages = buildPreviewPages(report);
  const safeIndex = Math.min(selectedIndex, Math.max(pages.length - 1, 0));
  const selected = pages[safeIndex] ?? pages[0];

  return (
    <aside className="xl:sticky xl:top-6 xl:h-[calc(100vh-3rem)]">
      <Card className="h-full overflow-hidden border-primary/20">
        <CardHeader className="border-b bg-secondary/30 py-3">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Eye className="h-4 w-4 text-primary" />
            ライブプレビュー
          </CardTitle>
        </CardHeader>
        <CardContent className="flex h-[calc(100%-57px)] flex-col gap-3 p-3">
          <div className="min-h-0 flex-1 overflow-auto rounded-md bg-muted/40 p-3">
            <div className="mx-auto min-h-[560px] w-[340px] bg-white p-5 text-slate-950 shadow-sm ring-1 ring-border">
              {selected && renderPreviewPage(selected, report, client, reportKindLabel)}
            </div>
          </div>

          <div className="border-t pt-3">
            <div className="mb-2 flex items-center justify-between gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={safeIndex === 0}
                onClick={() => onSelectIndex(Math.max(safeIndex - 1, 0))}
              >
                前
              </Button>
              <span className="text-xs text-muted-foreground">
                {safeIndex + 1} / {pages.length}
              </span>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={safeIndex >= pages.length - 1}
                onClick={() => onSelectIndex(Math.min(safeIndex + 1, pages.length - 1))}
              >
                次
              </Button>
            </div>
            <div className="flex gap-2 overflow-x-auto pb-1">
              {pages.map((page, index) => (
                <button
                  key={`${page.kind}-${index}`}
                  type="button"
                  className={`min-w-28 rounded-md border px-2 py-2 text-left text-xs transition ${
                    index === safeIndex
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border bg-background hover:bg-secondary"
                  }`}
                  onClick={() => onSelectIndex(index)}
                >
                  <span className="block text-[10px] text-muted-foreground">{index + 1}</span>
                  <span className="line-clamp-2 font-medium">{page.title}</span>
                </button>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>
    </aside>
  );
}

type PreviewPage = { kind: string; title: string; pageNumber?: number };

function buildPreviewPages(report: ReportData): PreviewPage[] {
  const pages: PreviewPage[] = [
    { kind: "cover", title: "表紙" },
    { kind: "summary", title: "総括チェック表" },
    { kind: "external", title: "外観点検" },
  ];

  for (const page of getOutputPagesForReportKind(report.report_kind)) {
    if (page.key === "lvInsulation") {
      for (let index = 1; index <= report.outputConfig.lvInsulationPageCount; index++) {
        pages.push({ kind: "lvInsulation", title: `低圧絶縁 ${index}枚目`, pageNumber: index });
      }
      continue;
    }
    if (report.outputConfig.pages[page.key]) {
      pages.push({ kind: page.key, title: page.label });
    }
  }

  pages.push({ kind: "instruments", title: "計測器一覧" });
  return pages;
}

function renderPreviewPage(page: PreviewPage, report: ReportData, client: Client, reportKindLabel: string) {
  if (page.kind === "cover") {
    return (
      <PreviewSheet title={reportKindLabel} subtitle={client.facility_name}>
        <PreviewLine label="宛先" value={`${client.name} 様`} />
        <PreviewLine label="実施日" value={`令和${report.year_wareki}年${report.month}月${report.day}日`} />
        <PreviewLine label="天候" value={`${report.weather} / ${report.temperature}℃ / ${report.humidity}%`} />
        <PreviewLine label="点検者" value={report.inspector} />
      </PreviewSheet>
    );
  }

  if (page.kind === "summary") {
    return (
      <PreviewSheet title="総括チェック表" subtitle={client.facility_name}>
        <PreviewTable
          headers={["No", "項目", "判定"]}
          rows={report.summary
            .filter((item) => item.result !== "")
            .map((item) => [item.no, item.label, item.result])}
        />
      </PreviewSheet>
    );
  }

  if (page.kind === "groundResistance") {
    return (
      <PreviewSheet title="接地抵抗測定" subtitle={client.facility_name}>
        <PreviewTable headers={["接地", "種別", "測定値", "判定"]} rows={report.ground.map((g) => [g.name, g.type, g.value, g.judge])} />
      </PreviewSheet>
    );
  }

  if (page.kind === "hvInsulation") {
    return (
      <PreviewSheet title="高圧関係 絶縁抵抗試験" subtitle={client.facility_name}>
        <PreviewTable headers={["回路", "電圧", "測定値", "判定"]} rows={report.hv.map((h) => [h.name, h.voltage, h.value, h.judge])} />
      </PreviewSheet>
    );
  }

  if (page.kind === "lvInsulation") {
    return (
      <PreviewSheet title={`低圧絶縁抵抗測定 ${page.pageNumber ?? 1}枚目`} subtitle={client.facility_name}>
        <PreviewTable headers={["回路", "R-P", "R-N", "判定"]} rows={report.lv.map((l) => [String(l.id), l.rp, l.rn, l.judge])} />
      </PreviewSheet>
    );
  }

  if (page.kind === "arrayInsulation") {
    return (
      <PreviewSheet title="太陽電池アレイ 絶縁測定" subtitle={client.facility_name}>
        <PreviewTable headers={["No", "測定値", "判定"]} rows={report.array.map((a) => [String(a.id), a.value, a.judge])} />
      </PreviewSheet>
    );
  }

  if (page.kind === "generatorInspection") {
    return (
      <PreviewSheet title="非常用予備発電装置 点検記録" subtitle={client.facility_name}>
        <PreviewLine label="蓄電池点検" value="未入力" />
        <PreviewLine label="自動起動・自動停止" value="未入力" />
        <PreviewLine label="絶縁抵抗測定" value="発電機 / 制御盤" />
        <PreviewLine label="特記事項" value="特に異常を認めず" />
      </PreviewSheet>
    );
  }

  if (page.kind === "external") {
    return (
      <PreviewSheet title="外観点検" subtitle={client.facility_name}>
        <PreviewTable headers={["項目", "判定"]} rows={report.external.map((e) => [e.label, e.result])} />
      </PreviewSheet>
    );
  }

  if (page.kind === "instruments") {
    return (
      <PreviewSheet title="計測器一覧" subtitle={client.facility_name}>
        <PreviewTable headers={["名称", "メーカー", "型式", "製造番号"]} rows={report.inst.map((i) => [i.name, i.maker, i.model, i.serial])} />
      </PreviewSheet>
    );
  }

  return (
    <PreviewSheet title={page.title} subtitle={client.facility_name}>
      <PreviewLine label="出力" value="このページは出力対象です" />
    </PreviewSheet>
  );
}

function PreviewSheet({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <div className="space-y-4 text-xs">
      <div className="border-b border-slate-300 pb-3 text-center">
        <h3 className="text-base font-bold tracking-normal">{title}</h3>
        <p className="mt-1 text-[11px] text-slate-600">{subtitle}</p>
      </div>
      {children}
    </div>
  );
}

function PreviewLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[84px_1fr] border-b border-slate-200 py-2 text-xs">
      <span className="font-medium text-slate-600">{label}</span>
      <span>{value || "未入力"}</span>
    </div>
  );
}

function PreviewTable({ headers, rows }: { headers: string[]; rows: string[][] }) {
  return (
    <table className="w-full border-collapse text-[10px]">
      <thead>
        <tr>
          {headers.map((header) => (
            <th key={header} className="border border-slate-400 bg-slate-100 px-1 py-1 text-left font-semibold">
              {header}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, rowIndex) => (
          <tr key={rowIndex}>
            {row.map((cell, cellIndex) => (
              <td key={cellIndex} className="border border-slate-300 px-1 py-1 align-top">
                {cell || "?"}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
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

function countDetails(r: ReportData): number {
  return (
    r.ground.length +
    r.hv.length +
    9 + // dgr
    5 + // ocr
    3 + // ovgr
    r.array.length +
    r.lv.length * 2 +
    r.summary.filter((item) => item.result !== "").length +
    r.external.length +
    r.ground.length +
    r.array.length +
    r.lv.length +
    3
  );
}
