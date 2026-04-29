"use client";

import { ExternalLink, Send, Calendar, Briefcase, Lightbulb, Film, Rocket, Building2, CheckCircle2, Sparkles, XCircle } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAix } from "../../data/store";
import { StageBadge, ProposalStatusBadge, OpsStatusChip, ActionStatusBadge, PriorityBadge } from "../ui-bits";
import type { OpsTask } from "../../data/mock";
import { AddHypothesisDialog } from "../add-hypothesis-dialog";
import { AddTaskDialog } from "../add-task-dialog";

/* ==================== Hypotheses View ==================== */
export function HypothesesView() {
  const { hypotheses, clients } = useAix();
  const byClient = (id: string) => clients.find((c) => c.id === id);

  const validated = hypotheses.filter((h) => h.status === "validated");
  const draft = hypotheses.filter((h) => h.status === "draft");
  const archived = hypotheses.filter((h) => h.status === "archived");

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
            <Lightbulb className="h-5 w-5 text-amber-400" />
            課題分析ボード
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            クライアントの課題に対するダンの仮説と解決アイデア。影響度×確度で優先順位を決めます。
          </p>
        </div>
        <AddHypothesisDialog />
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <HypothesisColumn title="検証済" items={validated} getClient={byClient} accent="emerald" />
        <HypothesisColumn title="ドラフト" items={draft} getClient={byClient} accent="blue" />
        <HypothesisColumn title="アーカイブ" items={archived} getClient={byClient} accent="slate" />
      </div>
    </div>
  );
}

function HypothesisColumn({
  title,
  items,
  getClient,
  accent,
}: {
  title: string;
  items: ReturnType<typeof useAix>["hypotheses"];
  getClient: (id: string) => ReturnType<typeof useAix>["clients"][number] | undefined;
  accent: "emerald" | "blue" | "slate";
}) {
  const dot = {
    emerald: "bg-emerald-500",
    blue: "bg-blue-500",
    slate: "bg-slate-500",
  }[accent];
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-medium flex items-center gap-2">
          <span className={`h-2 w-2 rounded-full ${dot}`} />
          {title}
          <span className="text-muted-foreground text-xs font-normal">({items.length})</span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {items.length === 0 && (
          <div className="text-xs text-muted-foreground py-8 text-center">—</div>
        )}
        {items.map((h) => {
          const c = getClient(h.clientId);
          return (
            <div
              key={h.id}
              className="rounded-md border border-border bg-card p-3 space-y-2"
            >
              <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
                <Building2 className="h-3 w-3" />
                <span className="truncate">{c?.name}</span>
              </div>
              <div className="text-sm font-medium leading-snug">{h.title}</div>
              <p className="text-[11px] text-muted-foreground leading-relaxed line-clamp-2">
                {h.problem}
              </p>
              <div className="flex gap-1.5 pt-1">
                <Badge variant="outline" className="rounded-sm text-[9px] font-mono">
                  影響 {h.impact}
                </Badge>
                <Badge variant="outline" className="rounded-sm text-[9px] font-mono">
                  確度 {h.confidence}
                </Badge>
              </div>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

/* ==================== Proposals View ==================== */
export function ProposalsView({ onOpenClient }: { onOpenClient: (id: string) => void }) {
  const { proposals, clients } = useAix();
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          <Film className="h-5 w-5 text-blue-400" />
          提案工房
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          課題から提案動画・プロトタイプへと橋渡しするパイプライン。
        </p>
      </div>
      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>提案タイトル</TableHead>
                <TableHead>クライアント</TableHead>
                <TableHead>ステータス</TableHead>
                <TableHead>送付日</TableHead>
                <TableHead className="text-right">アクション</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {proposals.map((p) => {
                const c = clients.find((x) => x.id === p.clientId);
                return (
                  <TableRow key={p.id}>
                    <TableCell>
                      <div className="text-sm font-medium">{p.title}</div>
                      <div className="text-xs text-muted-foreground mt-0.5 line-clamp-1">
                        {p.summary}
                      </div>
                    </TableCell>
                    <TableCell>
                      <button
                        type="button"
                        onClick={() => c && onOpenClient(c.id)}
                        className="text-sm hover:underline"
                      >
                        {c?.name ?? "—"}
                      </button>
                    </TableCell>
                    <TableCell>
                      <ProposalStatusBadge status={p.status} />
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground font-mono tabular-nums">
                      {p.sentAt ?? "—"}
                    </TableCell>
                    <TableCell className="text-right">
                      {p.prototypeUrl && (
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-7 text-xs rounded-sm"
                          asChild
                        >
                          <a href={p.prototypeUrl} target="_blank" rel="noreferrer">
                            <ExternalLink className="h-3 w-3 mr-1" />
                            プロト
                          </a>
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

/* ==================== Prototypes View ==================== */
export function PrototypesView({ onOpenClient }: { onOpenClient: (id: string) => void }) {
  const { prototypes, clients } = useAix();
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          <Rocket className="h-5 w-5 text-purple-400" />
          プロトタイプ管理
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          提案に紐づく実動プロトタイプの稼働状況と主要機能。
        </p>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {prototypes.map((p) => {
          const c = clients.find((x) => x.id === p.clientId);
          return (
            <Card key={p.id}>
              <CardContent className="p-5 space-y-3">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h3 className="font-semibold text-sm">{p.name}</h3>
                    <button
                      type="button"
                      onClick={() => c && onOpenClient(c.id)}
                      className="text-xs text-muted-foreground hover:underline mt-0.5"
                    >
                      {c?.name}
                    </button>
                  </div>
                  <Badge
                    variant="outline"
                    className={
                      p.status === "live"
                        ? "rounded-sm text-[10px] text-emerald-400 border-emerald-500/30 bg-emerald-500/10"
                        : p.status === "building"
                          ? "rounded-sm text-[10px] text-blue-400 border-blue-500/30 bg-blue-500/10"
                          : "rounded-sm text-[10px]"
                    }
                  >
                    {p.status === "live" ? "● 稼働中" : p.status === "building" ? "○ 開発中" : "停止"}
                  </Badge>
                </div>
                <p className="text-xs text-muted-foreground leading-relaxed">
                  {p.description}
                </p>
                <div className="flex gap-1 flex-wrap">
                  {p.coreFeatures.map((f) => (
                    <Badge
                      key={f}
                      variant="outline"
                      className="rounded-sm text-[10px] font-normal"
                    >
                      <CheckCircle2 className="h-2.5 w-2.5 mr-1 text-emerald-500" />
                      {f}
                    </Badge>
                  ))}
                </div>
                <div className="flex items-center justify-between pt-2 border-t border-border text-xs">
                  <span className="text-muted-foreground">
                    最終更新 {p.lastUpdated}
                  </span>
                  {(p.url.startsWith("/") || p.url.startsWith("http")) && (
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-7 text-xs rounded-sm"
                      asChild
                    >
                      <a href={p.url} target="_blank" rel="noreferrer">
                        <ExternalLink className="h-3 w-3 mr-1" />
                        開く
                      </a>
                    </Button>
                  )}
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}

/* ==================== Outreach View ==================== */
export function OutreachView({ onOpenClient }: { onOpenClient: (id: string) => void }) {
  const { outreach, clients } = useAix();
  const sorted = [...outreach].sort((a, b) => b.occurredAt.localeCompare(a.occurredAt));
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          <Send className="h-5 w-5 text-blue-400" />
          営業活動
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          送信・受信の履歴を時系列で。ダンが下書きした文面はここから確認できます。
        </p>
      </div>
      <Card>
        <CardContent className="p-0">
          <div className="divide-y divide-border">
            {sorted.map((o) => {
              const c = clients.find((x) => x.id === o.clientId);
              return (
                <div key={o.id} className="p-4 space-y-2">
                  <div className="flex items-center justify-between text-xs">
                    <div className="flex items-center gap-2">
                      <Badge
                        variant="outline"
                        className={
                          o.direction === "outbound"
                            ? "rounded-sm text-[10px] text-blue-400 border-blue-500/30"
                            : "rounded-sm text-[10px] text-emerald-400 border-emerald-500/30"
                        }
                      >
                        {o.direction === "outbound" ? "↗ 送信" : "↙ 受信"}
                      </Badge>
                      <Badge variant="outline" className="rounded-sm text-[10px]">
                        {o.kind}
                      </Badge>
                      <span className="text-muted-foreground">{o.occurredAt}</span>
                    </div>
                    <Badge variant="outline" className="rounded-sm text-[10px]">
                      {o.outcome}
                    </Badge>
                  </div>
                  <div className="text-sm font-medium">{o.subject}</div>
                  <p className="text-xs text-muted-foreground leading-relaxed">
                    {o.body}
                  </p>
                  <button
                    type="button"
                    onClick={() => c && onOpenClient(c.id)}
                    className="text-xs text-muted-foreground hover:underline"
                  >
                    {c?.name}
                  </button>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

/* ==================== Meetings View ==================== */
export function MeetingsView({ onOpenClient }: { onOpenClient: (id: string) => void }) {
  const { meetings, clients } = useAix();
  const sorted = [...meetings].sort((a, b) => a.scheduledAt.localeCompare(b.scheduledAt));
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          <Calendar className="h-5 w-5 text-purple-400" />
          商談カレンダー
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          予定されている商談と、過去の議事録。
        </p>
      </div>
      <Card>
        <CardContent className="p-0">
          <div className="divide-y divide-border">
            {sorted.map((m) => {
              const c = clients.find((x) => x.id === m.clientId);
              const d = new Date(m.scheduledAt);
              return (
                <div
                  key={m.id}
                  className="p-4 flex items-center gap-4"
                >
                  <div className="shrink-0 text-center w-20">
                    <div className="text-xs text-muted-foreground tabular-nums">
                      {d.getFullYear()}/{d.getMonth() + 1}/{d.getDate()}
                    </div>
                    <div className="font-mono text-lg font-bold tabular-nums">
                      {String(d.getHours()).padStart(2, "0")}:
                      {String(d.getMinutes()).padStart(2, "0")}
                    </div>
                    <div className="text-[10px] text-muted-foreground">
                      {m.durationMinutes}分
                    </div>
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium">{m.title}</div>
                    <div className="text-xs text-muted-foreground">
                      <button
                        type="button"
                        onClick={() => c && onOpenClient(c.id)}
                        className="hover:underline"
                      >
                        {c?.name}
                      </button>
                      {" · "}
                      {m.mode === "online" ? "オンライン" : "対面"}
                    </div>
                    {m.summary && (
                      <p className="text-xs text-muted-foreground mt-1.5 leading-relaxed">
                        {m.summary}
                      </p>
                    )}
                  </div>
                  <Badge
                    variant="outline"
                    className={
                      m.status === "upcoming"
                        ? "rounded-sm text-[10px] text-blue-400 border-blue-500/30 bg-blue-500/10"
                        : m.status === "done"
                          ? "rounded-sm text-[10px] text-emerald-400 border-emerald-500/30 bg-emerald-500/10"
                          : "rounded-sm text-[10px]"
                    }
                  >
                    {m.status === "upcoming" ? "予定" : m.status === "done" ? "完了" : "中止"}
                  </Badge>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

/* ==================== Ops View ==================== */
const OPS_COLUMNS: { key: OpsTask["status"]; label: string; dot: string }[] = [
  { key: "todo", label: "未着手", dot: "bg-slate-500" },
  { key: "doing", label: "進行中", dot: "bg-blue-500" },
  { key: "review", label: "レビュー", dot: "bg-amber-500" },
  { key: "done", label: "完了", dot: "bg-emerald-500" },
];

export function OpsView({ onOpenClient }: { onOpenClient: (id: string) => void }) {
  const { opsTasks, contracts, clients, moveOpsTask } = useAix();
  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
            <Briefcase className="h-5 w-5 text-amber-400" />
            契約・運用
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            契約済みクライアントへの運用タスクをかんばん形式で。
          </p>
        </div>
        <AddTaskDialog />
      </div>

      {/* 契約一覧 */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium">契約中</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {contracts.length === 0 && (
            <div className="text-xs text-muted-foreground py-4 text-center">
              契約なし
            </div>
          )}
          {contracts.map((c) => {
            const client = clients.find((x) => x.id === c.clientId);
            return (
              <div
                key={c.id}
                className="flex items-center gap-4 rounded-md border border-border p-3"
              >
                <Briefcase className="h-4 w-4 text-muted-foreground shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium">{c.title}</div>
                  <button
                    type="button"
                    onClick={() => client && onOpenClient(client.id)}
                    className="text-xs text-muted-foreground hover:underline"
                  >
                    {client?.name}
                  </button>
                </div>
                <div className="text-right">
                  <div className="font-mono text-sm tabular-nums">
                    ¥{c.mrr.toLocaleString()}/月
                  </div>
                  {c.oneTime && (
                    <div className="text-xs text-muted-foreground font-mono tabular-nums">
                      初期 ¥{c.oneTime.toLocaleString()}
                    </div>
                  )}
                </div>
                <Badge variant="outline" className="rounded-sm text-[10px]">
                  {c.status === "active" ? "契約中" : c.status}
                </Badge>
              </div>
            );
          })}
        </CardContent>
      </Card>

      {/* カンバン */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
        {OPS_COLUMNS.map((col) => {
          const tasks = opsTasks.filter((t) => t.status === col.key);
          return (
            <Card key={col.key}>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-medium flex items-center gap-2">
                  <span className={`h-2 w-2 rounded-full ${col.dot}`} />
                  {col.label}
                  <span className="text-muted-foreground text-xs font-normal ml-auto">
                    {tasks.length}
                  </span>
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {tasks.map((t) => {
                  const client = clients.find((x) => x.id === t.clientId);
                  return (
                    <div
                      key={t.id}
                      className="rounded-md border border-border bg-card p-3 space-y-2"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="text-sm font-medium leading-snug">
                          {t.title}
                        </div>
                        <PriorityBadge priority={t.priority} />
                      </div>
                      <p className="text-[11px] text-muted-foreground leading-relaxed line-clamp-2">
                        {t.detail}
                      </p>
                      <div className="flex items-center justify-between text-[10px]">
                        <button
                          type="button"
                          onClick={() => client && onOpenClient(client.id)}
                          className="text-muted-foreground hover:underline truncate"
                        >
                          {client?.name}
                        </button>
                        {t.dueDate && (
                          <span className="text-muted-foreground font-mono">
                            期限 {t.dueDate}
                          </span>
                        )}
                      </div>
                      <div className="flex gap-1 pt-1">
                        {OPS_COLUMNS.filter((c) => c.key !== t.status).map((c) => (
                          <button
                            key={c.key}
                            type="button"
                            onClick={() => moveOpsTask(t.id, c.key)}
                            className="text-[9px] text-muted-foreground hover:text-foreground border border-border rounded-sm px-1.5 py-0.5"
                          >
                            → {c.label}
                          </button>
                        ))}
                      </div>
                    </div>
                  );
                })}
                {tasks.length === 0 && (
                  <div className="text-[11px] text-muted-foreground py-4 text-center">
                    —
                  </div>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}

/* ==================== Actions View ==================== */
export function ActionsView({ onOpenClient }: { onOpenClient: (id: string) => void }) {
  const { danActions, clients, approveDanAction, rejectDanAction } = useAix();
  const sorted = [...danActions].sort((a, b) =>
    b.proposedAt.localeCompare(a.proposedAt),
  );
  const pending = sorted.filter((a) => a.status === "pending_review");
  const history = sorted.filter((a) => a.status !== "pending_review");

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          <Sparkles className="h-5 w-5 text-amber-400" />
          ダンのアクション
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          ダンが提案・実行したアクション。承認・却下の判断を。
        </p>
      </div>

      <Card className="border-amber-500/20 bg-amber-500/[0.02]">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-amber-400" />
            承認待ち ({pending.length})
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {pending.length === 0 && (
            <div className="text-xs text-muted-foreground py-6 text-center">
              承認待ちはありません
            </div>
          )}
          {pending.map((a) => {
            const c = clients.find((x) => x.id === a.clientId);
            const riskColor = {
              green: "text-emerald-400 border-emerald-500/30 bg-emerald-500/10",
              yellow: "text-amber-400 border-amber-500/30 bg-amber-500/10",
              red: "text-rose-400 border-rose-500/30 bg-rose-500/10",
            }[a.riskLevel];
            return (
              <div
                key={a.id}
                className="rounded-md border border-border bg-card p-4 space-y-3"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <Badge
                      variant="outline"
                      className={`rounded-sm text-[9px] font-mono ${riskColor}`}
                    >
                      {a.riskLevel.toUpperCase()}
                    </Badge>
                    <Badge variant="outline" className="rounded-sm text-[10px]">
                      {a.kind}
                    </Badge>
                  </div>
                  {c && (
                    <button
                      type="button"
                      onClick={() => onOpenClient(c.id)}
                      className="text-xs text-muted-foreground hover:underline"
                    >
                      {c.name}
                    </button>
                  )}
                </div>
                <div className="text-sm font-medium">{a.title}</div>
                <p className="text-xs text-muted-foreground leading-relaxed">
                  {a.detail}
                </p>
                <div className="flex items-center gap-2 pt-1">
                  <Button
                    size="sm"
                    className="h-8 text-xs rounded-sm"
                    onClick={() => approveDanAction(a.id)}
                  >
                    <CheckCircle2 className="h-3.5 w-3.5 mr-1" />
                    承認・実行
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-8 text-xs rounded-sm"
                    onClick={() => rejectDanAction(a.id)}
                  >
                    <XCircle className="h-3.5 w-3.5 mr-1" />
                    却下
                  </Button>
                </div>
              </div>
            );
          })}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium">履歴 ({history.length})</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <div className="divide-y divide-border">
            {history.map((a) => {
              const c = clients.find((x) => x.id === a.clientId);
              return (
                <div key={a.id} className="p-4 space-y-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 text-xs">
                      <Badge variant="outline" className="rounded-sm text-[10px]">
                        {a.kind}
                      </Badge>
                      <span className="text-muted-foreground">
                        {new Date(a.proposedAt).toLocaleString("ja")}
                      </span>
                    </div>
                    <ActionStatusBadge status={a.status} />
                  </div>
                  <div className="text-sm font-medium">{a.title}</div>
                  <p className="text-xs text-muted-foreground leading-relaxed">
                    {a.detail}
                  </p>
                  <div className="flex items-center justify-between text-xs pt-1">
                    {c && (
                      <button
                        type="button"
                        onClick={() => onOpenClient(c.id)}
                        className="text-muted-foreground hover:underline"
                      >
                        {c.name}
                      </button>
                    )}
                    {a.artifactUrl && (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-6 text-xs"
                        asChild
                      >
                        <a href={a.artifactUrl} target="_blank" rel="noreferrer">
                          <ExternalLink className="h-3 w-3 mr-1" />
                          成果物
                        </a>
                      </Button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
