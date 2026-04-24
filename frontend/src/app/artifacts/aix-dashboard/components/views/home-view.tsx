"use client";

import {
  TrendingUp,
  Clock,
  CheckCircle2,
  AlertCircle,
  Sparkles,
  ArrowRight,
  Building2,
  Film,
  Rocket,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { useAix } from "../../data/store";
import { pipelineKpi, actionKpi, type DanAction, type Client } from "../../data/mock";
import { StageBadge } from "../ui-bits";
import type { AixView } from "../sidebar";

type HomeViewProps = {
  onNavigate: (v: AixView) => void;
  onOpenClient: (id: string) => void;
};

export function HomeView({ onNavigate, onOpenClient }: HomeViewProps) {
  const {
    clients,
    danActions,
    proposals,
    prototypes,
    meetings,
    approveDanAction,
    rejectDanAction,
  } = useAix();

  const pipe = pipelineKpi(clients);
  const acts = actionKpi(danActions);

  const pending = danActions.filter((a) => a.status === "pending_review");
  const upcomingMeetings = meetings
    .filter((m) => m.status === "upcoming")
    .sort((a, b) => a.scheduledAt.localeCompare(b.scheduledAt))
    .slice(0, 3);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">AIX Cockpit</h1>
          <p className="text-sm text-muted-foreground mt-1">
            ダンがクライアントのDXを前に進める。あなたは良し悪しを判断するだけ。
          </p>
        </div>
        <Badge className="bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/15 border-emerald-500/30 rounded-sm font-mono text-[10px]">
          ● LIVE
        </Badge>
      </div>

      {/* KPI 行 */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
        <KpiBox
          label="クライアント"
          value={pipe.total}
          hint={`${pipe.running}社が運用中`}
          icon={<Building2 className="h-3.5 w-3.5" />}
          onClick={() => onNavigate("clients")}
        />
        <KpiBox
          label="提案中"
          value={proposals.filter((p) => ["sent", "responded"].includes(p.status)).length}
          hint="反応待ち"
          icon={<Film className="h-3.5 w-3.5" />}
          onClick={() => onNavigate("proposals")}
        />
        <KpiBox
          label="プロトタイプ"
          value={prototypes.filter((p) => p.status !== "retired").length}
          hint={`${prototypes.filter((p) => p.status === "live").length}個が稼働中`}
          icon={<Rocket className="h-3.5 w-3.5" />}
          onClick={() => onNavigate("prototypes")}
        />
        <KpiBox
          label="ダン承認待ち"
          value={acts.pending}
          hint="あなたの判断待ち"
          icon={<Sparkles className="h-3.5 w-3.5" />}
          highlight
          onClick={() => onNavigate("actions")}
        />
        <KpiBox
          label="実行済みアクション"
          value={acts.executed}
          hint="直近のダンの動き"
          icon={<CheckCircle2 className="h-3.5 w-3.5" />}
        />
      </div>

      {/* パイプラインとダン承認待ち */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card className="lg:col-span-2">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium">
                案件パイプライン
              </CardTitle>
              <Button
                variant="ghost"
                size="sm"
                className="h-7 text-xs"
                onClick={() => onNavigate("clients")}
              >
                一覧を開く
                <ArrowRight className="h-3 w-3 ml-1" />
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <PipelineBar pipe={pipe} />
            <div className="space-y-2 pt-1">
              {clients.slice(0, 3).map((c) => (
                <ClientRow key={c.id} client={c} onOpen={() => onOpenClient(c.id)} />
              ))}
            </div>
          </CardContent>
        </Card>

        <Card className="border-amber-500/20 bg-amber-500/[0.02]">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-amber-400" />
                ダンの承認待ち
              </CardTitle>
              <Button
                variant="ghost"
                size="sm"
                className="h-7 text-xs"
                onClick={() => onNavigate("actions")}
              >
                すべて
                <ArrowRight className="h-3 w-3 ml-1" />
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-2">
            {pending.slice(0, 4).map((a) => (
              <PendingActionCard
                key={a.id}
                action={a}
                onApprove={() => approveDanAction(a.id)}
                onReject={() => rejectDanAction(a.id)}
              />
            ))}
            {pending.length === 0 && (
              <div className="text-xs text-muted-foreground text-center py-6">
                承認待ちはありません
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* 今日・明日の予定 */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm font-medium">
              直近の商談
            </CardTitle>
            <Button
              variant="ghost"
              size="sm"
              className="h-7 text-xs"
              onClick={() => onNavigate("meetings")}
            >
              商談一覧
              <ArrowRight className="h-3 w-3 ml-1" />
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {upcomingMeetings.length === 0 && (
            <div className="text-xs text-muted-foreground text-center py-6">
              予定されている商談はありません
            </div>
          )}
          <div className="divide-y divide-border">
            {upcomingMeetings.map((m) => {
              const client = clients.find((c) => c.id === m.clientId);
              const d = new Date(m.scheduledAt);
              return (
                <div
                  key={m.id}
                  className="flex items-center gap-4 py-3 first:pt-0 last:pb-0"
                >
                  <div className="shrink-0 text-center w-16">
                    <div className="text-xs text-muted-foreground tabular-nums">
                      {d.getMonth() + 1}/{d.getDate()}
                    </div>
                    <div className="font-mono text-sm font-bold tabular-nums">
                      {String(d.getHours()).padStart(2, "0")}:
                      {String(d.getMinutes()).padStart(2, "0")}
                    </div>
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium truncate">{m.title}</div>
                    <div className="text-xs text-muted-foreground truncate">
                      {client?.name} · {m.mode === "online" ? "オンライン" : "対面"} ·{" "}
                      {m.durationMinutes}分
                    </div>
                  </div>
                  <Badge variant="outline" className="rounded-sm text-[10px]">
                    {m.status === "upcoming" ? "予定" : m.status}
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

/* ---------- sub components ---------- */

function KpiBox({
  label,
  value,
  hint,
  icon,
  highlight,
  onClick,
}: {
  label: string;
  value: number;
  hint: string;
  icon?: React.ReactNode;
  highlight?: boolean;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!onClick}
      className={
        "text-left rounded-lg border bg-card p-4 transition-colors " +
        (highlight
          ? "border-amber-500/30 bg-amber-500/5"
          : "border-border hover:bg-accent/30") +
        (onClick ? " cursor-pointer" : " cursor-default")
      }
    >
      <div className="flex items-center justify-between text-xs text-muted-foreground mb-1.5">
        <span className="flex items-center gap-1.5">
          {icon}
          {label}
        </span>
      </div>
      <div className="text-2xl font-semibold tabular-nums">{value}</div>
      <div className="text-[11px] text-muted-foreground mt-0.5">{hint}</div>
    </button>
  );
}

function PipelineBar({
  pipe,
}: {
  pipe: ReturnType<typeof pipelineKpi>;
}) {
  const total = Math.max(1, pipe.total);
  const stages = [
    { key: "prospect", label: "見込", count: pipe.prospect, color: "bg-slate-500" },
    { key: "proposed", label: "提案中", count: pipe.proposed, color: "bg-blue-500" },
    { key: "meeting", label: "商談中", count: pipe.meeting, color: "bg-purple-500" },
    {
      key: "contracted",
      label: "契約済",
      count: pipe.contracted,
      color: "bg-amber-500",
    },
    {
      key: "running",
      label: "運用中",
      count: pipe.running,
      color: "bg-emerald-500",
    },
  ];
  return (
    <div className="space-y-2">
      <div className="flex h-2 rounded-full overflow-hidden bg-muted">
        {stages.map((s) => (
          <div
            key={s.key}
            className={s.color}
            style={{ width: `${(s.count / total) * 100}%` }}
          />
        ))}
      </div>
      <div className="grid grid-cols-5 gap-2 text-[11px]">
        {stages.map((s) => (
          <div key={s.key} className="flex items-center gap-1.5">
            <span className={"h-2 w-2 rounded-full " + s.color} />
            <span className="text-muted-foreground">{s.label}</span>
            <span className="tabular-nums font-semibold ml-auto">
              {s.count}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ClientRow({
  client,
  onOpen,
}: {
  client: Client;
  onOpen: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className="w-full flex items-center gap-3 rounded-md border border-border px-3 py-2.5 hover:bg-accent/30 transition-colors text-left"
    >
      <div className="h-8 w-8 rounded-md bg-accent flex items-center justify-center shrink-0">
        <Building2 className="h-4 w-4 text-muted-foreground" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium truncate">{client.name}</div>
        <div className="text-xs text-muted-foreground truncate">
          {client.industry} · {client.location}
        </div>
      </div>
      <StageBadge stage={client.stage} />
      <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" />
    </button>
  );
}

function PendingActionCard({
  action,
  onApprove,
  onReject,
}: {
  action: DanAction;
  onApprove: () => void;
  onReject: () => void;
}) {
  const riskColor = {
    green: "text-emerald-400 border-emerald-500/30 bg-emerald-500/10",
    yellow: "text-amber-400 border-amber-500/30 bg-amber-500/10",
    red: "text-rose-400 border-rose-500/30 bg-rose-500/10",
  }[action.riskLevel];
  return (
    <div className="rounded-md border border-border bg-card p-3 space-y-2">
      <div className="flex items-start gap-2">
        <Badge
          variant="outline"
          className={"rounded-sm text-[9px] font-mono " + riskColor}
        >
          {action.riskLevel.toUpperCase()}
        </Badge>
        <div className="text-xs font-medium text-foreground flex-1 leading-snug">
          {action.title}
        </div>
      </div>
      <p className="text-[11px] text-muted-foreground leading-relaxed line-clamp-2">
        {action.detail}
      </p>
      <div className="flex gap-1.5 pt-0.5">
        <Button
          size="sm"
          className="h-7 text-[11px] flex-1 rounded-sm"
          onClick={onApprove}
        >
          承認・実行
        </Button>
        <Button
          size="sm"
          variant="outline"
          className="h-7 text-[11px] rounded-sm"
          onClick={onReject}
        >
          却下
        </Button>
      </div>
    </div>
  );
}
