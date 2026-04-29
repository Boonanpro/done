export type Company = {
  id: string;
  name: string;
  industry: string;
  address: string;
  employees: number;
  founded: string;
  phone: string;
  score: number;
  hpStatus: "none" | "outdated" | "ok";
  mobileOk: boolean;
  inquiryForm: boolean;
  issues: { title: string; detail: string; confidence: number }[];
  status: "診断済み" | "プロト生成済" | "送信済" | "商談中" | "受注";
  lastContact?: string;
};

export const companies: Company[] = [
  {
    id: "tanaka-seimitsu",
    name: "田中精密工業株式会社",
    industry: "製造業",
    address: "尼崎市潮江2-5-3",
    employees: 28,
    founded: "昭和47年",
    phone: "06-6419-XXXX",
    score: 92,
    hpStatus: "none",
    mobileOk: false,
    inquiryForm: false,
    issues: [
      {
        title: "Googleにビジネスプロフィールのみで公式サイトなし",
        detail:
          "検索結果にはGBPが表示されるが、実績を伝えるチャネルが存在しない。新規取引の入り口がゼロ。",
        confidence: 99,
      },
      {
        title: "業界内での技術力訴求の場がない",
        detail:
          "公差±0.005mmの加工は武器だがHPがないので顧客（医療機器メーカー等）が技術を知る機会がない。",
        confidence: 94,
      },
    ],
    status: "診断済み",
  },
  {
    id: "sakimoto-koumuten",
    name: "崎本工務店",
    industry: "建設業",
    address: "尼崎市塚口本町",
    employees: 12,
    founded: "昭和58年",
    phone: "06-6426-XXXX",
    score: 88,
    hpStatus: "outdated",
    mobileOk: false,
    inquiryForm: true,
    issues: [
      {
        title: "HPが2015年から更新停止・スマホ非対応",
        detail:
          "施工事例が10年前のまま。問い合わせフォームも機能していない。",
        confidence: 97,
      },
    ],
    status: "プロト生成済",
  },
  {
    id: "sei-gakuin",
    name: "聖学院ピアノ教室",
    industry: "教育",
    address: "尼崎市南塚口町",
    employees: 3,
    founded: "平成14年",
    phone: "06-6422-XXXX",
    score: 81,
    hpStatus: "outdated",
    mobileOk: false,
    inquiryForm: false,
    issues: [
      {
        title: "体験レッスン予約導線がない",
        detail:
          "HPはあるが電話番号だけで、Webから体験レッスンを予約できない。",
        confidence: 92,
      },
    ],
    status: "送信済",
  },
  {
    id: "hair-salon-lumiere",
    name: "hair salon LUMIÈRE",
    industry: "美容",
    address: "尼崎市立花町",
    employees: 5,
    founded: "平成28年",
    phone: "06-6438-XXXX",
    score: 79,
    hpStatus: "none",
    mobileOk: false,
    inquiryForm: false,
    issues: [
      {
        title: "Instagram頼りで予約流出",
        detail:
          "検索からの新規客獲得動線が無く、紹介に依存している。",
        confidence: 88,
      },
    ],
    status: "診断済み",
  },
  {
    id: "kosuji-ent",
    name: "越路ENT医院",
    industry: "医療",
    address: "尼崎市大物町",
    employees: 8,
    founded: "平成10年",
    phone: "06-6481-XXXX",
    score: 76,
    hpStatus: "outdated",
    mobileOk: true,
    inquiryForm: false,
    issues: [
      {
        title: "Web予約未対応",
        detail:
          "診療時間・アクセスはHPに載っているが、Web予約・問診票が無く電話集中。",
        confidence: 90,
      },
    ],
    status: "商談中",
  },
  {
    id: "tatsuta-zairyo",
    name: "立田資材株式会社",
    industry: "卸売",
    address: "尼崎市大庄北",
    employees: 22,
    founded: "昭和42年",
    phone: "06-6416-XXXX",
    score: 74,
    hpStatus: "outdated",
    mobileOk: false,
    inquiryForm: true,
    issues: [
      {
        title: "取扱品目のカタログが紙のみ",
        detail:
          "Web上で在庫・型番検索ができないため、注文の度に電話・FAXが発生。",
        confidence: 93,
      },
    ],
    status: "診断済み",
  },
  {
    id: "ayumi-kaigo",
    name: "あゆみ介護サービス",
    industry: "介護",
    address: "尼崎市武庫之荘",
    employees: 18,
    founded: "平成19年",
    phone: "06-6431-XXXX",
    score: 71,
    hpStatus: "outdated",
    mobileOk: true,
    inquiryForm: true,
    issues: [
      {
        title: "採用情報がHPに無い",
        detail:
          "求人媒体頼みで採用コストが年200万円超。自社HPでの求人動線が無い。",
        confidence: 91,
      },
    ],
    status: "送信済",
  },
  {
    id: "tachibana-senbei",
    name: "立花せんべい本舗",
    industry: "食品",
    address: "尼崎市西立花町",
    employees: 7,
    founded: "大正13年",
    phone: "06-6417-XXXX",
    score: 69,
    hpStatus: "none",
    mobileOk: false,
    inquiryForm: false,
    issues: [
      {
        title: "ECチャネル無し",
        detail:
          "店頭販売のみ。贈答需要があるのにオンライン購入ができない。",
        confidence: 87,
      },
    ],
    status: "診断済み",
  },
  {
    id: "amagasaki-auto",
    name: "アマガサキオートサービス",
    industry: "整備",
    address: "尼崎市扇町",
    employees: 6,
    founded: "平成6年",
    phone: "06-6488-XXXX",
    score: 66,
    hpStatus: "outdated",
    mobileOk: false,
    inquiryForm: false,
    issues: [
      {
        title: "見積り依頼フォームが無い",
        detail:
          "電話受付のみで夜間・休日の問い合わせ取りこぼしが発生。",
        confidence: 85,
      },
    ],
    status: "診断済み",
  },
  {
    id: "mikuni-printing",
    name: "三国印刷株式会社",
    industry: "印刷",
    address: "尼崎市杭瀬本町",
    employees: 14,
    founded: "昭和52年",
    phone: "06-6481-XXXX",
    score: 64,
    hpStatus: "outdated",
    mobileOk: true,
    inquiryForm: true,
    issues: [
      {
        title: "オンライン見積もり未対応",
        detail:
          "Web問い合わせはあるがPDF入稿から先の自動化が未整備。",
        confidence: 80,
      },
    ],
    status: "診断済み",
  },
];

export const todayActions = [
  {
    id: "a1",
    companyId: "tanaka-seimitsu",
    action: "プロトタイプ承認待ち",
    urgent: true,
  },
  {
    id: "a2",
    companyId: "hair-salon-lumiere",
    companyName: "hair salon LUMIÈRE",
    action: "診断レポート確認",
    urgent: false,
  },
  {
    id: "a3",
    companyId: "kosuji-ent",
    companyName: "越路ENT医院",
    action: "商談アポ調整中",
    urgent: false,
  },
  {
    id: "a4",
    companyId: "sei-gakuin",
    companyName: "聖学院ピアノ教室",
    action: "返信あり・要確認",
    urgent: true,
  },
  {
    id: "a5",
    companyId: "amagasaki-auto",
    companyName: "アマガサキオートサービス",
    action: "アプローチ候補",
    urgent: false,
  },
];

export const notifications = [
  {
    id: "n1",
    time: "10:32",
    text: "田中精密工業からプロトタイプのフィードバック受信",
  },
  {
    id: "n2",
    time: "09:15",
    text: "聖学院ピアノ教室が送信メールを開封",
  },
  {
    id: "n3",
    time: "08:48",
    text: "診断バッチ完了（5,000社）",
  },
  {
    id: "n4",
    time: "08:40",
    text: "越路ENT医院からアポ日時の回答あり",
  },
];

export const kpi = {
  total: 5000,
  diagnosed: 5000,
  prototyped: 30,
  approached: 100,
  meetings: 5,
  deals: 2,
};

export const funnel = [
  { label: "尼崎市 全法人リスト", value: 5000, key: "LIST" },
  { label: "HP診断で重点抽出", value: 300, key: "QUALIFIED" },
  { label: "プロトタイプ生成", value: 30, key: "PROTOTYPED" },
  { label: "3チャネル アプローチ", value: 100, key: "CONTACTED" },
  { label: "商談アポ獲得", value: 5, key: "MEETINGS" },
  { label: "受注", value: 2, key: "DEALS" },
];

export const industryReplyRate = [
  { industry: "製造", rate: 22 },
  { industry: "飲食", rate: 18 },
  { industry: "医療", rate: 8 },
  { industry: "建設", rate: 16 },
  { industry: "運送", rate: 12 },
  { industry: "小売", rate: 19 },
  { industry: "教育", rate: 11 },
  { industry: "サービス", rate: 14 },
];

export const aiInsight =
  "製造業と飲食業の返信率が高い傾向。来月は製造業の重点アプローチを推奨。";

export const draftMessage = `件名: 田中精密工業のHPサンプルを作成しました（本田AI営業）

株式会社田中精密工業 田中様

突然のご連絡失礼いたします。尼崎市のAI活用DX支援を行っております本田と申します。

御社のGoogleビジネスプロフィールを拝見し、±0.005mmの精密加工技術に感銘を受け、
試しに公式サイトのサンプルを作成いたしました（完全無料・採用不要）。

▶ サンプル: https://tanaka-seisitsu.preview.miki-honda.jp

本サイトには以下の意図を込めています:
- 技術を伝える: 加工事例を写真+図面で掲載
- 採用を支援: 二代目候補を念頭に若手職人向けコピー
- 問い合わせ動線: フォーム+電話を全ページに常設

もしご興味ありましたら、30分ほどお電話でご説明できますと幸いです。
日程は本メールへの返信 or お電話（080-XXXX-XXXX）で承ります。

本田 樹 / 本田AI営業`;
