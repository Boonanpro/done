import type { Client, Equipment, Judge, MeasuringInstrument, ReportData, ReportKind } from "./types";

// 範囲内の値を小数1桁または整数で返す
function rand(min: number, max: number, digits = 1): string {
  const v = Math.random() * (max - min) + min;
  if (digits === 0) return String(Math.round(v));
  return v.toFixed(digits);
}

function randInt(min: number, max: number): number {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

const SUMMARY_LABELS: { id: string; no: string; label: string }[] = [
  { id: "r01", no: "１", label: "過電流継電器の動作" },
  { id: "r02", no: "２", label: "高圧地絡継電器の動作" },
  { id: "r03", no: "３", label: "電圧継電器の動作" },
  { id: "r04", no: "４", label: "高圧機器の塵埃・清掃" },
  { id: "r05", no: "５", label: "高圧開閉装置操作機構" },
  { id: "r06", no: "６", label: "高圧関係絶縁抵抗" },
  { id: "r07", no: "７", label: "接地抵抗・接地状況" },
  { id: "r08", no: "８", label: "配電盤表示灯" },
  { id: "r09", no: "９", label: "各配電盤の締付状況" },
  { id: "r10", no: "10", label: "計器の指示" },
  { id: "r11", no: "11", label: "低圧関係絶縁抵抗" },
  { id: "r12", no: "12", label: "絶縁油試験" },
  { id: "r13", no: "13", label: "各種警報表示装置" },
  { id: "r14", no: "14", label: "開閉器・ヒューズ等の容量" },
  { id: "r15", no: "15", label: "高圧ヒューズの予備" },
  { id: "r16", no: "16", label: "低圧ヒューズの予備" },
  { id: "r17", no: "17", label: "高圧ケーブル埋設表示" },
  { id: "r18", no: "18", label: "小動物進入防止対策" },
  { id: "r19", no: "19", label: "立ち入り禁止表示" },
  { id: "r20", no: "20", label: "ジスコン棒" },
  { id: "r21", no: "21", label: "キュービクル状況" },
  { id: "r22", no: "22", label: "太陽電池アレイ" },
  { id: "r23", no: "23", label: "パワーコンディショナー" },
];

const EXTERNAL_LABELS: { id: string; label: string }[] = [
  { id: "r01", label: "引込設備" },
  { id: "r02", label: "受電室・電気室／キュービクル式 受・変電設備" },
  { id: "r03", label: "遮断器・開閉器／断路器" },
  { id: "r04", label: "電力ヒューズ／計器用変成器／母線" },
  { id: "r05", label: "変圧器" },
  { id: "r06", label: "配電盤／制御回路" },
  { id: "r07", label: "蓄電池／充電装置" },
  { id: "r08", label: "接地装置（接地線・保護管等）" },
  { id: "r09", label: "配電設備" },
];

const PCS_LABELS: { id: string; label: string }[] = [
  { id: "r01", label: "交流周波数上昇" },
  { id: "r02", label: "交流周波数低下" },
  { id: "r03", label: "交流不足電圧" },
  { id: "r04", label: "交流過電圧" },
  { id: "r05", label: "受動的単独運転検出機能（電圧位相跳躍）" },
  { id: "r06", label: "能動的単独運転検出機能（スリップモード周波数シフト方式）" },
  { id: "r07", label: "地絡過電圧" },
  { id: "r08", label: "復電後にPCSが運転しない事の確認" },
  { id: "r09", label: "故障リセットによりPCSが正常運転する事を確認" },
  { id: "r10", label: "各警報や表示等が正常動作する事を確認" },
];

// 17, 23 → 「該当なし」（空選択 = no/label/result 全部空）
const SUMMARY_EMPTY_IDS = new Set(["r17", "r23"]);
const SUMMARY_DASH_IDS = new Set(["r12"]); // 絶縁油試験 → 「－」

const WEATHERS = ["晴", "くもり", "雨", "晴のち曇り", "くもり時々雨"];

export function generateReport(
  client: Client,
  equipmentMap: Map<string, Equipment>,
  instrumentMap: Map<string, MeasuringInstrument>,
  todayWareki = 8,
  todayMonth = 4,
  todayDay = 7,
  reportKind: ReportKind = "annual",
): ReportData {
  const pas = client.pas_equipment_id ? equipmentMap.get(client.pas_equipment_id) : undefined;
  const dgrRelay = client.dgr_relay_id ? equipmentMap.get(client.dgr_relay_id) : undefined;
  const ocrEq = client.ocr_equipment_id ? equipmentMap.get(client.ocr_equipment_id) : undefined;
  const ovgrEq = client.ovgr_equipment_id ? equipmentMap.get(client.ovgr_equipment_id) : undefined;

  // 接地抵抗 6項目
  const ground = client.ground_items.map((g, idx) => ({
    id: `g${idx + 1}`,
    name: g.name,
    type: g.type,
    value: rand(g.range_min, g.range_max, g.range_max < 10 ? 1 : 0),
    judge: "良" as const,
  }));

  // 高圧絶縁抵抗 8項目
  const hv = client.hv_circuits.map((c, idx) => ({
    id: `h${idx + 1}`,
    name: c.name,
    voltage: c.voltage,
    value: c.has_value ? rand(c.range_min, c.range_max, 0) + (c.unit ? `〔${c.unit}〕` : "") : "－",
    judge: c.has_value ? ("良" as const) : ("－" as const),
  }));

  // アレイ
  const array = Array.from({ length: client.array_count }, (_, i) => ({
    id: i + 1,
    value: rand(client.array_value_min, client.array_value_max, 0),
    judge: "良" as const,
  }));

  // 接続箱
  const box = Array.from({ length: client.box_count }, (_, i) => ({
    id: i + 1,
    value: client.box_measure ? rand(client.box_value_min, client.box_value_max, 0) : "－",
    judge: "良" as const,
  }));

  // 低圧絶縁抵抗
  const lv = Array.from({ length: client.lv_circuit_count }, (_, i) => {
    const id = client.lv_circuit_start + i;
    return {
      id,
      rp: rand(client.lv_rp_min, client.lv_rp_max, 1),
      rn: rand(client.lv_rn_min, client.lv_rn_max, 1),
      judge: "良" as const,
    };
  });

  // 計測器
  const inst = client.measuring_instrument_ids.slice(0, 8).map((iid, idx) => {
    const m = instrumentMap.get(iid);
    return {
      id: `i${idx + 1}`,
      name: m?.name ?? "",
      maker: m?.maker ?? "",
      model: m?.model ?? "",
      serial: m?.serial ?? "",
    };
  });
  // 8件未満なら空で埋める
  while (inst.length < 8) {
    inst.push({ id: `i${inst.length + 1}`, name: "", maker: "", model: "", serial: "" });
  }

  // 総括（23項目）。result が「空」の項目は出力時に no/label も空欄化される
  const summary = SUMMARY_LABELS.map((s) => {
    let result: ReportData["summary"][number]["result"] = "良";
    if (SUMMARY_EMPTY_IDS.has(s.id)) result = "";
    if (SUMMARY_DASH_IDS.has(s.id)) result = "－";
    return { id: s.id, no: s.no, label: s.label, result };
  });

  // 外観点検
  const external = EXTERNAL_LABELS.map((e) => ({
    id: e.id,
    label: e.label,
    result: "良" as const,
  }));

  // PCS確認（基本「－/未確認」、3, 7, 8, 9, 10だけ点検日入り）
  const inspectDate = `2026年${todayMonth}月${todayDay}日`;
  const pcs = PCS_LABELS.map((p, idx) => {
    const num = idx + 1;
    if (num === 3) return { id: p.id, label: p.label, date: inspectDate, state: "解列", note: "" };
    if (num === 7) return { id: p.id, label: p.label, date: inspectDate, state: "解列", note: "試験釦による" };
    if (num === 8) return { id: p.id, label: p.label, date: "同上", state: "解列維持", note: "" };
    if (num === 9) return { id: p.id, label: p.label, date: "同上", state: "良", note: "" };
    if (num === 10) return { id: p.id, label: p.label, date: "同上", state: "良", note: "" };
    return { id: p.id, label: p.label, date: "－", state: "－", note: "未確認" };
  });

  // DGR
  const dgr = {
    pas_maker: pas?.maker ?? "",
    pas_model: pas?.model ?? "",
    pas_serial: pas?.serial ?? "",
    pas_mfg_date: pas?.mfg_date ?? "",
    relay_maker: dgrRelay?.maker ?? "",
    relay_model: dgrRelay?.model ?? "",
    relay_serial: dgrRelay?.serial ?? "",
    relay_mfg_date: dgrRelay?.mfg_date ?? "",
    relay_setting: dgrRelay?.setting ?? "",
    relay_setting2: dgrRelay?.setting2 ?? "",
    v_tap: "2",
    v_min: rand(75, 85, 0),
    i_tap: "0.2",
    i_min: rand(0.18, 0.22, 3),
    phase_lead: `進み ${randInt(118, 124)} 度`,
    phase_lag: `遅れ-${randInt(42, 48)}度`,
    t_tap: "0.3",
    t_i_a: rand(0.38, 0.40, 3),
    t_i_b: rand(0.78, 0.82, 3),
    t_a: rand(0.24, 0.28, 3),
    t_b: rand(0.13, 0.15, 3),
    linked_time: rand(0.30, 0.32, 3) + "秒 *",
    judge: "良" as const,
  };

  // OCR
  const ocr = {
    maker: ocrEq?.maker ?? "",
    model: ocrEq?.model ?? "",
    serial: ocrEq?.serial ?? "",
    mfg_date: ocrEq?.mfg_date ?? "",
    setting_limit: ocrEq?.setting ?? "",
    setting_inst: ocrEq?.setting2 ?? "",
    tap_at: "5",
    r_current: rand(4.7, 5.3, 1),
    t_current: rand(4.7, 5.3, 1),
    test_tap: "５At",
    r_300: rand(0.95, 1.15, 3),
    t_300: rand(0.95, 1.15, 3),
    inst_tap: "10",
    vcb_time: rand(0.07, 0.09, 3),
    indicator: "表示" as Judge,
    judge: "合格" as Judge,
  };

  // OVGR
  const ovgr = {
    maker: ovgrEq?.maker ?? "",
    model: ovgrEq?.model ?? "",
    model_no: ovgrEq?.model_no ?? "",
    serial: ovgrEq?.serial ?? "",
    mfg_date: ovgrEq?.mfg_date ?? "",
    setting: ovgrEq?.setting ?? "",
    v_op_3_5_a: rand(13.0, 13.4, 1),
    v_op_3_5_b: rand(13.0, 13.4, 1),
    v_op_3_5_judge: "良" as const,
    t_op_2_5_judge: "良" as const,
    t_op_3: rand(0.95, 1.05, 3),
    t_op_3_judge: "良" as const,
    indicator: "良" as const,
    judge: "合格" as Judge,
  };

  return {
    client_id: client.id,
    report_kind: reportKind,
    year_wareki: todayWareki,
    month: todayMonth,
    day: todayDay,
    weather: WEATHERS[Math.floor(Math.random() * WEATHERS.length)],
    temperature: randInt(5, 28),
    humidity: randInt(40, 85),
    inspector: client.inspector || "本田修",

    summary,
    external,
    ground,
    hv,
    dgr,
    ocr,
    ovgr,
    array,
    box,
    lv,
    pcs,
    inst,
  };
}
