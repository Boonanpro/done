/**
 * AIX事業ダッシュボードの初期シードデータ。
 *
 * 将来はSupabaseなどの実DBに移行するが、現時点ではlocalStorageで永続化される
 * プロトタイプとして動作。`useAixStore` が読み書きを担当する。
 */

export type ClientStage =
  | "prospect" // 見込み（仮説だけ）
  | "proposed" // 提案送付済み
  | "meeting" // 商談中
  | "contracted" // 契約済み
  | "running" // 運用中
  | "paused"; // 一時停止

export type Priority = "high" | "mid" | "low";

export type Client = {
  id: string;
  name: string;
  industry: string;
  size: string;
  location: string;
  website?: string;
  contactName: string;
  contactRole: string;
  contactEmail?: string;
  contactPhone?: string;
  stage: ClientStage;
  priority: Priority;
  assignedAt: string; // ISO date
  summary: string;
  tags: string[];
  kpiNote?: string;
};

export type Hypothesis = {
  id: string;
  clientId: string;
  title: string;
  problem: string;
  solution: string;
  impact: "high" | "mid" | "low";
  confidence: "high" | "mid" | "low";
  status: "draft" | "validated" | "archived";
  createdAt: string;
};

export type Proposal = {
  id: string;
  clientId: string;
  hypothesisId: string;
  title: string;
  status: "drafting" | "ready" | "sent" | "responded" | "won" | "lost";
  videoUrl?: string;
  prototypeUrl?: string;
  sentAt?: string;
  summary: string;
};

export type Prototype = {
  id: string;
  clientId: string;
  proposalId?: string;
  name: string;
  description: string;
  url: string;
  status: "building" | "live" | "retired";
  coreFeatures: string[];
  lastUpdated: string;
};

export type Outreach = {
  id: string;
  clientId: string;
  kind: "email" | "phone" | "message";
  direction: "outbound" | "inbound";
  subject: string;
  body: string;
  occurredAt: string;
  outcome: "sent" | "opened" | "replied" | "no_response" | "scheduled";
};

export type Meeting = {
  id: string;
  clientId: string;
  title: string;
  mode: "online" | "onsite";
  scheduledAt: string;
  durationMinutes: number;
  status: "upcoming" | "done" | "canceled";
  summary?: string;
  nextActions?: string[];
};

export type Contract = {
  id: string;
  clientId: string;
  title: string;
  mrr: number; // 月額
  oneTime?: number; // 初期
  status: "negotiation" | "active" | "ended";
  startDate?: string;
  endDate?: string;
  scope: string[];
};

export type OpsTask = {
  id: string;
  clientId: string;
  title: string;
  detail: string;
  status: "todo" | "doing" | "review" | "done";
  priority: Priority;
  dueDate?: string;
  assignee: "dan" | "miki" | "both";
};

export type DanAction = {
  id: string;
  clientId?: string;
  kind:
    | "research"
    | "hypothesis"
    | "draft_proposal"
    | "build_prototype"
    | "draft_outreach"
    | "schedule_meeting"
    | "deploy_update"
    | "send_report";
  title: string;
  detail: string;
  status: "pending_review" | "approved" | "rejected" | "executed" | "rolled_back";
  proposedAt: string;
  executedAt?: string;
  artifactUrl?: string;
  riskLevel: "green" | "yellow" | "red";
};

/* ──────────────────────────────────────── */
/* SEED DATA                                */
/* ──────────────────────────────────────── */

export const SEED_CLIENTS: Client[] = [
  {
    id: "cli_yoshikawa",
    name: "有限会社 吉川特装自動車",
    industry: "自動車整備（特装車）",
    size: "小規模（10名前後想定）",
    location: "鳥取県米子市",
    contactName: "細田 かおり",
    contactRole: "代表取締役",
    contactPhone: "0859-27-4885",
    stage: "running",
    priority: "high",
    assignedAt: "2026-04-20",
    summary:
      "新明和工業の認定修理工場。特装車の修理・整備を中国地方で展開。電話問い合わせの負担軽減が初期課題。",
    tags: ["特装車", "新明和認定", "山陰", "DX初期"],
    kpiNote: "問い合わせの3割をWebフォームに置換を目標",
  },
  {
    id: "cli_sanin_logistics",
    name: "山陰物流 株式会社（仮名）",
    industry: "運送・物流",
    size: "中規模（50名）",
    location: "島根県松江市",
    contactName: "—",
    contactRole: "—",
    stage: "prospect",
    priority: "mid",
    assignedAt: "2026-04-23",
    summary:
      "配送ルート最適化とドライバー勤怠管理に課題。中国地方の物流デジタル化ポテンシャル大。",
    tags: ["物流", "勤怠DX", "ルート最適化"],
  },
  {
    id: "cli_tottori_kensetsu",
    name: "鳥取建設 株式会社（仮名）",
    industry: "建設業",
    size: "中規模（80名）",
    location: "鳥取県鳥取市",
    contactName: "—",
    contactRole: "—",
    stage: "proposed",
    priority: "mid",
    assignedAt: "2026-04-21",
    summary:
      "紙の工事日報をデジタル化したい。現場写真の共有とクラウド化が当面のニーズ。",
    tags: ["建設", "日報DX", "現場DX"],
  },
];

export const SEED_HYPOTHESES: Hypothesis[] = [
  {
    id: "hyp_yk_01",
    clientId: "cli_yoshikawa",
    title: "Web問い合わせフォームで電話対応を削減できる",
    problem:
      "問い合わせが毎回電話で入り、車台番号・型式の説明を毎度している。ベテランの時間を奪っている。",
    solution:
      "車台番号などを先に入力させるマルチステップフォーム。LINE画像送信フローをWebに統合。",
    impact: "high",
    confidence: "high",
    status: "validated",
    createdAt: "2026-04-20",
  },
  {
    id: "hyp_yk_02",
    clientId: "cli_yoshikawa",
    title: "修理進捗の顧客可視化で問い合わせ電話を減らせる",
    problem:
      "「うちの車、いつ直る？」の電話が毎日入る。進捗ステータスが社内でも把握しきれていない。",
    solution:
      "案件ごとの進捗ステータス（受付→部品手配→整備→完了）を顧客に共有できる簡易トラッキングページ。",
    impact: "high",
    confidence: "mid",
    status: "draft",
    createdAt: "2026-04-22",
  },
  {
    id: "hyp_yk_03",
    clientId: "cli_yoshikawa",
    title: "部品発注の車台番号照会を自動化できる",
    problem:
      "新明和の部品データベースに車台番号を手入力で照会している。時間と入力ミスが発生。",
    solution:
      "車検証OCR + 過去履歴DBで車両情報を自動補完。部品照会もワンクリックで新明和ポータルに転記。",
    impact: "mid",
    confidence: "mid",
    status: "draft",
    createdAt: "2026-04-23",
  },
  {
    id: "hyp_tt_01",
    clientId: "cli_tottori_kensetsu",
    title: "現場写真 + 位置情報で日報を3分で完成できる",
    problem:
      "手書き日報を事務所に戻って転記。現場終了後1時間の残業が常態化。",
    solution:
      "スマホアプリで写真と位置情報を自動で紐づけ。テンプレで事実ベースを埋めてAIがコメントを提案。",
    impact: "high",
    confidence: "mid",
    status: "validated",
    createdAt: "2026-04-21",
  },
  {
    id: "hyp_sn_01",
    clientId: "cli_sanin_logistics",
    title: "ルート最適化で1便あたり30分短縮できる",
    problem:
      "配送順の最適化がドライバーの経験頼り。新人は迷う時間が1時間/日発生。",
    solution:
      "配送先のリストからGoogle OR-Tools等で巡回セールスマン最適化、日次配送計画を自動生成。",
    impact: "high",
    confidence: "mid",
    status: "draft",
    createdAt: "2026-04-23",
  },
];

export const SEED_PROPOSALS: Proposal[] = [
  {
    id: "prop_yk_01",
    clientId: "cli_yoshikawa",
    hypothesisId: "hyp_yk_01",
    title: "吉川特装 HP + スマート問い合わせフォーム",
    status: "won",
    prototypeUrl: "/artifacts/kittoku",
    sentAt: "2026-04-22",
    summary:
      "認定修理工場としての信頼性訴求と、車両情報・画像をまとめて送信するマルチステップ問い合わせフォーム。",
  },
  {
    id: "prop_yk_02",
    clientId: "cli_yoshikawa",
    hypothesisId: "hyp_yk_02",
    title: "修理進捗トラッキング ページ",
    status: "drafting",
    summary:
      "受付番号で顧客が自車の修理進捗を確認できる。担当者が更新する裏側のSSボタンは一瞬で済む設計。",
  },
  {
    id: "prop_tt_01",
    clientId: "cli_tottori_kensetsu",
    hypothesisId: "hyp_tt_01",
    title: "建設現場 日報アプリ (MVP)",
    status: "sent",
    sentAt: "2026-04-22",
    summary:
      "スマホで現場写真と位置情報を記録するだけで日報が自動生成。PWA想定。",
  },
];

export const SEED_PROTOTYPES: Prototype[] = [
  {
    id: "proto_yk_01",
    clientId: "cli_yoshikawa",
    proposalId: "prop_yk_01",
    name: "吉川特装 公式HP",
    description: "認定修理工場としてのブランディング + 問い合わせフォーム。",
    url: "/artifacts/kittoku",
    status: "live",
    coreFeatures: [
      "新明和認定バッジ",
      "対応車種9機種",
      "問い合わせ3ステップ解説",
      "マルチステップフォーム",
      "会社情報・アクセス",
      "採用情報・応募",
    ],
    lastUpdated: "2026-04-24",
  },
  {
    id: "proto_tt_01",
    clientId: "cli_tottori_kensetsu",
    proposalId: "prop_tt_01",
    name: "建設日報アプリ MVP",
    description:
      "PWAで現場写真 + 位置情報 + 音声メモから日報を自動生成するMVP。",
    url: "#prototype-kensetsu",
    status: "building",
    coreFeatures: [
      "現場写真アップロード",
      "位置情報自動付加",
      "テンプレ日報生成",
      "AI コメント提案",
    ],
    lastUpdated: "2026-04-23",
  },
];

export const SEED_OUTREACH: Outreach[] = [
  {
    id: "out_yk_01",
    clientId: "cli_yoshikawa",
    kind: "phone",
    direction: "inbound",
    subject: "HP制作の相談",
    body: "ユーザー（みきさん）経由で、電話問い合わせの負担軽減を相談。LINE問い合わせフローの課題を共有。",
    occurredAt: "2026-04-20",
    outcome: "scheduled",
  },
  {
    id: "out_yk_02",
    clientId: "cli_yoshikawa",
    kind: "email",
    direction: "outbound",
    subject: "HPプロトタイプ完成のご報告",
    body: "デモ版HPをお送りします。ご希望の内容修正があればご連絡ください。",
    occurredAt: "2026-04-24",
    outcome: "sent",
  },
  {
    id: "out_tt_01",
    clientId: "cli_tottori_kensetsu",
    kind: "email",
    direction: "outbound",
    subject: "建設日報アプリ MVPご提案",
    body: "3分で日報が完成するMVPのデモ動画を添付しました。ご確認ください。",
    occurredAt: "2026-04-22",
    outcome: "opened",
  },
];

export const SEED_MEETINGS: Meeting[] = [
  {
    id: "mtg_yk_01",
    clientId: "cli_yoshikawa",
    title: "HPフィードバック MTG",
    mode: "online",
    scheduledAt: "2026-04-26T10:00:00+09:00",
    durationMinutes: 45,
    status: "upcoming",
    summary: "HPプロトタイプへのフィードバックと、次の進捗トラッキングの優先順位確認。",
  },
  {
    id: "mtg_tt_01",
    clientId: "cli_tottori_kensetsu",
    title: "MVP動画レビュー",
    mode: "online",
    scheduledAt: "2026-04-28T14:00:00+09:00",
    durationMinutes: 60,
    status: "upcoming",
  },
];

export const SEED_CONTRACTS: Contract[] = [
  {
    id: "con_yk_01",
    clientId: "cli_yoshikawa",
    title: "HP制作 + 運用サポート",
    mrr: 30000,
    oneTime: 200000,
    status: "active",
    startDate: "2026-04-24",
    scope: [
      "HP制作 + ドメイン・ホスティング",
      "月次の微修正・コンテンツ更新",
      "問い合わせフォーム改善運用",
    ],
  },
];

export const SEED_OPS_TASKS: OpsTask[] = [
  {
    id: "op_yk_01",
    clientId: "cli_yoshikawa",
    title: "実会社情報をHPに反映",
    detail:
      "代表挨拶・スタッフ写真・実績事例を吉川さんから取得してプレースホルダを差し替え。",
    status: "todo",
    priority: "high",
    dueDate: "2026-05-01",
    assignee: "both",
  },
  {
    id: "op_yk_02",
    clientId: "cli_yoshikawa",
    title: "Web問い合わせ運用テスト",
    detail: "1週間分の問い合わせが電話/Webのどちらで入ったかを計測。",
    status: "doing",
    priority: "high",
    dueDate: "2026-05-05",
    assignee: "dan",
  },
  {
    id: "op_yk_03",
    clientId: "cli_yoshikawa",
    title: "問い合わせ→LINE画像送付フローのQR案内",
    detail: "フォーム送信完了画面にLINE QRコードを追加（画像送付の補完導線）。",
    status: "review",
    priority: "mid",
    assignee: "dan",
  },
  {
    id: "op_tt_01",
    clientId: "cli_tottori_kensetsu",
    title: "MVPデモ動画の再生数確認",
    detail: "提案動画が開封されたかを確認、次アクションを検討。",
    status: "todo",
    priority: "mid",
    assignee: "dan",
  },
];

export const SEED_DAN_ACTIONS: DanAction[] = [
  {
    id: "act_01",
    clientId: "cli_yoshikawa",
    kind: "build_prototype",
    title: "吉川特装HPのプロトタイプを完成",
    detail:
      "新明和風ネイビー + 黄色アクセントでLPとマルチステップ問い合わせフォームを実装。",
    status: "executed",
    proposedAt: "2026-04-24T10:00:00+09:00",
    executedAt: "2026-04-24T12:30:00+09:00",
    artifactUrl: "/artifacts/kittoku",
    riskLevel: "green",
  },
  {
    id: "act_02",
    clientId: "cli_yoshikawa",
    kind: "draft_outreach",
    title: "HP完成のご報告メール ドラフト",
    detail: "吉川さん向けに、HPデモURLを含む完成報告メールの文面を生成。",
    status: "pending_review",
    proposedAt: "2026-04-24T13:00:00+09:00",
    riskLevel: "yellow",
  },
  {
    id: "act_03",
    clientId: "cli_yoshikawa",
    kind: "hypothesis",
    title: "追加仮説: 部品OCR自動化で発注ミス削減",
    detail:
      "車検証のOCRで車台番号を自動抽出し、発注ミスと手入力時間を削減する新仮説。",
    status: "pending_review",
    proposedAt: "2026-04-24T13:30:00+09:00",
    riskLevel: "green",
  },
  {
    id: "act_04",
    clientId: "cli_tottori_kensetsu",
    kind: "draft_outreach",
    title: "リマインド営業メール ドラフト",
    detail:
      "開封済みだが返信なし。3日後に軽いリマインドを送るドラフトを用意。",
    status: "pending_review",
    proposedAt: "2026-04-24T14:00:00+09:00",
    riskLevel: "yellow",
  },
  {
    id: "act_05",
    clientId: "cli_sanin_logistics",
    kind: "research",
    title: "山陰物流の課題分析レポート",
    detail:
      "公開情報から仮説候補3件を抽出。コールドメール送付前の前提情報として整理。",
    status: "executed",
    proposedAt: "2026-04-23T18:00:00+09:00",
    executedAt: "2026-04-23T19:00:00+09:00",
    riskLevel: "green",
  },
];

/* ──────────────────────────────────────── */
/* Aggregation helpers                      */
/* ──────────────────────────────────────── */

export function pipelineKpi(clients: Client[]) {
  const by = (stage: ClientStage) => clients.filter((c) => c.stage === stage).length;
  return {
    prospect: by("prospect"),
    proposed: by("proposed"),
    meeting: by("meeting"),
    contracted: by("contracted"),
    running: by("running"),
    total: clients.length,
  };
}

export function actionKpi(actions: DanAction[]) {
  return {
    pending: actions.filter((a) => a.status === "pending_review").length,
    executed: actions.filter((a) => a.status === "executed").length,
    rejected: actions.filter((a) => a.status === "rejected").length,
    total: actions.length,
  };
}
