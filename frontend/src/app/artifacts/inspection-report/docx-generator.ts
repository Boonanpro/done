"use client";

import PizZip from "pizzip";
import Docxtemplater from "docxtemplater";
import { saveAs } from "file-saver";
import type { Client, ReportData } from "./types";

// ReportData → docxtemplater が期待するネストオブジェクトに変換
function buildContext(report: ReportData, client: Client): Record<string, unknown> {
  const ctx: Record<string, unknown> = {};

  ctx.rpt = {
    year_wareki: report.year_wareki,
    month: report.month,
    day: report.day,
    weather: report.weather,
    temperature: report.temperature,
    humidity: report.humidity,
    inspector: report.inspector,
  };

  ctx.client = {
    name: client.name,
    facility_name: client.facility_name,
  };

  // sum.r01 ... r23: { no, label, result } のネストオブジェクト
  // result が「空」(空文字)のときは no/label も空にして「項目ごと消えた」見た目にする
  const sum: Record<string, { no: string; label: string; result: string }> = {};
  for (const s of report.summary) {
    if (s.result === "") {
      sum[s.id] = { no: "", label: "", result: "" };
    } else {
      sum[s.id] = { no: s.no, label: s.label, result: s.result };
    }
  }
  ctx.sum = sum;

  const ext: Record<string, string> = {};
  for (const e of report.external) ext[e.id] = e.result;
  ctx.ext = ext;

  const ground: Record<string, unknown> = {};
  report.ground.forEach((g, i) => {
    ground[`r${i + 1}`] = { name: g.name, type: g.type, value: g.value, judge: g.judge };
  });
  ctx.ground = ground;

  const hv: Record<string, unknown> = {};
  report.hv.forEach((h, i) => {
    hv[`r${i + 1}`] = { name: h.name, voltage: h.voltage, value: h.value, judge: h.judge };
  });
  ctx.hv = hv;

  ctx.dgr = {
    pas: {
      maker: report.dgr.pas_maker,
      model: report.dgr.pas_model,
      serial: report.dgr.pas_serial,
      mfg_date: report.dgr.pas_mfg_date,
    },
    relay: {
      maker: report.dgr.relay_maker,
      model: report.dgr.relay_model,
      serial: report.dgr.relay_serial,
      mfg_date: report.dgr.relay_mfg_date,
      setting: report.dgr.relay_setting,
      setting2: report.dgr.relay_setting2,
    },
    v_tap: report.dgr.v_tap,
    v_min: report.dgr.v_min,
    i_tap: report.dgr.i_tap,
    i_min: report.dgr.i_min,
    phase_lead: report.dgr.phase_lead,
    phase_lag: report.dgr.phase_lag,
    t_tap: report.dgr.t_tap,
    t_i_a: report.dgr.t_i_a,
    t_i_b: report.dgr.t_i_b,
    t_a: report.dgr.t_a,
    t_b: report.dgr.t_b,
    linked_time: report.dgr.linked_time,
    judge: report.dgr.judge,
  };

  ctx.ocr = { ...report.ocr };
  ctx.ovgr = { ...report.ovgr };

  const array: Record<string, unknown> = {};
  report.array.forEach((a) => {
    array[`r${a.id}`] = { value: a.value, judge: a.judge };
  });
  ctx.array = array;

  const box: Record<string, unknown> = {};
  report.box.forEach((b) => {
    box[`r${b.id}`] = { value: b.value, judge: b.judge };
  });
  ctx.box = box;

  const lv: Record<string, unknown> = {};
  report.lv.forEach((l) => {
    lv[`r${l.id}`] = { rp: l.rp, rn: l.rn, judge: l.judge };
  });
  ctx.lv = lv;

  const pcs: Record<string, unknown> = {};
  report.pcs.forEach((p) => {
    pcs[p.id] = { date: p.date, state: p.state, note: p.note };
  });
  ctx.pcs = pcs;

  const inst: Record<string, unknown> = {};
  report.inst.forEach((i, idx) => {
    inst[`r${idx + 1}`] = { name: i.name, maker: i.maker, model: i.model, serial: i.serial };
  });
  ctx.inst = inst;

  return ctx;
}

export async function generateDocxBlob(report: ReportData, client: Client): Promise<Blob> {
  if (report.report_kind === "completion") {
    throw new Error("竣工報告書のWordひな形が未登録です。竣工用のWordひな形を追加すると出力できます。");
  }

  const res = await fetch("/inspection-template.docx");
  if (!res.ok) throw new Error("テンプレートの読み込みに失敗しました");
  const arrayBuf = await res.arrayBuffer();

  const zip = new PizZip(arrayBuf);
  removeSkippedWordSections(zip, report);
  const doc = new Docxtemplater(zip, {
    paragraphLoop: true,
    linebreaks: true,
    delimiters: { start: "{{", end: "}}" },
    nullGetter: () => "",
    // ドット記法 `{{rpt.year_wareki}}` をネストオブジェクトとして解釈
    parser: (tag: string) => ({
      get: (scope: unknown) => {
        if (tag === ".") return scope;
        const keys = tag.split(".");
        let result: unknown = scope;
        for (const k of keys) {
          if (result == null || typeof result !== "object") return "";
          result = (result as Record<string, unknown>)[k];
        }
        return result == null ? "" : result;
      },
    }),
  });

  doc.render(buildContext(report, client));

  const out = doc.getZip().generate({
    type: "blob",
    mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  });
  return out;
}

export async function downloadDocx(
  report: ReportData,
  client: Client,
  saveDir: FileSystemDirectoryHandle | null,
): Promise<{ savedTo: string }> {
  const blob = await generateDocxBlob(report, client);
  const filename = makeFilename(report, client, "docx");

  if (saveDir) {
    try {
      const fileHandle = await saveDir.getFileHandle(filename, { create: true });
      const writable = await fileHandle.createWritable();
      await writable.write(blob);
      await writable.close();
      return { savedTo: `フォルダ「${saveDir.name}」内に保存` };
    } catch (e) {
      console.warn("フォルダ保存に失敗、通常DLにフォールバック", e);
    }
  }

  saveAs(blob, filename);
  return { savedTo: "ブラウザの既定ダウンロードフォルダ" };
}

export async function downloadPdf(
  report: ReportData,
  client: Client,
  saveDir: FileSystemDirectoryHandle | null,
): Promise<{ savedTo: string }> {
  return downloadDocx(report, client, saveDir);
}

const WORD_SECTION_RULES: { summaryId: string; start: string; end?: string }[] = [
  { summaryId: "r07", start: "接地抵抗測定", end: "高 圧 関 係 絶 縁 抵 抗 試 験" },
  { summaryId: "r06", start: "高 圧 関 係 絶 縁 抵 抗 試 験", end: "地 絡 方 向 継 電 器 試 験" },
  { summaryId: "r02", start: "地 絡 方 向 継 電 器 試 験", end: "過 電 流 継 電 器 試 験" },
  { summaryId: "r01", start: "過 電 流 継 電 器 試 験", end: "地絡過電圧継電器試験" },
  { summaryId: "r03", start: "地絡過電圧継電器試験", end: "アレイNO" },
  { summaryId: "r22", start: "アレイNO", end: "絶縁抵抗測定(太陽電池アレイ)" },
  { summaryId: "r11", start: "絶縁抵抗測定(太陽電池アレイ)", end: "【PCSの保護継電器の機能確認及び総合連動試験】" },
  { summaryId: "r23", start: "【PCSの保護継電器の機能確認及び総合連動試験】" },
];

function removeSkippedWordSections(zip: PizZip, report: ReportData) {
  const skipped = new Set(report.summary.filter((item) => item.result === "").map((item) => item.id));
  if (skipped.size === 0) return;

  const file = zip.file("word/document.xml");
  if (!file) return;

  let xml = file.asText();
  for (const rule of WORD_SECTION_RULES) {
    if (!skipped.has(rule.summaryId)) continue;
    xml = removeWordSection(xml, rule.start, rule.end);
  }
  xml = repairBodySectionProperties(xml);
  xml = removeOrphanedBookmarkMarkers(xml);

  zip.file("word/document.xml", xml);
}

function removeWordSection(xml: string, startText: string, endText?: string): string {
  const startTextIndex = findWordTextIndex(xml, startText);
  if (startTextIndex < 0) return xml;

  const endTextIndex = endText
    ? findWordTextIndex(xml, endText, startTextIndex + 1)
    : xml.indexOf("<w:sectPr", startTextIndex);
  if (endTextIndex < 0) return xml;

  const startIndex = findContainingBlockStart(xml, startTextIndex);
  const endIndex = endText ? findContainingBlockStart(xml, endTextIndex) : endTextIndex;
  if (startIndex < 0 || endIndex <= startIndex) return xml;

  return xml.slice(0, startIndex) + xml.slice(endIndex);
}

function findContainingBlockStart(xml: string, index: number): number {
  const tableIndex = findLastOpenTagStart(xml, "tbl", index);
  const tableEndIndex = xml.lastIndexOf("</w:tbl>", index);
  if (tableIndex > tableEndIndex) return tableIndex;

  return findLastOpenTagStart(xml, "p", index);
}

function findLastOpenTagStart(xml: string, tagName: string, beforeIndex: number): number {
  const pattern = new RegExp(`<w:${escapeRegex(tagName)}(?:\\s|>)`, "g");
  let lastIndex = -1;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(xml))) {
    if (match.index > beforeIndex) break;
    lastIndex = match.index;
  }
  return lastIndex;
}

function repairBodySectionProperties(xml: string): string {
  return xml.replace(/<w:p\b[^>]*>(?:<w:pPr>[\s\S]*?<\/w:pPr>)?(<w:sectPr\b[\s\S]*?<\/w:sectPr>)/g, "$1");
}

function removeOrphanedBookmarkMarkers(xml: string): string {
  const startIds = new Set(
    Array.from(xml.matchAll(/<w:bookmarkStart\b[^>]*\bw:id="([^"]+)"[^>]*\/>/g)).map((match) => match[1]),
  );
  const endIds = new Set(
    Array.from(xml.matchAll(/<w:bookmarkEnd\b[^>]*\bw:id="([^"]+)"[^>]*\/>/g)).map((match) => match[1]),
  );

  let cleaned = xml.replace(/<w:bookmarkStart\b[^>]*\bw:id="([^"]+)"[^>]*\/>/g, (match, id: string) =>
    endIds.has(id) ? match : "",
  );
  cleaned = cleaned.replace(/<w:bookmarkEnd\b[^>]*\bw:id="([^"]+)"[^>]*\/>/g, (match, id: string) =>
    startIds.has(id) ? match : "",
  );
  return cleaned;
}

function findWordTextIndex(xml: string, searchText: string, fromIndex = 0): number {
  const target = normalizeSearchText(searchText);
  if (!target) return -1;

  let text = "";
  const map: number[] = [];
  const textPattern = /<w:t[^>]*>([\s\S]*?)<\/w:t>/g;
  let match: RegExpExecArray | null;

  while ((match = textPattern.exec(xml))) {
    const raw = unescapeXmlText(match[1]);
    const rawStart = match.index + match[0].indexOf(">") + 1;
    for (let i = 0; i < raw.length; i++) {
      const char = raw[i];
      if (/\s/.test(char)) continue;
      text += char;
      map.push(rawStart + i);
    }
  }

  const normalizedFrom = map.findIndex((xmlIndex) => xmlIndex >= fromIndex);
  const found = text.indexOf(target, Math.max(0, normalizedFrom));
  return found >= 0 ? map[found] : -1;
}

function normalizeSearchText(value: string): string {
  return value.replace(/\s/g, "");
}

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function unescapeXmlText(value: string): string {
  return value
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&amp;/g, "&");
}

function makeFilename(report: ReportData, client: Client, ext: string): string {
  const safeName = client.name.replace(/[\\/:*?"<>|]/g, "");
  const reportName = report.report_kind === "completion" ? "竣工報告書" : "年次点検記録";
  return `R${report.year_wareki}_${safeName}_${reportName}_${report.year_wareki}-${report.month}-${report.day}.${ext}`;
}
