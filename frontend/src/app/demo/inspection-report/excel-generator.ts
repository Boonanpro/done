"use client";

import { saveAs } from "file-saver";
import PizZip from "pizzip";
import type { Client, ReportData } from "./types";

type Cell = string | number | null | undefined;

type Sheet = {
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
      console.warn("Failed to save Excel file to selected directory. Falling back to download.", e);
    }
  }

  saveAs(blob, filename);
  return { savedTo: "ブラウザの既定ダウンロードフォルダ" };
}

function generateExcelBlob(report: ReportData, client: Client): Blob {
  const sheets: Sheet[] = [
    buildCoverSheet(report, client),
    buildJudgesSheet(report),
    buildMeasurementsSheet(report),
    buildRelaysSheet(report),
    buildInstrumentsSheet(report),
  ];

  const zip = new PizZip();
  zip.file("[Content_Types].xml", contentTypes(sheets.length));
  zip.folder("_rels")?.file(".rels", rootRels());
  zip.folder("docProps")?.file("core.xml", coreProps());
  zip.folder("docProps")?.file("app.xml", appProps(sheets));

  const xl = zip.folder("xl");
  xl?.file("workbook.xml", workbook(sheets));
  xl?.file("styles.xml", styles());
  xl?.folder("_rels")?.file("workbook.xml.rels", workbookRels(sheets.length));
  const worksheets = xl?.folder("worksheets");
  sheets.forEach((sheet, index) => {
    worksheets?.file(`sheet${index + 1}.xml`, renderWorksheet(sheet));
  });

  return zip.generate({
    type: "blob",
    mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
}

function buildCoverSheet(report: ReportData, client: Client): Sheet {
  return {
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
  };
}

function buildJudgesSheet(report: ReportData): Sheet {
  return {
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
  };
}

function buildMeasurementsSheet(report: ReportData): Sheet {
  return {
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
  };
}

function buildRelaysSheet(report: ReportData): Sheet {
  return {
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
  };
}

function buildInstrumentsSheet(report: ReportData): Sheet {
  return {
    name: "計測器",
    rows: [
      ["名称", "メーカー", "型式", "製造番号"],
      ...report.inst.map((i) => [i.name, i.maker, i.model, i.serial]),
      [],
      ["PCS確認", "確認日", "状態", "備考"],
      ...report.pcs.map((p) => [p.label, p.date, p.state, p.note]),
    ],
  };
}

function renderWorksheet(sheet: Sheet): string {
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheetViews>
    <sheetView workbookViewId="0"/>
  </sheetViews>
  <sheetFormatPr defaultRowHeight="18"/>
  <cols>
    <col min="1" max="1" width="18" customWidth="1"/>
    <col min="2" max="2" width="26" customWidth="1"/>
    <col min="3" max="3" width="18" customWidth="1"/>
    <col min="4" max="4" width="18" customWidth="1"/>
    <col min="5" max="5" width="12" customWidth="1"/>
  </cols>
  <sheetData>
    ${sheet.rows.map(renderRow).join("\n")}
  </sheetData>
  <pageMargins left="0.4" right="0.4" top="0.5" bottom="0.5" header="0.3" footer="0.3"/>
  <pageSetup orientation="landscape" fitToWidth="1" fitToHeight="0"/>
</worksheet>`;
}

function renderRow(row: Cell[], rowIndex: number): string {
  const rowNumber = rowIndex + 1;
  return `<row r="${rowNumber}">${row.map((cell, columnIndex) => renderCell(cell, rowNumber, columnIndex, rowIndex === 0)).join("")}</row>`;
}

function renderCell(value: Cell, rowNumber: number, columnIndex: number, isHeader: boolean): string {
  const ref = `${columnName(columnIndex + 1)}${rowNumber}`;
  const style = isHeader ? ' s="1"' : "";
  if (value == null || value === "") return `<c r="${ref}"${style}/>`;
  if (typeof value === "number") return `<c r="${ref}"${style}><v>${value}</v></c>`;
  return `<c r="${ref}" t="inlineStr"${style}><is><t>${xml(String(value))}</t></is></c>`;
}

function xml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

function makeFilename(report: ReportData, client: Client, ext: string): string {
  const safeName = client.name.replace(/[\\/:*?"<>|]/g, "");
  return `R${report.year_wareki}_${safeName}_inspection-report_${report.year_wareki}-${report.month}-${report.day}.${ext}`;
}

function contentTypes(sheetCount: number): string {
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
  ${Array.from({ length: sheetCount }, (_, i) => `<Override PartName="/xl/worksheets/sheet${i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`).join("\n  ")}
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>`;
}

function rootRels(): string {
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>`;
}

function workbook(sheets: Sheet[]): string {
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <workbookPr/>
  <sheets>
    ${sheets.map((sheet, i) => `<sheet name="${xml(sheet.name)}" sheetId="${i + 1}" r:id="rId${i + 1}"/>`).join("\n    ")}
  </sheets>
</workbook>`;
}

function workbookRels(sheetCount: number): string {
  const sheetRels = Array.from(
    { length: sheetCount },
    (_, i) => `<Relationship Id="rId${i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet${i + 1}.xml"/>`,
  ).join("\n  ");
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  ${sheetRels}
  <Relationship Id="rId${sheetCount + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>`;
}

function styles(): string {
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="2">
    <font><sz val="10"/><name val="Yu Gothic"/></font>
    <font><b/><sz val="10"/><name val="Yu Gothic"/></font>
  </fonts>
  <fills count="3">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFD9EAF7"/><bgColor indexed="64"/></patternFill></fill>
  </fills>
  <borders count="2">
    <border><left/><right/><top/><bottom/><diagonal/></border>
    <border><left/><right/><top/><bottom style="thin"><color auto="1"/></bottom/><diagonal/></border>
  </borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="2">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1"/>
  </cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>`;
}

function coreProps(): string {
  const now = new Date().toISOString();
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
  xmlns:dc="http://purl.org/dc/elements/1.1/"
  xmlns:dcterms="http://purl.org/dc/terms/"
  xmlns:dcmitype="http://purl.org/dc/dcmitype/"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>Inspection Report</dc:title>
  <dc:creator>inspection-report</dc:creator>
  <cp:lastModifiedBy>inspection-report</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">${now}</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">${now}</dcterms:modified>
</cp:coreProperties>`;
}

function appProps(sheets: Sheet[]): string {
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
  xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>inspection-report</Application>
  <TitlesOfParts>
    <vt:vector size="${sheets.length}" baseType="lpstr">
      ${sheets.map((sheet) => `<vt:lpstr>${xml(sheet.name)}</vt:lpstr>`).join("\n      ")}
    </vt:vector>
  </TitlesOfParts>
</Properties>`;
}

function columnName(index: number): string {
  let name = "";
  let n = index;
  while (n > 0) {
    const remainder = (n - 1) % 26;
    name = String.fromCharCode(65 + remainder) + name;
    n = Math.floor((n - 1) / 26);
  }
  return name;
}
