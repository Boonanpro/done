"use client";

import { saveAs } from "file-saver";
import * as XLSX from "xlsx";
import type { Client, ReportData } from "./types";

type Cell = string | number | null | undefined;

type SheetSpec = {
  name: string;
  rows: Cell[][];
};

export async function downloadExcel(
  report: ReportData,
  client: Client,
  saveDir: FileSystemDirectoryHandle | null,
): Promise<{ savedTo: string }> {
  const blob = generateExcelBlob(report, client);
  const filename = makeFilename(report, client, "xlsx");

  if (saveDir) {
    try {
      const fileHandle = await saveDir.getFileHandle(filename, { create: true });
      const writable = await fileHandle.createWritable();
      await writable.write(blob);
      await writable.close();
      return { savedTo: `フォルダ「${saveDir.name}」に保存` };
    } catch (e) {
      console.warn("Excel file save failed. Falling back to browser download.", e);
    }
  }

  saveAs(blob, filename);
  return { savedTo: "ブラウザの既定ダウンロードフォルダ" };
}

function generateExcelBlob(report: ReportData, client: Client): Blob {
  const workbook = XLSX.utils.book_new();

  for (const spec of buildSheets(report, client)) {
    const worksheet = XLSX.utils.aoa_to_sheet(spec.rows);
    worksheet["!cols"] = columnWidths(spec.rows);
    worksheet["!freeze"] = { xSplit: 0, ySplit: 1 };
    XLSX.utils.book_append_sheet(workbook, worksheet, spec.name);
  }

  const output = XLSX.write(workbook, {
    bookType: "xlsx",
    type: "array",
    compression: true,
  });

  return new Blob([output], {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
}

function buildSheets(report: ReportData, client: Client): SheetSpec[] {
  return [
    {
      name: "基本情報",
      rows: [
        ["年次点検報告書"],
        [],
        ["顧客名", client.name],
        ["設備名", client.facility_name],
        ["実施日", `令和${report.year_wareki}年${report.month}月${report.day}日`],
        ["天候", report.weather],
        ["温度", `${report.temperature}℃`],
        ["湿度", `${report.humidity}%`],
        ["点検者", report.inspector],
      ],
    },
    {
      name: "判定",
      rows: [
        ["区分", "番号", "項目", "判定"],
        ...report.summary.map((s) => ["総合", s.no, s.label, s.result]),
        [],
        ...report.external.map((e) => ["外観点検", "", e.label, e.result]),
        [],
        ...report.ground.map((g) => ["接地抵抗", "", `${g.name} ${g.type}`, g.judge]),
        ["DGR", "", "総合判定", report.dgr.judge],
        ["OCR", "", "総合判定", report.ocr.judge],
        ["OVGR", "", "総合判定", report.ovgr.judge],
        ...report.array.map((a) => ["太陽電池アレイ", String(a.id), "", a.judge]),
        ...report.box.map((b) => ["接続箱", String(b.id), "", b.judge]),
        ...report.lv.map((l) => ["低圧絶縁抵抗", String(l.id), "", l.judge]),
      ],
    },
    {
      name: "測定値",
      rows: [
        ["区分", "名称", "種別", "測定値", "判定"],
        ...report.ground.map((g) => ["接地抵抗", g.name, g.type, g.value, g.judge]),
        ...report.hv.map((h) => ["高圧絶縁抵抗", h.name, h.voltage, h.value, h.judge]),
        ...report.array.map((a) => ["太陽電池アレイ", `No.${a.id}`, "", a.value, a.judge]),
        ...report.box.map((b) => ["接続箱", `No.${b.id}`, "", b.value, b.judge]),
        ...report.lv.map((l) => ["低圧絶縁抵抗", `回路 ${l.id}`, "R-P", l.rp, l.judge]),
        ...report.lv.map((l) => ["低圧絶縁抵抗", `回路 ${l.id}`, "R-N", l.rn, l.judge]),
      ],
    },
    {
      name: "継電器",
      rows: [
        ["区分", "項目", "値"],
        ["DGR PAS", "メーカー", report.dgr.pas_maker],
        ["DGR PAS", "型式", report.dgr.pas_model],
        ["DGR PAS", "製造番号", report.dgr.pas_serial],
        ["DGR PAS", "製造年月", report.dgr.pas_mfg_date],
        ["DGR リレー", "メーカー", report.dgr.relay_maker],
        ["DGR リレー", "型式", report.dgr.relay_model],
        ["DGR リレー", "製造番号", report.dgr.relay_serial],
        ["DGR リレー", "製造年月", report.dgr.relay_mfg_date],
        ["DGR リレー", "整定", report.dgr.relay_setting],
        ["DGR リレー", "整定2", report.dgr.relay_setting2],
        ["DGR 試験", "Vタップ", report.dgr.v_tap],
        ["DGR 試験", "V最小", report.dgr.v_min],
        ["DGR 試験", "Iタップ", report.dgr.i_tap],
        ["DGR 試験", "I最小", report.dgr.i_min],
        ["DGR 試験", "位相進み", report.dgr.phase_lead],
        ["DGR 試験", "位相遅れ", report.dgr.phase_lag],
        ["DGR 試験", "Tタップ", report.dgr.t_tap],
        ["DGR 試験", "試験電流A", report.dgr.t_i_a],
        ["DGR 試験", "試験電流B", report.dgr.t_i_b],
        ["DGR 試験", "動作時間A", report.dgr.t_a],
        ["DGR 試験", "動作時間B", report.dgr.t_b],
        ["DGR 試験", "連動時間", report.dgr.linked_time],
        [],
        ["OCR", "メーカー", report.ocr.maker],
        ["OCR", "型式", report.ocr.model],
        ["OCR", "製造番号", report.ocr.serial],
        ["OCR", "製造年月", report.ocr.mfg_date],
        ["OCR", "限時整定", report.ocr.setting_limit],
        ["OCR", "瞬時整定", report.ocr.setting_inst],
        ["OCR", "タップ", report.ocr.tap_at],
        ["OCR", "R相動作電流", report.ocr.r_current],
        ["OCR", "T相動作電流", report.ocr.t_current],
        ["OCR", "試験タップ", report.ocr.test_tap],
        ["OCR", "300% R相", report.ocr.r_300],
        ["OCR", "300% T相", report.ocr.t_300],
        ["OCR", "瞬時タップ", report.ocr.inst_tap],
        ["OCR", "VCB時間", report.ocr.vcb_time],
        [],
        ["OVGR", "メーカー", report.ovgr.maker],
        ["OVGR", "型式", report.ovgr.model],
        ["OVGR", "型番", report.ovgr.model_no],
        ["OVGR", "製造番号", report.ovgr.serial],
        ["OVGR", "製造年月", report.ovgr.mfg_date],
        ["OVGR", "整定", report.ovgr.setting],
        ["OVGR", "動作電圧A", report.ovgr.v_op_3_5_a],
        ["OVGR", "動作電圧B", report.ovgr.v_op_3_5_b],
        ["OVGR", "動作時間3%", report.ovgr.t_op_3],
      ],
    },
    {
      name: "計測器",
      rows: [
        ["名称", "メーカー", "型式", "製造番号"],
        ...report.inst.map((i) => [i.name, i.maker, i.model, i.serial]),
        [],
        ["PCS確認", "確認日", "状態", "備考"],
        ...report.pcs.map((p) => [p.label, p.date, p.state, p.note]),
      ],
    },
  ];
}

function columnWidths(rows: Cell[][]): XLSX.ColInfo[] {
  const maxColumns = Math.max(...rows.map((row) => row.length));
  return Array.from({ length: maxColumns }, (_, columnIndex) => {
    const maxLength = rows.reduce((max, row) => {
      const value = row[columnIndex];
      return Math.max(max, value == null ? 0 : String(value).length);
    }, 8);

    return { wch: Math.min(Math.max(maxLength + 2, 10), 36) };
  });
}

function makeFilename(report: ReportData, client: Client, ext: string): string {
  const safeName = client.name.replace(/[\\/:*?"<>|]/g, "");
  return `R${report.year_wareki}_${safeName}_年次点検報告書_${report.year_wareki}-${report.month}-${report.day}.${ext}`;
}
