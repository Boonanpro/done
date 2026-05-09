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
  if (report.report_kind === "completion") {
    return generateCompletionExcelBlob(report, client);
  }
  return generateAnnualExcelBlob(report, client);
}

async function generateAnnualExcelBlob(report: ReportData, client: Client): Promise<Blob> {
  const res = await fetch("/annual-inspection-template.xlsm");
  if (!res.ok) throw new Error("年次点検Excelテンプレートの読み込みに失敗しました");

  const zip = new PizZip(await res.arrayBuffer());
  const skipped = skippedSummaryIds(report);
  mutateSheet(zip, "xl/worksheets/sheet1.xml", annualCoverCells(report, client));
  mutateSheet(zip, "xl/worksheets/sheet15.xml", annualLowVoltageCells(report));
  addAnnualConfiguredSheets(zip, report, client);
  hideAnnualSkippedSheets(zip, skipped);

  return zip.generate({
    type: "blob",
    mimeType: "application/vnd.ms-excel.sheet.macroEnabled.12",
  });
}

function annualCoverCells(report: ReportData, client: Client): Record<string, CellValue> {
  return {
    B6: `${client.name}　様`,
    F8: `${client.facility_name}　　      ㊞　　　　　　　　　　　　　　　　　${report.inspector}   　`,
    C11: `実施日:${2018 + report.year_wareki}年  ${report.month}月  ${report.day}日 天候：${report.weather} 気温：${report.temperature}℃ 湿度${report.humidity}％`,
    ...annualSummaryResultCells(report),
  };
}

function annualSummaryResultCells(report: ReportData): Record<string, CellValue> {
  const cells: Record<string, CellValue> = {};
  report.summary.slice(0, 12).forEach((item, index) => {
    cells[`D${17 + index}`] = item.result;
  });
  report.summary.slice(12, 23).forEach((item, index) => {
    cells[`G${17 + index}`] = item.result;
  });
  return cells;
}

function annualLowVoltageCells(report: ReportData): Record<string, CellValue> {
  const cells: Record<string, CellValue> = {};
  report.lv.slice(0, 8).forEach((item, index) => {
    const row = 9 + index;
    cells[`C${row}`] = `回路 ${item.id}`;
    cells[`D${row}`] = joinNonEmpty([item.rp, item.rn], " / ");
    cells[`E${row}`] = item.judge || "良";
  });
  return cells;
}

function addAnnualConfiguredSheets(zip: PizZip, report: ReportData, client: Client) {
  const lvPageCount = report.outputConfig.lvInsulationPageCount;
  if (lvPageCount > 1) {
    for (let page = 2; page <= lvPageCount; page++) {
      duplicateWorksheet(zip, "xl/worksheets/sheet15.xml", `低圧絶縁 ${page}`);
    }
  }

  if (report.outputConfig.pages.generatorInspection) {
    addWorksheet(zip, "発電機点検記録", generatorInspectionSheetXml(report, client));
  }
}

async function generateCompletionExcelBlob(report: ReportData, client: Client): Promise<Blob> {
  const res = await fetch("/inspection-template.xlsm");
  if (!res.ok) throw new Error("Excelテンプレートの読み込みに失敗しました");

  const zip = new PizZip(await res.arrayBuffer());
  const dateSerial = excelDateSerial(report);
  const weatherLine = `天候 ： ${report.weather} 気温${report.temperature}℃ 湿度${report.humidity}%`;
  const skipped = skippedSummaryIds(report);

  mutateSheet(zip, "xl/worksheets/sheet1.xml", {
    B12: client.facility_name,
    B15: report.inspector,
    B16: dateSerial,
    B30: "良",
    ...coverInspectionListCells(skipped),
  });
  clearCells(zip, "xl/worksheets/sheet1.xml", coverInspectionListCellsToClear(skipped));

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
  keepCoverStampInsidePrintArea(zip);
  hideSkippedSheets(zip, skipped);

  return zip.generate({
    type: "blob",
    mimeType: "application/vnd.ms-excel.sheet.macroEnabled.12",
  });
}

function hideAnnualSkippedSheets(zip: PizZip, skipped: Set<string>) {
  const sheetsToHide = new Set<string>();

  if (skipped.has("r01")) sheetsToHide.add("過電流継電器");
  if (skipped.has("r02")) sheetsToHide.add("SOG");
  if (skipped.has("r03")) {
    sheetsToHide.add("OVGR");
    sheetsToHide.add("不足電圧");
    sheetsToHide.add("低圧OVGR");
  }
  if (skipped.has("r06") && skipped.has("r07")) sheetsToHide.add("接地・高圧絶縁");
  if (skipped.has("r11")) sheetsToHide.add("低圧絶縁");
  if (skipped.has("r22")) {
    sheetsToHide.add("アレイ絶縁A1-A4");
    sheetsToHide.add("アレイ絶縁A5-B2");
    sheetsToHide.add("アレイ絶縁B3-C1");
    sheetsToHide.add("アレイ絶縁C2-C5");
    sheetsToHide.add("アレイ絶縁C6-C8");
    sheetsToHide.add("アレイ絶縁D1-D3");
  }
  if (skipped.has("r23")) sheetsToHide.add("総合保護連動");

  const workbookFile = zip.file("xl/workbook.xml");
  if (!workbookFile) return;

  let xml = workbookFile.asText();
  for (const sheetName of sheetsToHide) {
    xml = hideWorkbookSheet(xml, sheetName);
  }
  zip.file("xl/workbook.xml", xml);
}

function duplicateWorksheet(zip: PizZip, sourcePath: string, sheetName: string) {
  const source = zip.file(sourcePath);
  if (!source) return;

  const sheetPath = nextWorksheetPath(zip);
  addWorksheet(zip, sheetName, source.asText(), sheetPath);

  const sourceRelsPath = sourcePath.replace("xl/worksheets/", "xl/worksheets/_rels/") + ".rels";
  const sourceRels = zip.file(sourceRelsPath);
  if (sourceRels) {
    const targetRelsPath = sheetPath.replace("xl/worksheets/", "xl/worksheets/_rels/") + ".rels";
    zip.file(targetRelsPath, sourceRels.asText());
  }
}

function addWorksheet(zip: PizZip, sheetName: string, sheetXml: string, preferredPath?: string) {
  const workbookFile = zip.file("xl/workbook.xml");
  const relsFile = zip.file("xl/_rels/workbook.xml.rels");
  const contentTypesFile = zip.file("[Content_Types].xml");
  if (!workbookFile || !relsFile || !contentTypesFile) return;

  const sheetPath = preferredPath ?? nextWorksheetPath(zip);
  const sheetId = nextWorkbookSheetId(workbookFile.asText());
  const relId = nextRelationshipId(relsFile.asText());
  const sheetTarget = sheetPath.replace("xl/", "");

  zip.file(sheetPath, sheetXml);
  zip.file(
    "xl/workbook.xml",
    workbookFile
      .asText()
      .replace(
        "</sheets>",
        `<sheet name="${escapeXml(sheetName)}" sheetId="${sheetId}" r:id="${relId}"/></sheets>`,
      ),
  );
  zip.file(
    "xl/_rels/workbook.xml.rels",
    relsFile
      .asText()
      .replace(
        "</Relationships>",
        `<Relationship Id="${relId}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="${sheetTarget}"/></Relationships>`,
      ),
  );
  zip.file(
    "[Content_Types].xml",
    ensureWorksheetContentType(contentTypesFile.asText(), sheetPath),
  );
}

function nextWorksheetPath(zip: PizZip): string {
  const maxSheetNumber = Math.max(
    0,
    ...Object.keys(zip.files)
      .map((path) => path.match(/^xl\/worksheets\/sheet(\d+)\.xml$/)?.[1])
      .filter((value): value is string => Boolean(value))
      .map(Number),
  );
  return `xl/worksheets/sheet${maxSheetNumber + 1}.xml`;
}

function nextWorkbookSheetId(workbookXml: string): number {
  return (
    Math.max(
      0,
      ...Array.from(workbookXml.matchAll(/\bsheetId="(\d+)"/g)).map((match) => Number(match[1])),
    ) + 1
  );
}

function nextRelationshipId(relsXml: string): string {
  const maxId = Math.max(
    0,
    ...Array.from(relsXml.matchAll(/\bId="rId(\d+)"/g)).map((match) => Number(match[1])),
  );
  return `rId${maxId + 1}`;
}

function ensureWorksheetContentType(xml: string, sheetPath: string): string {
  const partName = `/${sheetPath}`;
  if (xml.includes(`PartName="${partName}"`)) return xml;
  return xml.replace(
    "</Types>",
    `<Override PartName="${partName}" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>`,
  );
}

function generatorInspectionSheetXml(report: ReportData, client: Client): string {
  const date = `${2018 + report.year_wareki}年${report.month}月${report.day}日`;
  const rows: Record<string, CellValue>[] = [
    { A: "業場名", C: client.facility_name || client.name, H: "点検日", J: date },
    { A: "非常用予備発電装置 点検記録" },
    { A: "定格出力", B: "", D: "定格電圧", F: "", H: "定格周波数", I: "" },
    { A: "蓄電池電圧", B: "", D: "タンク容量", F: "", H: "燃料", I: "", K: "回転数" },
    { A: "製造者名", B: "型式", D: "製造番号", F: "製造年", H: "始動方式" },
    { A: "" },
    { A: "【蓄電池点検】" },
    { A: "蓄電池番号", B: "電圧(V)", D: "比重", E: "液温", G: "蓄電池番号", H: "電圧(V)", J: "比重", L: "液温" },
    { A: "1", B: "", D: "－", E: "－" },
    {},
    {},
    {},
    {},
    { A: "判定基準：停電から電源切替まで　即時型：10秒以内　即時型以外：40秒以内" },
    {},
    {},
    { A: "停電　起動　電圧確立　負荷切替" },
    { A: "自動起動", J: "判定：良" },
    { C: "", E: "", G: "" },
    {},
    { A: "判定基準：復電から停止用電磁弁ONまで3分±2秒" },
    { A: "復電　負荷切替　電磁弁ON　停止　解放" },
    { A: "自動停止", J: "判定：良" },
    { C: "", E: "", G: "", I: "" },
    {},
    { A: "絶縁抵抗測定（MΩ以上）" },
    { B: "印加電圧(V)", C: "測定値", D: "管理値", E: "判定", F: "備考" },
    { A: "発電機", B: "250", C: "", D: "0.2", E: "良" },
    { A: "制御盤", B: "125", C: "", D: "0.1", E: "良" },
    {},
    { A: "【外観点検・試運転記録】" },
    { A: "別紙記載" },
    {},
    { A: "【特記事項】" },
    { A: "特に異常を認めず" },
  ];

  return worksheetXml(rows);
}

function worksheetXml(rows: Record<string, CellValue>[]): string {
  const rowXml = rows
    .map((row, index) => {
      const rowNumber = index + 1;
      const cells = Object.entries(row)
        .map(([column, value]) => buildCell(`${column}${rowNumber}`, "", value))
        .join("");
      return `<row r="${rowNumber}">${cells}</row>`;
    })
    .join("");

  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><dimension ref="A1:L35"/><sheetViews><sheetView workbookViewId="0"/></sheetViews><sheetFormatPr defaultRowHeight="18"/><sheetData>${rowXml}</sheetData><pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/><pageSetup paperSize="9" orientation="portrait"/></worksheet>`;
}

function skippedSummaryIds(report: ReportData): Set<string> {
  return new Set(report.summary.filter((item) => item.result === "").map((item) => item.id));
}

function coverInspectionListCells(skipped: Set<string>): Record<string, CellValue> {
  return {
    B20: skipped.has("r07") ? "" : undefined,
    B21: skipped.has("r06") ? "" : undefined,
    B22: skipped.has("r02") ? "" : undefined,
    B23: skipped.has("r01") ? "" : undefined,
    B24: skipped.has("r03") ? "" : undefined,
    B25: skipped.has("r03") ? "" : undefined,
    B26: skipped.has("r11") ? "" : undefined,
  };
}

function coverInspectionListCellsToClear(skipped: Set<string>): string[] {
  return Object.entries(coverInspectionListCells(skipped))
    .filter(([, value]) => value === "")
    .map(([address]) => address);
}

function hideSkippedSheets(zip: PizZip, skipped: Set<string>) {
  const sheetsToHide = new Set<string>();
  if (skipped.has("r07")) sheetsToHide.add("接地抵抗試験");
  if (skipped.has("r06")) sheetsToHide.add("耐圧");
  if (skipped.has("r02")) sheetsToHide.add("地絡継電器");
  if (skipped.has("r01")) sheetsToHide.add("過電流継電器");
  if (skipped.has("r03")) {
    sheetsToHide.add("不足電圧");
    sheetsToHide.add("地絡過電圧");
  }
  if (skipped.has("r11")) sheetsToHide.add("低圧幹線絶縁抵抗測定");

  const workbookFile = zip.file("xl/workbook.xml");
  if (!workbookFile) return;

  let xml = workbookFile.asText();
  for (const sheetName of ALWAYS_HIDDEN_SHEETS) {
    xml = hideWorkbookSheet(xml, sheetName);
  }
  if (sheetsToHide.size > 0) {
    for (const sheetName of sheetsToHide) {
      xml = hideWorkbookSheet(xml, sheetName);
    }
  }
  zip.file("xl/workbook.xml", xml);
}

const ALWAYS_HIDDEN_SHEETS = ["アルバム", "アルバム (2)", "アルバム (3)", "アルバム (4)", "アルバム (5)", "用語集"];

function hideWorkbookSheet(xml: string, sheetName: string): string {
  return xml.replace(/<sheet\b[^>]*\/>/g, (sheetTag) => {
    const name = getXmlAttribute(sheetTag, "name");
    if (name?.trim() !== sheetName) return sheetTag;

    if (/\bstate="/.test(sheetTag)) {
      return sheetTag.replace(/\bstate="[^"]*"/, 'state="veryHidden"');
    }
    return sheetTag.replace(/\/>$/, ' state="veryHidden"/>');
  });
}

function keepCoverStampInsidePrintArea(zip: PizZip) {
  const drawingFile = zip.file("xl/drawings/drawing1.xml");
  if (!drawingFile) return;

  const stampColOffset = "3800000";
  const stampXOffset = "5171600";
  const xml = drawingFile.asText().replace(/<xdr:oneCellAnchor>[\s\S]*?<\/xdr:oneCellAnchor>/, (anchor) => {
    if (!/<xdr:cNvPr\b[^>]*\bname="図 1"/.test(anchor)) return anchor;
    return anchor
      .replace(/(<xdr:colOff>)-?\d+(<\/xdr:colOff>)/, `$1${stampColOffset}$2`)
      .replace(/(<a:off\b[^>]*\bx=")-?\d+("[^>]*\/>)/, `$1${stampXOffset}$2`);
  });
  zip.file("xl/drawings/drawing1.xml", xml);
}

function mutateSheet(zip: PizZip, path: string, values: Record<string, CellValue>) {
  const file = zip.file(path);
  if (!file) return;

  let xml = file.asText();
  for (const [address, value] of Object.entries(values)) {
    if (value == null) continue;
    xml = setCellValue(xml, address, value);
  }
  zip.file(path, xml);
}

function clearCells(zip: PizZip, path: string, addresses: string[]) {
  if (addresses.length === 0) return;

  const file = zip.file(path);
  if (!file) return;

  let xml = file.asText();
  for (const address of addresses) {
    xml = clearCellValue(xml, address);
  }
  zip.file(path, xml);
}

function clearCellValue(xml: string, address: string): string {
  const cellPattern = new RegExp(`<c\\b(?=[^>]*\\br="${escapeRegex(address)}"\\b)([^>]*)>([\\s\\S]*?)<\\/c>`);
  const selfClosingPattern = new RegExp(`<c\\b(?=[^>]*\\br="${escapeRegex(address)}"\\b)([^>]*)\\/>`);
  const clearCell = (_match: string, attrs: string) => {
    const style = attrs.match(/\bs="[^"]*"/)?.[0];
    return `<c r="${address}"${style ? ` ${style}` : ""}/>`;
  };

  if (cellPattern.test(xml)) {
    return xml.replace(cellPattern, clearCell);
  }
  return xml.replace(selfClosingPattern, clearCell);
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
  const reportName = report.report_kind === "completion" ? "竣工報告書" : "年次点検報告書";
  return `R${report.year_wareki}_${safeName}_${reportName}_${report.year_wareki}-${report.month}-${report.day}.${ext}`;
}

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function getXmlAttribute(tag: string, name: string): string | null {
  const match = tag.match(new RegExp(`\\b${escapeRegex(name)}="([^"]*)"`));
  return match ? unescapeXml(match[1]) : null;
}

function unescapeXml(value: string): string {
  return value
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&amp;/g, "&");
}

function escapeXml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}
