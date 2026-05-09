import type { Client, Equipment, MeasuringInstrument } from "./types";

// 機器マスタ（共通プール）— 島津組ベース
export const initialEquipments: Equipment[] = [
  {
    id: "eq-pas-togami-klt",
    category: "pas",
    category_label: "開閉器（PAS）",
    maker: "戸上電機",
    model: "KLT-PSA-D2N11LT",
    serial: "－",
    mfg_date: "2013年4月",
    notes: "受電回路用",
  },
  {
    id: "eq-dgr-togami-ltr",
    category: "dgr_relay",
    category_label: "地絡方向継電器（DGR）",
    maker: "戸上電機",
    model: "LTR-P-D",
    serial: "A888471",
    mfg_date: "2013年4月",
    setting: "Ｖ0＝ 2 ％／Ｉ0＝ 0.2Ａ／時限＝ 0.2 秒",
    setting2: "Ｖ0＝ 2 ％／Ｉ0＝ 0.2Ａ／時限＝ 0.2 秒",
  },
  {
    id: "eq-ocr-mitsubishi-moc",
    category: "ocr",
    category_label: "過電流継電器（OCR）",
    maker: "三　菱",
    model: "ＭＯＣ－Ａ１Ｖ－Ｒ",
    serial: "7E101CM4031",
    mfg_date: "2013年－月",
    setting: "5At　　1Ｌ",
    setting2: "35At（CT＝30／5A）",
  },
  {
    id: "eq-ovgr-mitsubishi-cvg",
    category: "ovgr",
    category_label: "地絡過電圧継電器（OVGR）",
    maker: "三　菱",
    model: "CVG1-A02S1",
    model_no: "371PQB",
    serial: "8S87PP00011",
    mfg_date: "2020年－月",
    setting: "動作電圧：2.5（％）／動作時間：１（Ｓ）",
  },
];

// 計測器マスタ（点検側が持っている試験機。お父さん共通）
export const initialInstruments: MeasuringInstrument[] = [
  { id: "mi-1", name: "接地抵抗計", maker: "双 興 電 機", model: "ECT-1000", serial: "17E020090" },
  { id: "mi-2", name: "絶縁抵抗計", maker: "三和電気計器", model: "DM-1008S", serial: "1105080056" },
  { id: "mi-3", name: "絶縁抵抗計", maker: "HIOKI", model: "IR-4032", serial: "150338364" },
  { id: "mi-4", name: "絶縁抵抗計", maker: "HIOKI", model: "IR-4055", serial: "170538276" },
  { id: "mi-5", name: "過電流継電器試験装置", maker: "双 興 電 機", model: "OCR-50CK", serial: "16X080273" },
  { id: "mi-6", name: "電圧要素テスタ", maker: "双 興 電 機", model: "TVD-1000K", serial: "6T0602581" },
  { id: "mi-7", name: "位相特性試験装置", maker: "ムサシインテック", model: "2235", serial: "618104" },
  { id: "mi-8", name: "ハイボルトテスター", maker: "双 興 電 機", model: "HVT-11K", serial: "14H040252" },
];

// クライアントマスタ（島津組がサンプル）
export const initialClients: Client[] = [
  {
    id: "client-shimazu",
    name: "株式会社 島津組",
    facility_name: "島津組一部太陽光発電所",
    inspector: "本田修",

    ground_items: [
      { name: "高圧機器外箱", type: "EA", range_min: 5, range_max: 9, note: "1.4.6共用接地" },
      { name: "変圧器二次電路", type: "EB", range_min: 14, range_max: 22, note: "1.4.6共用接地" },
      { name: "電柱PAS(避雷器内蔵)", type: "EA", range_min: 7, range_max: 11, note: "1.4.6共用接地" },
      { name: "低圧機器外箱", type: "EC", range_min: 5, range_max: 9, note: "1.4.6共用接地" },
      { name: "キュービクル避雷器", type: "EA", range_min: 5, range_max: 9, note: "1.4.6共用接地" },
      { name: "パワーコンディショナ", type: "EC", range_min: 5, range_max: 9, note: "1.4.6共用接地" },
    ],

    hv_circuits: [
      { name: "高圧ケーブル（Ｇ端子接地方式） 5,000V", voltage: "5,000", has_value: false, range_min: 0, range_max: 0, unit: "ＧΩ" },
      { name: "高圧ケーブル（Ｇ端子接地方式） 10,000V", voltage: "10,000", has_value: false, range_min: 0, range_max: 0, unit: "ＧΩ" },
      { name: "高圧ケーブル 弱点比", voltage: "弱点比", has_value: false, range_min: 0, range_max: 0, unit: "倍" },
      { name: "高圧ケーブル キック現象", voltage: "キック現象", has_value: false, range_min: 0, range_max: 0, unit: "" },
      { name: "高圧ケーブル シース", voltage: "シース", has_value: true, range_min: 1300, range_max: 1600, unit: "MΩ" },
      { name: "高圧ケーブル 総合判定", voltage: "総 合 判 定", has_value: false, range_min: 0, range_max: 0, unit: "" },
      { name: "高圧一括", voltage: "5,000", has_value: true, range_min: 10, range_max: 13, unit: "ＧΩ" },
      { name: "PAS2次〜DS1次", voltage: "〃", has_value: false, range_min: 0, range_max: 0, unit: "" },
      { name: "DS2次一括", voltage: "〃", has_value: true, range_min: 90, range_max: 110, unit: "ＧΩ" },
      { name: "DS2次〜VCB1次", voltage: "〃", has_value: false, range_min: 0, range_max: 0, unit: "" },
      { name: "VCB2次一括", voltage: "〃", has_value: false, range_min: 0, range_max: 0, unit: "" },
      { name: "3φ250kVA変圧器", voltage: "〃", has_value: false, range_min: 0, range_max: 0, unit: "" },
    ],

    array_count: 16,
    array_value_min: 3,
    array_value_max: 5,

    box_count: 16,
    box_measure: false,
    box_value_min: 3,
    box_value_max: 5,

    lv_circuit_count: 16,
    lv_circuit_start: 101,
    lv_rp_min: 0.8,
    lv_rp_max: 1.6,
    lv_rn_min: 0.7,
    lv_rn_max: 1.3,

    pas_equipment_id: "eq-pas-togami-klt",
    dgr_relay_id: "eq-dgr-togami-ltr",
    ocr_equipment_id: "eq-ocr-mitsubishi-moc",
    ovgr_equipment_id: "eq-ovgr-mitsubishi-cvg",

    measuring_instrument_ids: ["mi-1", "mi-2", "mi-3", "mi-4", "mi-5", "mi-6", "mi-7", "mi-8"],
  },
];
