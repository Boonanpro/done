import type {
  Judge,
  OutputPageKey,
  ReportConfigSnapshot,
  ReportData,
  ReportKind,
  ReportOutputConfig,
} from "./types";

export const OUTPUT_PAGE_DEFINITIONS: {
  key: OutputPageKey;
  summaryId?: string;
  label: string;
  description: string;
  reportKinds?: ReportKind[];
}[] = [
  { key: "ocr", summaryId: "r01", label: "過電流継電器", description: "OCR 試験ページ" },
  { key: "dgr", summaryId: "r02", label: "地絡継電器", description: "DGR/SOG 試験ページ" },
  { key: "ovgr", summaryId: "r03", label: "地絡過電圧継電器", description: "OVGR/不足電圧関連ページ" },
  { key: "hvInsulation", summaryId: "r06", label: "高圧絶縁", description: "高圧関係 絶縁抵抗試験" },
  { key: "groundResistance", summaryId: "r07", label: "接地抵抗", description: "接地抵抗測定ページ" },
  { key: "lvInsulation", summaryId: "r11", label: "低圧絶縁", description: "低圧絶縁抵抗測定ページ" },
  { key: "arrayInsulation", summaryId: "r22", label: "太陽電池アレイ", description: "アレイ絶縁測定ページ" },
  { key: "pcs", summaryId: "r23", label: "PCS", description: "PCS 保護継電器・総合連動試験" },
  {
    key: "generatorInspection",
    label: "発電機点検記録",
    description: "非常用予備発電装置の点検記録。年次点検のみ使用します。",
    reportKinds: ["annual"],
  },
];

const PAGE_KEY_BY_SUMMARY_ID = new Map(
  OUTPUT_PAGE_DEFINITIONS.flatMap((page) => (page.summaryId ? [[page.summaryId, page.key] as const] : [])),
);

export function getOutputPageKeyForSummaryId(summaryId: string): OutputPageKey | undefined {
  return PAGE_KEY_BY_SUMMARY_ID.get(summaryId);
}

export function getOutputPagesForReportKind(reportKind: ReportKind) {
  return OUTPUT_PAGE_DEFINITIONS.filter((page) => !page.reportKinds || page.reportKinds.includes(reportKind));
}

export function createDefaultOutputConfig(reportKind: ReportKind): ReportOutputConfig {
  return {
    pages: {
      ocr: true,
      dgr: true,
      ovgr: true,
      hvInsulation: true,
      groundResistance: true,
      lvInsulation: reportKind === "annual",
      arrayInsulation: true,
      pcs: true,
      generatorInspection: false,
    },
    lvInsulationPageCount: reportKind === "annual" ? 1 : 0,
    summaryVisibility: {},
  };
}

export function deriveOutputConfigFromSummary(
  summary: ReportData["summary"],
  reportKind: ReportKind,
): ReportOutputConfig {
  const defaults = createDefaultOutputConfig(reportKind);
  const pages = { ...defaults.pages };
  const summaryVisibility: Record<string, boolean> = {};

  for (const item of summary) {
    summaryVisibility[item.id] = item.result !== "";
    const key = PAGE_KEY_BY_SUMMARY_ID.get(item.id);
    if (key) pages[key] = item.result !== "";
  }

  return {
    pages,
    lvInsulationPageCount: pages.lvInsulation ? Math.max(defaults.lvInsulationPageCount, 1) : 0,
    summaryVisibility,
  };
}

export function applyOutputConfigToSummary(
  summary: ReportData["summary"],
  config: ReportOutputConfig,
): ReportData["summary"] {
  return summary.map((item) => {
    const key = PAGE_KEY_BY_SUMMARY_ID.get(item.id);
    if (!key) {
      const visible = config.summaryVisibility[item.id] ?? item.result !== "";
      if (!visible) return { ...item, result: "" };
      return { ...item, result: item.result === "" ? ("良" as Judge) : item.result };
    }

    const enabled = key === "lvInsulation" ? config.lvInsulationPageCount > 0 : config.pages[key];
    if (!enabled) return { ...item, result: "" };
    return { ...item, result: item.result === "" ? ("良" as Judge) : item.result };
  });
}

export function normalizeOutputConfig(config: ReportOutputConfig): ReportOutputConfig {
  const lvInsulationPageCount = clampLvPageCount(config.lvInsulationPageCount);
  const pages = {
    ...createDefaultOutputConfig("annual").pages,
    ...config.pages,
    lvInsulation: lvInsulationPageCount > 0,
  };
  return {
    pages,
    lvInsulationPageCount,
    summaryVisibility: config.summaryVisibility ?? {},
  };
}

export function applySavedConfig(report: ReportData, saved?: ReportConfigSnapshot): ReportData {
  const baseReport = report.report_kind === "completion" ? forceCompletionDefaultSummary(report) : report;
  const defaultConfig =
    baseReport.report_kind === "annual"
      ? deriveOutputConfigFromSummary(baseReport.summary, baseReport.report_kind)
      : createDefaultOutputConfig(baseReport.report_kind);
  if (!saved) {
    const outputConfig = normalizeOutputConfig(defaultConfig);
    return { ...baseReport, outputConfig, summary: applyOutputConfigToSummary(baseReport.summary, outputConfig) };
  }

  const summaryResults = saved.summaryResults ?? {};
  const summary = baseReport.summary.map((item) => ({
    ...item,
    result: summaryResults[item.id] ?? item.result,
  }));
  const outputConfig = normalizeOutputConfig(saved.outputConfig ?? defaultConfig);

  return {
    ...baseReport,
    inspector: saved.inspector || baseReport.inspector,
    inst: saved.instruments?.length ? saved.instruments : baseReport.inst,
    outputConfig,
    summary: applyOutputConfigToSummary(summary, outputConfig),
  };
}

export function snapshotReportConfig(report: ReportData): ReportConfigSnapshot {
  const outputConfig = normalizeOutputConfig(report.outputConfig);
  return {
    outputConfig,
    summaryResults: Object.fromEntries(report.summary.map((item) => [item.id, item.result])),
    inspector: report.inspector,
    instruments: report.inst,
  };
}

export function updateReportOutputConfig(
  report: ReportData,
  patch: Partial<Omit<ReportOutputConfig, "pages">> & {
    pages?: Partial<Record<OutputPageKey, boolean>>;
    summaryVisibility?: Record<string, boolean>;
  },
): Pick<ReportData, "outputConfig" | "summary"> {
  const outputConfig = normalizeOutputConfig({
    ...report.outputConfig,
    ...patch,
    pages: {
      ...report.outputConfig.pages,
      ...patch.pages,
    },
    summaryVisibility: {
      ...report.outputConfig.summaryVisibility,
      ...patch.summaryVisibility,
    },
  });

  return {
    outputConfig,
    summary: applyOutputConfigToSummary(report.summary, outputConfig),
  };
}

function clampLvPageCount(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(5, Math.round(value)));
}

function forceCompletionDefaultSummary(report: ReportData): ReportData {
  return {
    ...report,
    summary: report.summary.map((item) => {
      if (item.id === "r11") return item;
      return { ...item, result: item.result === "" ? ("良" as Judge) : item.result };
    }),
  };
}
