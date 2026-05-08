export type Judge = "良" | "不良" | "" | "－";
export type ReportKind = "annual" | "completion";

export type OutputPageKey =
  | "ocr"
  | "dgr"
  | "ovgr"
  | "hvInsulation"
  | "groundResistance"
  | "lvInsulation"
  | "arrayInsulation"
  | "pcs";

export type ReportOutputConfig = {
  pages: Record<OutputPageKey, boolean>;
  lvInsulationPageCount: number;
};

export type ReportConfigSnapshot = {
  outputConfig: ReportOutputConfig;
  summaryResults: Record<string, Judge>;
  inspector: string;
  instruments: ReportData["inst"];
};

// 機器マスタ（PAS / 各種継電器 / 変圧器 など）
export type Equipment = {
  id: string;
  category: "pas" | "dgr_relay" | "ocr" | "ovgr" | "transformer" | "other";
  category_label: string;
  maker: string;
  model: string;
  model_no?: string;
  serial: string;
  mfg_date: string;
  setting?: string;
  setting2?: string;
  notes?: string;
};

// 計測器マスタ（試験で使う機材）
export type MeasuringInstrument = {
  id: string;
  name: string;
  maker: string;
  model: string;
  serial: string;
};

// クライアントの接地抵抗対象物（設備固定）
export type GroundItem = {
  name: string;
  type: string; // EA, EB, EC など
  range_min: number;
  range_max: number;
  note: string;
};

// クライアントの高圧絶縁抵抗回路
export type HvCircuit = {
  name: string;
  voltage: string;
  has_value: boolean;
  range_min: number;
  range_max: number;
  unit: string;
};

// クライアント = 案件
export type Client = {
  id: string;
  name: string;
  facility_name: string;
  inspector: string;

  ground_items: GroundItem[];
  hv_circuits: HvCircuit[];

  array_count: number;
  array_value_min: number;
  array_value_max: number;

  box_count: number;
  box_measure: boolean;
  box_value_min: number;
  box_value_max: number;

  lv_circuit_count: number;
  lv_circuit_start: number;
  lv_rp_min: number;
  lv_rp_max: number;
  lv_rn_min: number;
  lv_rn_max: number;

  pas_equipment_id: string;
  dgr_relay_id: string;
  ocr_equipment_id: string;
  ovgr_equipment_id: string;

  measuring_instrument_ids: string[];
};

// 1回の点検レポートで生成される全データ
export type ReportData = {
  client_id: string;
  report_kind: ReportKind;

  // 表紙
  year_wareki: number;
  month: number;
  day: number;
  weather: string;
  temperature: number;
  humidity: number;
  inspector: string;

  // Table 0 総括（最大23項目）。「空」選択時は no/label/result すべて空にする
  summary: { id: string; no: string; label: string; result: Judge }[];

  outputConfig: ReportOutputConfig;

  // Table 1 外観点検
  external: { id: string; label: string; result: Judge }[];

  // Table 2 接地抵抗 6項目
  ground: { id: string; name: string; type: string; value: string; judge: Judge }[];

  // Table 2 高圧絶縁抵抗
  hv: { id: string; name: string; voltage: string; value: string; judge: Judge }[];

  // Table 3 DGR
  dgr: {
    pas_maker: string;
    pas_model: string;
    pas_serial: string;
    pas_mfg_date: string;
    relay_maker: string;
    relay_model: string;
    relay_serial: string;
    relay_mfg_date: string;
    relay_setting: string;
    relay_setting2: string;
    v_tap: string;
    v_min: string;
    i_tap: string;
    i_min: string;
    phase_lead: string;
    phase_lag: string;
    t_tap: string;
    t_i_a: string;
    t_i_b: string;
    t_a: string;
    t_b: string;
    linked_time: string;
    judge: Judge;
  };

  // Table 4 OCR
  ocr: {
    maker: string;
    model: string;
    serial: string;
    mfg_date: string;
    setting_limit: string;
    setting_inst: string;
    tap_at: string;
    r_current: string;
    t_current: string;
    test_tap: string;
    r_300: string;
    t_300: string;
    inst_tap: string;
    vcb_time: string;
    indicator: Judge;
    judge: Judge;
  };

  // Table 5 OVGR
  ovgr: {
    maker: string;
    model: string;
    model_no: string;
    serial: string;
    mfg_date: string;
    setting: string;
    v_op_3_5_a: string;
    v_op_3_5_b: string;
    v_op_3_5_judge: Judge;
    t_op_2_5_judge: Judge;
    t_op_3: string;
    t_op_3_judge: Judge;
    indicator: Judge;
    judge: Judge;
  };

  // Table 6 アレイ / 接続箱
  array: { id: number; value: string; judge: Judge }[];
  box: { id: number; value: string; judge: Judge }[];

  // Table 7 低圧絶縁抵抗
  lv: { id: number; rp: string; rn: string; judge: Judge }[];

  // Table 8 PCS保護継電器確認
  pcs: { id: string; label: string; date: string; state: string; note: string }[];

  // Table 9 計測器
  inst: { id: string; name: string; maker: string; model: string; serial: string }[];
};
