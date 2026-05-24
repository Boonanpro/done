// 新Attackプロトタイプ用の架空データ
// 友人ヒアリング用のデモなので、新明和の実データは一切使わない
// 構造だけはATTACK実画面 (GTO*2-5433系) を踏襲

export type StockStatus = "in_stock" | "low_stock" | "out_of_stock" | "made_to_order";

export type Part = {
  id: string;
  partNumber: string;
  name: string;
  nameRomaji?: string;
  category: PartCategory;
  modelCompat: string[]; // 互換型式
  price: number;
  stock: StockStatus;
  leadTime: string; // "即日" "3営業日" "2週間" など
  imageRef?: string; // ATTACK上の参照番号 例: "18-1"
  description: string;
  // 3Dモデル上の部位ID (TruckModel 内のメッシュ名と対応)
  meshId: PartMeshId;
};

export type PartCategory =
  | "body" // ボデー (荷箱)
  | "hopper" // ホッパー (後部)
  | "hydraulic" // 油圧系
  | "chassis" // シャシ
  | "cab" // キャブ
  | "electrical" // 電装
  | "plate"; // プレート類

export type PartMeshId =
  | "cab"
  | "body"
  | "hopper"
  | "tailgate"
  | "rotating-plate"
  | "slide-plate"
  | "hydraulic-cylinder"
  | "hydraulic-pump"
  | "piping-body"
  | "piping-valve"
  | "pto"
  | "wheel-fl"
  | "wheel-fr"
  | "wheel-rl"
  | "wheel-rr"
  | "warning-light"
  | "mfg-plate";

export const CATEGORY_LABEL: Record<PartCategory, string> = {
  body: "ボデー",
  hopper: "ホッパー",
  hydraulic: "油圧系",
  chassis: "シャシ",
  cab: "キャブ",
  electrical: "電装",
  plate: "プレート類",
};

export const MESH_LABEL: Record<PartMeshId, string> = {
  cab: "キャブ",
  body: "ボデー本体",
  hopper: "ホッパー",
  tailgate: "リアゲート",
  "rotating-plate": "回転板",
  "slide-plate": "スライドプレート",
  "hydraulic-cylinder": "油圧シリンダー",
  "hydraulic-pump": "ピストンポンプ ASSY",
  "piping-body": "パイピング ボデー",
  "piping-valve": "パイピング バルブ",
  pto: "PTO (動力取出装置)",
  "wheel-fl": "前輪 左",
  "wheel-fr": "前輪 右",
  "wheel-rl": "後輪 左",
  "wheel-rr": "後輪 右",
  "warning-light": "警告灯",
  "mfg-plate": "製造Noプレート",
};

export type VehicleModel = {
  id: string;
  modelCode: string; // 例: GT042-5433/W/N
  catalogCode: string; // 例: H-3401-G0498A
  series: string; // 例: GTO*2-5433
  productionPeriod: string;
  description: string;
};

export const VEHICLE_MODELS: VehicleModel[] = [
  {
    id: "gt042-5433",
    modelCode: "GT042-5433/W/N",
    catalogCode: "H-3401-G0498A",
    series: "GTO*2-5433(*)",
    productionPeriod: "2012.12 (H24.12) ~ 2017.11 (H29.11)",
    description: "塵芥車 4.2t積 回転板式",
  },
  {
    id: "gt052-5433",
    modelCode: "GT052-5433/W/N",
    catalogCode: "H-3401-G0498A",
    series: "GTO*2-5433(*)",
    productionPeriod: "2012.12 (H24.12) ~ 2017.11 (H29.11)",
    description: "塵芥車 5.2t積 回転板式",
  },
  {
    id: "gt062-5444",
    modelCode: "GT062-5444/W/N",
    catalogCode: "H-3401-G0512B",
    series: "GTO*3-5444(*)",
    productionPeriod: "2018.01 (H30.01) ~ 現行",
    description: "塵芥車 6.2t積 プレス式",
  },
];

// 架空の部品データ (GT042-5433 をベースに30点ほど)
export const PARTS: Part[] = [
  {
    id: "p001",
    partNumber: "1H-3401-08210",
    name: "ピストンポンプ ASSY",
    nameRomaji: "Piston Pump ASSY",
    category: "hydraulic",
    modelCompat: ["GT042-5433/W/N", "GT052-5433/W/N"],
    price: 248000,
    stock: "in_stock",
    leadTime: "即日",
    imageRef: "01-02",
    description: "ホッパー油圧駆動の心臓部。回転板・押込板の動力源。",
    meshId: "hydraulic-pump",
  },
  {
    id: "p002",
    partNumber: "1H-3401-08315",
    name: "油圧シリンダー (押込)",
    category: "hydraulic",
    modelCompat: ["GT042-5433/W/N", "GT052-5433/W/N"],
    price: 89400,
    stock: "in_stock",
    leadTime: "即日",
    imageRef: "03-01",
    description: "押込板を上下させる油圧シリンダー。",
    meshId: "hydraulic-cylinder",
  },
  {
    id: "p003",
    partNumber: "1H-3401-04102",
    name: "回転板 ASSY",
    category: "hopper",
    modelCompat: ["GT042-5433/W/N", "GT052-5433/W/N"],
    price: 156000,
    stock: "low_stock",
    leadTime: "3営業日",
    imageRef: "04-01",
    description: "ゴミをボデー内部に送り込む回転板本体。摩耗消耗品。",
    meshId: "rotating-plate",
  },
  {
    id: "p004",
    partNumber: "1H-3401-04205",
    name: "スライドプレート",
    category: "hopper",
    modelCompat: ["GT042-5433/W/N", "GT052-5433/W/N", "GT062-5444/W/N"],
    price: 42800,
    stock: "in_stock",
    leadTime: "即日",
    imageRef: "04-02",
    description: "回転板下部の摺動板。約2年で要交換。",
    meshId: "slide-plate",
  },
  {
    id: "p005",
    partNumber: "1H-3401-12010",
    name: "リアゲート ASSY",
    category: "hopper",
    modelCompat: ["GT042-5433/W/N", "GT052-5433/W/N"],
    price: 412000,
    stock: "made_to_order",
    leadTime: "2~3週間",
    imageRef: "05-01",
    description: "テールゲート本体。事故等の交換時のみ。",
    meshId: "tailgate",
  },
  {
    id: "p006",
    partNumber: "1H-3401-07010",
    name: "パイピング ボデー",
    category: "hydraulic",
    modelCompat: ["GT042-5433/W/N"],
    price: 38500,
    stock: "in_stock",
    leadTime: "即日",
    imageRef: "02-01",
    description: "ボデー側の油圧配管セット。",
    meshId: "piping-body",
  },
  {
    id: "p007",
    partNumber: "1H-3401-07020",
    name: "パイピング バルブ",
    category: "hydraulic",
    modelCompat: ["GT042-5433/W/N", "GT052-5433/W/N"],
    price: 18900,
    stock: "in_stock",
    leadTime: "即日",
    imageRef: "03-02",
    description: "コントロールバルブ周りの配管セット。",
    meshId: "piping-valve",
  },
  {
    id: "p008",
    partNumber: "1H-3401-06010",
    name: "PTO ASSY (動力取出装置)",
    category: "chassis",
    modelCompat: ["GT042-5433/W/N", "GT052-5433/W/N"],
    price: 184000,
    stock: "low_stock",
    leadTime: "5営業日",
    imageRef: "06-01",
    description: "シャシ側からホッパー油圧へ動力を伝達。",
    meshId: "pto",
  },
  {
    id: "p009",
    partNumber: "1H-3401-21001",
    name: "警告灯 (黄色回転灯)",
    category: "electrical",
    modelCompat: ["GT042-5433/W/N", "GT052-5433/W/N", "GT062-5444/W/N"],
    price: 12800,
    stock: "in_stock",
    leadTime: "即日",
    imageRef: "21",
    description: "キャブルーフ警告灯。LED式。",
    meshId: "warning-light",
  },
  {
    id: "p010",
    partNumber: "1H-3401-99001",
    name: "MFG No. プレート",
    category: "plate",
    modelCompat: ["GT042-5433/W/N", "GT052-5433/W/N"],
    price: 3200,
    stock: "in_stock",
    leadTime: "即日",
    imageRef: "26-1",
    description: "車両識別プレート。再発行時のみ。",
    meshId: "mfg-plate",
  },
  {
    id: "p011",
    partNumber: "1H-3401-99002",
    name: "ボデー容積プレート",
    category: "plate",
    modelCompat: ["GT042-5433/W/N", "GT052-5433/W/N"],
    price: 2800,
    stock: "in_stock",
    leadTime: "即日",
    imageRef: "18-1",
    description: "ボデー容積を示すプレート。法定表示。",
    meshId: "mfg-plate",
  },
  {
    id: "p012",
    partNumber: "1H-3401-30101",
    name: "タイヤ 8.25R16 14PR",
    category: "chassis",
    modelCompat: ["GT042-5433/W/N", "GT052-5433/W/N"],
    price: 32400,
    stock: "in_stock",
    leadTime: "即日",
    imageRef: "30-1",
    description: "標準装着タイヤ。シャシ純正。",
    meshId: "wheel-rl",
  },
  {
    id: "p013",
    partNumber: "1H-3401-01001",
    name: "G.P ASSY",
    category: "hydraulic",
    modelCompat: ["GT042-5433/W/N", "GT052-5433/W/N"],
    price: 318000,
    stock: "made_to_order",
    leadTime: "2週間",
    imageRef: "01-01",
    description: "ギアポンプ アセンブリ。",
    meshId: "hydraulic-pump",
  },
  {
    id: "p014",
    partNumber: "1H-3401-08402",
    name: "油圧ホース (高圧)",
    category: "hydraulic",
    modelCompat: ["GT042-5433/W/N", "GT052-5433/W/N", "GT062-5444/W/N"],
    price: 8400,
    stock: "in_stock",
    leadTime: "即日",
    imageRef: "08-02",
    description: "ピストンポンプ→シリンダー間ホース。",
    meshId: "piping-body",
  },
  {
    id: "p015",
    partNumber: "1H-3401-04501",
    name: "回転板 ピン",
    category: "hopper",
    modelCompat: ["GT042-5433/W/N", "GT052-5433/W/N"],
    price: 4200,
    stock: "in_stock",
    leadTime: "即日",
    imageRef: "04-15",
    description: "回転板取付用ピン。摩耗時要交換。",
    meshId: "rotating-plate",
  },
];

export const STOCK_LABEL: Record<StockStatus, { label: string; color: string }> = {
  in_stock: { label: "在庫あり", color: "text-emerald-400 border-emerald-400/30" },
  low_stock: { label: "在庫少", color: "text-amber-400 border-amber-400/30" },
  out_of_stock: { label: "在庫切れ", color: "text-red-400 border-red-400/30" },
  made_to_order: { label: "受注生産", color: "text-blue-400 border-blue-400/30" },
};
