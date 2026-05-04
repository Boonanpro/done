"use client";

import { saveAs } from "file-saver";
import PizZip from "pizzip";
import type { Client, ReportData } from "./types";

type CellValue = string | number | null | undefined;

export async function downloadExcel(
  report: ReportData,
  client: Client,
  saveDir: FileSystemDirectoryHandle | null,
): Promise<{ savedTo: string }> {
  const blob = await generateExcelBlob(report, client);
  const filename = makeFilename(report, client, "xlsm");

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

async function generateExcelBlob(report: ReportData, client: Client): Promise<Blob> {
  const res = await fetch("/inspection-template.xlsm");
  if (!res.ok) throw new Error("Excelテンプレートの読み込みに失敗しました");

  const zip = new PizZip(await res.arrayBuffer());
  const dateSerial = excelDateSerial(report);
  const weatherLine = `天候 ： ${report.weather} 気温${report.temperature}℃ 湿度${report.humidity}%`;

  mutateSheet(zip, "xl/worksheets/sheet1.xml", {
    B12: client.facility_name,
    B15: report.inspector,
    B16: dateSerial,
    B30: "良",
  });

  mutateSheet(zip, "xl/worksheets/sheet2.xml", {
    A2: dateSerial,
    A3: `天候：${report.weather}`,
    ...cellsFromList("C", 4, 17, report.external.map((item) => item.result), "良"),
  });

  mutateSheet(zip, "xl/worksheets/sheet3.xml", {
    B2: dateSerial,
    D2: weatherLine,
    ...groundCells(report),
  });

  mutateSheet(zip, "xl/worksheets/sheet4.xml", {
    L2: dateSerial,
    I3: weatherLine,
    N6: firstJudge(report.hv, "良"),
    ...instrumentRow(report, 14, 0),
    ...instrumentRow(report, 15, 4),
    ...instrumentRow(report, 16, 5),
    ...instrumentRow(report, 17, 0),
    ...instrumentRow(report, 18, 1),
  });

  mutateSheet(zip, "xl/worksheets/sheet5.xml", {
    E2: dateSerial,
    B6: report.dgr.relay_maker,
    C6: report.dgr.relay_model,
    D6: report.dgr.relay_mfg_date,
    E6: report.dgr.relay_serial,
    F6: joinNonEmpty([report.dgr.relay_setting, report.dgr.relay_setting2], " "),
    B9: "良",
    B12: report.dgr.i_tap,
    E12: report.dgr.v_tap,
    B13: report.dgr.i_min,
    E13: report.dgr.v_min,
    B17: report.dgr.t_a,
    C17: report.dgr.t_b,
    D17: report.dgr.t_a,
    E17: report.dgr.t_b,
    B25: report.dgr.judge || "良",
    ...instrumentRow(report, 32, 6, ["A", "B", "C", "D", "E"]),
  });

  mutateSheet(zip, "xl/worksheets/sheet6.xml", {
    K10: report.ocr.maker,
    V10: report.ocr.maker,
    K11: report.ocr.model,
    V11: report.ocr.model,
    K12: report.ocr.serial,
    V12: report.ocr.serial,
    K13: report.ocr.mfg_date,
    V13: report.ocr.mfg_date,
    K17: report.ocr.setting_limit,
    V17: report.ocr.setting_limit,
    K18: report.ocr.tap_at,
    V18: report.ocr.tap_at,
    K19: report.ocr.setting_inst,
    V19: report.ocr.setting_inst,
    K23: report.ocr.r_current,
    V23: report.ocr.t_current,
    K28: report.ocr.r_300,
    V28: report.ocr.t_300,
    K35: report.ocr.inst_tap,
    V35: report.ocr.inst_tap,
    K37: report.ocr.vcb_time,
    V37: report.ocr.vcb_time,
    K39: "良",
    V39: "良",
    K40: "無",
    V40: "無",
    K41: report.ocr.judge || "良",
    V41: report.ocr.judge || "良",
  });

  mutateSheet(zip, "xl/worksheets/sheet8.xml", {
    K9: report.ovgr.maker,
    K10: report.ovgr.model,
    K11: report.ovgr.serial,
    K12: report.ovgr.model_no,
    K13: report.ovgr.mfg_date,
    K15: report.ovgr.setting,
    W20: report.ovgr.v_op_3_5_a,
    W22: report.ovgr.t_op_3,
    K28: "良",
    K30: "無",
    K31: report.ovgr.judge || "良",
  });

  mutateSheet(zip, "xl/worksheets/sheet9.xml", lowVoltageCells(report));
  mutateSheet(zip, "xl/worksheets/sheet10.xml", majorEquipmentCells(report));

  return zip.generate({
    type: "blob",
    mimeType: "application/vnd.ms-excel.sheet.macroEnabled.12",
  });
}

function mutateSheet(zip: PizZip, path: string, values: Record<string, CellValue>) {
  const file = zip.file(path);
  if (!file) return;

  let xml = file.asText();
  for (const [address, value] of Object.entries(values)) {
    if (value == null || value === "") continue;
    xml = setCellValue(xml, address, value);
  }
  zip.file(path, xml);
}

function setCellValue(xml: string, address: string, value: CellValue): string {
  const cellPattern = new RegExp(`<c\\b(?=[^>]*\\br="${escapeRegex(address)}"\\b)([^>]*)>([\\s\\S]*?)<\\/c>`);
  const selfClosingPattern = new RegExp(`<c\\b(?=[^>]*\\br="${escapeRegex(address)}"\\b)([^>]*)\\/>`);

  if (cellPattern.test(xml)) {
    return xml.replace(cellPattern, (_match, attrs: string) => buildCell(address, attrs, value));
  }
  return xml.replace(selfClosingPattern, (_match, attrs: string) => buildCell(address, attrs, value));
}

function buildCell(address: string, attrs: string, value: CellValue): string {
  const style = attrs.match(/\bs="[^"]*"/)?.[0];
  const baseAttrs = `r="${address}"${style ? ` ${style}` : ""}`;

  if (typeof value === "number") {
    return `<c ${baseAttrs}><v>${value}</v></c>`;
  }

  return `<c ${baseAttrs} t="inlineStr"><is><t>${escapeXml(String(value))}</t></is></c>`;
}

function groundCells(report: ReportData): Record<string, CellValue> {
  const cells: Record<string, CellValue> = {};
  report.ground.slice(0, 10).forEach((item, index) => {
    const row = index < 5 ? index + 4 : index + 5;
    cells[`A${row}`] = item.name;
    cells[`B${row}`] = item.type;
    cells[`D${row}`] = item.value;
    cells[`E${row}`] = item.judge || "良";
  });
  return cells;
}

function lowVoltageCells(report: ReportData): Record<string, CellValue> {
  const cells: Record<string, CellValue> = {};
  report.lv.slice(0, 23).forEach((item, index) => {
    const row = index + 3;
    cells[`A${row}`] = `回路 ${item.id}`;
    cells[`C${row}`] = joinNonEmpty([item.rp, item.rn], " / ");
    cells[`D${row}`] = item.judge || "良";
  });
  return cells;
}

function majorEquipmentCells(report: ReportData): Record<string, CellValue> {
  return {
    A3: "区分開閉器（PAS）",
    C3: report.dgr.pas_model,
    D3: report.dgr.pas_mfg_date,
    E3: report.dgr.pas_serial,
    F3: report.dgr.pas_maker,
    A4: "SOG制御器",
    C4: report.dgr.relay_model,
    D4: report.dgr.relay_mfg_date,
    E4: report.dgr.relay_serial,
    F4: report.dgr.relay_maker,
    A14: "OCR",
    B14: joinNonEmpty([report.ocr.setting_limit, report.ocr.setting_inst], " / "),
    C14: report.ocr.model,
    D14: report.ocr.mfg_date,
    E14: report.ocr.serial,
    F14: report.ocr.maker,
    A17: "OVGR",
    B17: report.ovgr.setting,
    C17: report.ovgr.model,
    D17: report.ovgr.mfg_date,
    E17: report.ovgr.serial,
    F17: report.ovgr.maker,
  };
}

function instrumentRow(
  report: ReportData,
  row: number,
  index: number,
  columns: [string, string, string, string, string] = ["A", "D", "F", "H", "J"],
): Record<string, CellValue> {
  const item = report.inst[index];
  if (!item) return {};

  const [nameCol, makerCol, modelCol, serialCol, yearCol] = columns;
  return {
    [`${nameCol}${row}`]: item.name,
    [`${makerCol}${row}`]: item.maker,
    [`${modelCol}${row}`]: item.model,
    [`${serialCol}${row}`]: item.serial,
    [`${yearCol}${row}`]: "",
  };
}

function cellsFromList(
  column: string,
  startRow: number,
  endRow: number,
  values: CellValue[],
  fallback: CellValue,
): Record<string, CellValue> {
  const cells: Record<string, CellValue> = {};
  for (let row = startRow; row <= endRow; row++) {
    cells[`${column}${row}`] = values[row - startRow] ?? fallback;
  }
  return cells;
}

function firstJudge(items: { judge: string }[], fallback: string): string {
  return items.find((item) => item.judge)?.judge || fallback;
}

function excelDateSerial(report: ReportData): number {
  const year = 2018 + report.year_wareki;
  const date = Date.UTC(year, report.month - 1, report.day);
  const excelEpoch = Date.UTC(1899, 11, 30);
  return Math.round((date - excelEpoch) / 86400000);
}

function joinNonEmpty(values: CellValue[], separator: string): string {
  return values
    .map((value) => (value == null ? "" : String(value).trim()))
    .filter(Boolean)
    .join(separator);
}

function makeFilename(report: ReportData, client: Client, ext: string): string {
  const safeName = client.name.replace(/[\\/:*?"<>|]/g, "");
  return `R${report.year_wareki}_${safeName}_年次点検報告書_${report.year_wareki}-${report.month}-${report.day}.${ext}`;
}

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function escapeXml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}
