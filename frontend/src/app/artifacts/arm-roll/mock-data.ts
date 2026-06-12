// 10tアームロール (CCA101*-20) パーツカタログ デモデータ
// 部品名・符号・枝番は、友人提供の実カタログ平面図
//   「各部名称 / 機種:10tアームロール(CCA101*-20) / パーツカタログNo:F-3401-E0037」
// に忠実。品番(末尾5桁)・価格・在庫・納期はデモ用の仮値。
// 本番化には各部品の詳細ページ(品番が出る画面)が必要。

export type StockStatus = "in_stock" | "low_stock" | "out_of_stock" | "made_to_order";

export type PartCategory =
  | "arm" // アーム機構
  | "hydraulic" // 油圧系
  | "jack" // ジャッキ
  | "frame" // フレーム
  | "chassis" // シャシ(架装メーカー扱い)
  | "electrical" // 電装
  | "accessory"; // アクセサリ

export type PartMeshId =
  | "cab"
  | "frame"
  | "arm"
  | "hook"
  | "lift-cyl"
  | "slide-cyl"
  | "jack-cyl"
  | "container-lock-cyl"
  | "jack"
  | "pump"
  | "control-valve"
  | "oil-tank"
  | "piping"
  | "wiring"
  | "wheel-front"
  | "wheel-rear"
  | "accessory";

export type Part = {
  id: string;
  partNumber: string; // 仮品番
  name: string;
  nameRomaji?: string;
  category: PartCategory;
  modelCompat: string[];
  price: number;
  stock: StockStatus;
  leadTime: string;
  imageRef?: string; // カタログ符号-枝番
  remark?: string; // カタログ備考
  provisional?: boolean; // 品番が仮かどうか
  description: string;
  meshId: PartMeshId;
};

export const CATEGORY_LABEL: Record<PartCategory, string> = {
  arm: "アーム機構",
  hydraulic: "油圧系",
  jack: "ジャッキ",
  frame: "フレーム",
  chassis: "シャシ",
  electrical: "電装",
  accessory: "アクセサリ",
};

export const MESH_LABEL: Record<PartMeshId, string> = {
  cab: "キャブ (運転席)",
  frame: "フレームSETG",
  arm: "アームASSY",
  hook: "ロック&フックSETG",
  "lift-cyl": "リフトCYL.ASSY",
  "slide-cyl": "スライドCYL.ASSY",
  "jack-cyl": "ジャッキCYL.ASSY",
  "container-lock-cyl": "コンテナロックCYL.ASSY",
  jack: "ジャッキSETG",
  pump: "ポンプ / プランジャポンプ",
  "control-valve": "コントロールバルブASSY",
  "oil-tank": "オイルリザーバASSY",
  piping: "パイピング",
  wiring: "エレクトリカルワイヤリング",
  "wheel-front": "前輪 (シャシ)",
  "wheel-rear": "後輪 (シャシ)",
  accessory: "アクセサリ",
};

export type VehicleModel = {
  id: string;
  modelCode: string;
  catalogCode: string;
  series: string;
  productionPeriod: string;
  description: string;
};

export const VEHICLE_MODELS: VehicleModel[] = [
  {
    id: "cca101-20",
    modelCode: "CCA101*-20(*)",
    catalogCode: "F-3401-E0037",
    series: "10t アームロール",
    productionPeriod: "脱着ボデー車 (コンテナ脱着式)",
    description: "10t積 アームロール / フックリフト式 脱着車",
  },
];

export const PARTS: Part[] = [
  // ── アーム機構 ──
  {
    id: "p10a",
    partNumber: "1F-3401-10010",
    name: "アームASSY",
    nameRomaji: "Arm ASSY",
    category: "arm",
    modelCompat: ["CCA101*-20(*)"],
    price: 684000,
    stock: "made_to_order",
    leadTime: "3~4週間",
    imageRef: "10-1",
    provisional: true,
    description: "コンテナを引き上げ・押し出しする主アーム。フックリフトの中核部品。",
    meshId: "arm",
  },
  {
    id: "p10b",
    partNumber: "1F-3401-10020",
    name: "アームASSY (後期型)",
    nameRomaji: "Arm ASSY (late)",
    category: "arm",
    modelCompat: ["CCA101*-20(*)"],
    price: 712000,
    stock: "made_to_order",
    leadTime: "3~4週間",
    imageRef: "10-2",
    provisional: true,
    description: "主アームの後期仕様。取付互換は要確認。",
    meshId: "arm",
  },
  {
    id: "p11",
    partNumber: "1F-3401-11010",
    name: "ロック&フックSETG",
    nameRomaji: "Lock & Hook SETG",
    category: "arm",
    modelCompat: ["CCA101*-20(*)"],
    price: 148000,
    stock: "low_stock",
    leadTime: "5営業日",
    imageRef: "11",
    provisional: true,
    description: "アーム先端のフックとコンテナ固定ロック。摩耗・安全部品。",
    meshId: "hook",
  },

  // ── 油圧シリンダー類 ──
  {
    id: "p03a",
    partNumber: "1F-3401-03010",
    name: "リフトCYL.ASSY",
    nameRomaji: "Lift Cylinder ASSY",
    category: "hydraulic",
    modelCompat: ["CCA101*-20(*)"],
    price: 196000,
    stock: "in_stock",
    leadTime: "即日",
    imageRef: "03-00",
    remark: "修理についてはサービスニュースNO.1338を準用の事。",
    provisional: true,
    description: "アームを起立・倒伏させる主油圧シリンダー。左右2本。",
    meshId: "lift-cyl",
  },
  {
    id: "p03b",
    partNumber: "1F-3401-03011",
    name: "リフトCYL.ASSY (互換)",
    nameRomaji: "Lift Cylinder ASSY (compat)",
    category: "hydraulic",
    modelCompat: ["CCA101*-20(*)"],
    price: 208000,
    stock: "in_stock",
    leadTime: "即日",
    imageRef: "03-01",
    remark: "ASSY互換部品(大窪製) 2007年9月より併用架装。",
    provisional: true,
    description: "リフトCYLの互換ASSY。2007年9月以降の架装で併用。",
    meshId: "lift-cyl",
  },
  {
    id: "p04",
    partNumber: "1F-3401-04010",
    name: "スライドCYL.ASSY",
    nameRomaji: "Slide Cylinder ASSY",
    category: "hydraulic",
    modelCompat: ["CCA101*-20(*)"],
    price: 174000,
    stock: "low_stock",
    leadTime: "5営業日",
    imageRef: "04-00",
    provisional: true,
    description: "コンテナを前後にスライドさせる油圧シリンダー。",
    meshId: "slide-cyl",
  },
  {
    id: "p06",
    partNumber: "1F-3401-06010",
    name: "コンテナロックCYL.ASSY",
    nameRomaji: "Container Lock Cylinder ASSY",
    category: "hydraulic",
    modelCompat: ["CCA101*-20(*)"],
    price: 58000,
    stock: "in_stock",
    leadTime: "即日",
    imageRef: "06-00",
    provisional: true,
    description: "コンテナを車体に固定する油圧ロックシリンダー。",
    meshId: "container-lock-cyl",
  },
  {
    id: "p05a",
    partNumber: "1F-3401-05010",
    name: "ジャッキCYL.ASSY (~2003.8)",
    nameRomaji: "Jack Cylinder ASSY",
    category: "jack",
    modelCompat: ["CCA101*-20(*)"],
    price: 92000,
    stock: "in_stock",
    leadTime: "即日",
    imageRef: "05-00",
    remark: "H15年8月迄 (~2003.8)",
    provisional: true,
    description: "後端アウトリガーを張り出す油圧シリンダー。2003年8月までの仕様。",
    meshId: "jack-cyl",
  },
  {
    id: "p05b",
    partNumber: "1F-3401-05011",
    name: "ジャッキCYL.ASSY (2003.9~)",
    nameRomaji: "Jack Cylinder ASSY",
    category: "jack",
    modelCompat: ["CCA101*-20(*)"],
    price: 96000,
    stock: "in_stock",
    leadTime: "即日",
    imageRef: "05-01",
    remark: "H15年9月以降 (2003.9~)",
    provisional: true,
    description: "後端アウトリガー用シリンダー。2003年9月以降の仕様。",
    meshId: "jack-cyl",
  },

  // ── 油圧駆動・配管 ──
  {
    id: "p01",
    partNumber: "1F-3401-01010",
    name: "ポンプSETG",
    nameRomaji: "Pump SETG",
    category: "hydraulic",
    modelCompat: ["CCA101*-20(*)"],
    price: 268000,
    stock: "made_to_order",
    leadTime: "2週間",
    imageRef: "01-00",
    provisional: true,
    description: "油圧の元圧を作るメインポンプ一式。全機構の動力源。",
    meshId: "pump",
  },
  {
    id: "p07",
    partNumber: "1F-3401-07010",
    name: "プランジャポンプ ASSY",
    nameRomaji: "Plunger Pump ASSY",
    category: "hydraulic",
    modelCompat: ["CCA101*-20(*)"],
    price: 312000,
    stock: "made_to_order",
    leadTime: "2~3週間",
    imageRef: "07-00",
    provisional: true,
    description: "高圧プランジャ式ポンプASSY。アーム・スライド駆動の主力。",
    meshId: "pump",
  },
  {
    id: "p08",
    partNumber: "1F-3401-08010",
    name: "コントロールバルブ ASSY",
    nameRomaji: "Control Valve ASSY",
    category: "hydraulic",
    modelCompat: ["CCA101*-20(*)"],
    price: 142000,
    stock: "low_stock",
    leadTime: "5営業日",
    imageRef: "08-00",
    provisional: true,
    description: "各シリンダーへの油の流れを切替える操作バルブ。",
    meshId: "control-valve",
  },
  {
    id: "p09",
    partNumber: "1F-3401-09010",
    name: "オイルリザーバASSY & バルブSETG",
    nameRomaji: "Oil Reservoir ASSY & Valve SETG",
    category: "hydraulic",
    modelCompat: ["CCA101*-20(*)"],
    price: 78000,
    stock: "in_stock",
    leadTime: "即日",
    imageRef: "09-00",
    provisional: true,
    description: "作動油タンクとリリーフバルブ一式。",
    meshId: "oil-tank",
  },
  {
    id: "p02a",
    partNumber: "1F-3401-02011",
    name: "パイピング-1",
    nameRomaji: "Piping-1",
    category: "hydraulic",
    modelCompat: ["CCA101*-20(*)"],
    price: 36500,
    stock: "in_stock",
    leadTime: "即日",
    imageRef: "02-01",
    provisional: true,
    description: "ポンプ~バルブ間の油圧配管セット (1系統)。",
    meshId: "piping",
  },
  {
    id: "p02b",
    partNumber: "1F-3401-02012",
    name: "パイピング-2",
    nameRomaji: "Piping-2",
    category: "hydraulic",
    modelCompat: ["CCA101*-20(*)"],
    price: 38900,
    stock: "in_stock",
    leadTime: "即日",
    imageRef: "02-02",
    remark: "修理についてはサービスニュースNO.1338を準用の事。",
    provisional: true,
    description: "バルブ~各シリンダー間の油圧配管セット (2系統)。",
    meshId: "piping",
  },

  // ── ジャッキ ──
  {
    id: "p12",
    partNumber: "1F-3401-12010",
    name: "ジャッキSETG",
    nameRomaji: "Jack SETG",
    category: "jack",
    modelCompat: ["CCA101*-20(*)"],
    price: 124000,
    stock: "low_stock",
    leadTime: "1週間",
    imageRef: "12-00",
    provisional: true,
    description: "後端アウトリガーの脚・接地パッド一式。車体安定用。",
    meshId: "jack",
  },

  // ── フレーム (架装メーカー別) ──
  {
    id: "p13a",
    partNumber: "1F-3401-13011",
    name: "フレームSETG (いすゞ)",
    nameRomaji: "Frame SETG (ISUZU)",
    category: "frame",
    modelCompat: ["CCA101*-20(*)"],
    price: 524000,
    stock: "made_to_order",
    leadTime: "4~6週間",
    imageRef: "13-01",
    provisional: true,
    description: "いすゞシャシ向けサブフレーム一式。",
    meshId: "frame",
  },
  {
    id: "p13b",
    partNumber: "1F-3401-13021",
    name: "フレームSETG (日デ)",
    nameRomaji: "Frame SETG (UD)",
    category: "frame",
    modelCompat: ["CCA101*-20(*)"],
    price: 524000,
    stock: "made_to_order",
    leadTime: "4~6週間",
    imageRef: "13-02",
    provisional: true,
    description: "日デ(UD)シャシ向けサブフレーム一式。",
    meshId: "frame",
  },
  {
    id: "p13c",
    partNumber: "1F-3401-13031",
    name: "フレームSETG (日野)",
    nameRomaji: "Frame SETG (HINO)",
    category: "frame",
    modelCompat: ["CCA101*-20(*)"],
    price: 524000,
    stock: "made_to_order",
    leadTime: "4~6週間",
    imageRef: "13-03",
    provisional: true,
    description: "日野シャシ向けサブフレーム一式。",
    meshId: "frame",
  },
  {
    id: "p13d",
    partNumber: "1F-3401-13041",
    name: "フレームSETG (三菱)",
    nameRomaji: "Frame SETG (MITSUBISHI)",
    category: "frame",
    modelCompat: ["CCA101*-20(*)"],
    price: 524000,
    stock: "made_to_order",
    leadTime: "4~6週間",
    imageRef: "13-04",
    provisional: true,
    description: "三菱ふそうシャシ向けサブフレーム一式。",
    meshId: "frame",
  },

  // ── 電装 ──
  {
    id: "p14",
    partNumber: "1F-3401-14010",
    name: "エレクトリカルワイヤリング&ラベルSETG",
    nameRomaji: "Electrical Wiring & Label SETG",
    category: "electrical",
    modelCompat: ["CCA101*-20(*)"],
    price: 64000,
    stock: "in_stock",
    leadTime: "3営業日",
    imageRef: "14-00",
    provisional: true,
    description: "架装部の配線ハーネスと注意ラベル一式。",
    meshId: "wiring",
  },

  // ── アクセサリ ──
  {
    id: "p15",
    partNumber: "1F-3401-15010",
    name: "アクセサリ",
    nameRomaji: "Accessory",
    category: "accessory",
    modelCompat: ["CCA101*-20(*)"],
    price: 28000,
    stock: "in_stock",
    leadTime: "即日",
    imageRef: "15-00",
    provisional: true,
    description: "工具箱・付属金具などのアクセサリ類。",
    meshId: "accessory",
  },

  // ── シャシ側(架装メーカー扱い / 参考) ──
  {
    id: "c-cab",
    partNumber: "—",
    name: "キャブ (運転席)",
    nameRomaji: "Cab",
    category: "chassis",
    modelCompat: ["CCA101*-20(*)"],
    price: 0,
    stock: "made_to_order",
    leadTime: "シャシメーカー扱い",
    imageRef: "—",
    description: "ベースシャシの運転席。新明和の架装部品ではなくシャシメーカー扱い。",
    meshId: "cab",
  },
  {
    id: "c-wf",
    partNumber: "—",
    name: "前輪 (タイヤ・ホイール)",
    nameRomaji: "Front Wheel",
    category: "chassis",
    modelCompat: ["CCA101*-20(*)"],
    price: 0,
    stock: "in_stock",
    leadTime: "シャシメーカー扱い",
    imageRef: "—",
    description: "前軸タイヤ。シャシメーカー純正扱い。",
    meshId: "wheel-front",
  },
  {
    id: "c-wr",
    partNumber: "—",
    name: "後輪 (タンデム)",
    nameRomaji: "Rear Wheel",
    category: "chassis",
    modelCompat: ["CCA101*-20(*)"],
    price: 0,
    stock: "in_stock",
    leadTime: "シャシメーカー扱い",
    imageRef: "—",
    description: "後軸タンデムタイヤ。シャシメーカー純正扱い。",
    meshId: "wheel-rear",
  },
];

export const STOCK_LABEL: Record<StockStatus, { label: string; color: string }> = {
  in_stock: { label: "在庫あり", color: "text-emerald-400 border-emerald-400/30" },
  low_stock: { label: "在庫少", color: "text-amber-400 border-amber-400/30" },
  out_of_stock: { label: "在庫切れ", color: "text-red-400 border-red-400/30" },
  made_to_order: { label: "受注生産", color: "text-blue-400 border-blue-400/30" },
};
