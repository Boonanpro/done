"use client";

import {
  ArrowLeft,
  ExternalLink,
  Phone,
  User,
  MapPin,
  Calendar,
  Target,
  CheckCircle2,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAix } from "../../data/store";
import {
  StageBadge,
  PriorityBadge,
  ProposalStatusBadge,
  OpsStatusChip,
  ActionStatusBadge,
} from "../ui-bits";

type Props = {
  clientId: string;
  onBack: () => void;
};

export function ClientDetailView({ clientId, onBack }: Props) {
  const {
    clients,
    hypotheses,
    proposals,
    prototypes,
    outreach,
    meetings,
    contracts,
    opsTasks,
    danActions,
  } = useAix();
  const client = clients.find((c) => c.id === clientId);
  if (!client) {
    return (
      <div className="space-y-4">
        <Button variant="ghost" size="sm" onClick={onBack}>
          <ArrowLeft className="h-4 w-4 mr-1" />
          戻る
        </Button>
        <div className="text-sm text-muted-foreground">
          クライアントが見つかりません。
        </div>
      </div>
    );
  }
  const cHyp = hypotheses.filter((h) => h.clientId === clientId);
  const cProp = proposals.filter((p) => p.clientId === clientId);
  const cProto = prototypes.filter((p) => p.clientId === clientId);
  const cOut = outreach.filter((o) => o.clientId === clientId);
  const cMtg = meetings.filter((m) => m.clientId === clientId);
  const cCon = contracts.filter((c) => c.clientId === clientId);
  const cOps = opsTasks.filter((o) => o.clientId === clientId);
  const cAct = danActions.filter((a) => a.clientId === clientId);

  return (
    <div className="space-y-6">
      <Button
        variant="ghost"
        size="sm"
        onClick={onBack}
        className="h-7 -ml-2 text-muted-foreground"
      >
        <ArrowLeft className="h-3.5 w-3.5 mr-1" />
        戻る
      </Button>

      {/* Header */}
      <Card>
        <CardContent className="p-6">
          <div className="flex items-start justify-between gap-4">
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <StageBadge stage={client.stage} />
                <PriorityBadge priority={client.priority} />
              </div>
              <h1 className="text-2xl font-semibold tracking-tight">
                {client.name}
              </h1>
              <div className="text-sm text-muted-foreground">
                {client.industry} · {client.size}
              </div>
            </div>
            <div className="text-right space-y-1 text-xs text-muted-foreground">
              <div className="flex items-center gap-1.5 justify-end">
                <MapPin className="h-3 w-3" />
                {client.location}
              </div>
              {client.contactName !== "—" && (
                <div className="flex items-center gap-1.5 justify-end">
                  <User className="h-3 w-3" />
                  {client.contactName} ({client.contactRole})
                </div>
              )}
              {client.contactPhone && (
                <div className="flex items-center gap-1.5 justify-end font-mono">
                  <Phone className="h-3 w-3" />
                  {client.contactPhone}
                </div>
              )}
              <div className="flex items-center gap-1.5 justify-end">
                <Calendar className="h-3 w-3" />
                登録 {client.assignedAt}
              </div>
            </div>
          </div>
          <p className="text-sm mt-5 leading-relaxed text-foreground/90">
            {client.summary}
          </p>
          {client.kpiNote && (
            <div className="mt-3 rounded-md bg-accent/30 border border-border px-3 py-2 text-xs flex items-center gap-2">
              <Target className="h-3.5 w-3.5 text-amber-400" />
              <span className="text-muted-foreground">KPI目標:</span>
              <span>{client.kpiNote}</span>
            </div>
          )}
          <div className="flex gap-1.5 flex-wrap mt-4">
            {client.tags.map((t) => (
              <Badge
                key={t}
                variant="outline"
                className="rounded-sm text-[10px]"
              >
                {t}
              </Badge>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Tabs */}
      <Tabs defaultValue="hypotheses" className="space-y-4">
        <TabsList className="rounded-sm">
          <TabsTrigger value="hypotheses" className="text-xs rounded-sm">
            課題仮説 ({cHyp.length})
          </TabsTrigger>
          <TabsTrigger value="proposals" className="text-xs rounded-sm">
            提案 ({cProp.length})
          </TabsTrigger>
          <TabsTrigger value="prototypes" className="text-xs rounded-sm">
            プロトタイプ ({cProto.length})
          </TabsTrigger>
          <TabsTrigger value="outreach" className="text-xs rounded-sm">
            営業活動 ({cOut.length})
          </TabsTrigger>
          <TabsTrigger value="meetings" className="text-xs rounded-sm">
            商談 ({cMtg.length})
          </TabsTrigger>
          <TabsTrigger value="contracts" className="text-xs rounded-sm">
            契約 ({cCon.length})
          </TabsTrigger>
          <TabsTrigger value="ops" className="text-xs rounded-sm">
            運用 ({cOps.length})
          </TabsTrigger>
          <TabsTrigger value="actions" className="text-xs rounded-sm">
            ダン履歴 ({cAct.length})
          </TabsTrigger>
        </TabsList>

        <TabsContent value="hypotheses" className="space-y-3">
          {cHyp.length === 0 && <Empty>仮説なし</Empty>}
          {cHyp.map((h) => (
            <Card key={h.id}>
              <CardContent className="p-5 space-y-3">
                <div className="flex items-start justify-between gap-3">
                  <h3 className="font-medium text-sm">{h.title}</h3>
                  <div className="flex gap-1.5 shrink-0">
                    <Badge variant="outline" className="rounded-sm text-[10px]">
                      影響: {h.impact}
                    </Badge>
                    <Badge variant="outline" className="rounded-sm text-[10px]">
                      確度: {h.confidence}
                    </Badge>
                    <Badge
                      variant="outline"
                      className="rounded-sm text-[10px]"
                    >
                      {h.status}
                    </Badge>
                  </div>
                </div>
                <div className="text-xs text-muted-foreground">
                  <span className="text-rose-400">課題: </span>
                  {h.problem}
                </div>
                <div className="text-xs text-muted-foreground">
                  <span className="text-emerald-400">解決策: </span>
                  {h.solution}
                </div>
              </CardContent>
            </Card>
          ))}
        </TabsContent>

        <TabsContent value="proposals" className="space-y-3">
          {cProp.length === 0 && <Empty>提案なし</Empty>}
          {cProp.map((p) => (
            <Card key={p.id}>
              <CardContent className="p-5 space-y-2">
                <div className="flex items-start justify-between gap-3">
                  <h3 className="font-medium text-sm">{p.title}</h3>
                  <ProposalStatusBadge status={p.status} />
                </div>
                <p className="text-xs text-muted-foreground leading-relaxed">
                  {p.summary}
                </p>
                {p.prototypeUrl && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7 text-xs rounded-sm"
                    asChild
                  >
                    <a href={p.prototypeUrl} target="_blank" rel="noreferrer">
                      <ExternalLink className="h-3 w-3 mr-1" />
                      プロトタイプを開く
                    </a>
                  </Button>
                )}
              </CardContent>
            </Card>
          ))}
        </TabsContent>

        <TabsContent value="prototypes" className="space-y-3">
          {cProto.length === 0 && <Empty>プロトタイプなし</Empty>}
          {cProto.map((p) => (
            <Card key={p.id}>
              <CardContent className="p-5 space-y-3">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h3 className="font-medium text-sm">{p.name}</h3>
                    <div className="text-xs text-muted-foreground mt-0.5">
                      更新: {p.lastUpdated}
                    </div>
                  </div>
                  <Badge variant="outline" className="rounded-sm text-[10px]">
                    {p.status === "live" ? "稼働中" : p.status === "building" ? "開発中" : "停止"}
                  </Badge>
                </div>
                <p className="text-xs text-muted-foreground">{p.description}</p>
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
                {p.url.startsWith("/") || p.url.startsWith("http") ? (
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7 text-xs rounded-sm"
                    asChild
                  >
                    <a href={p.url} target="_blank" rel="noreferrer">
                      <ExternalLink className="h-3 w-3 mr-1" />
                      プロトを開く
                    </a>
                  </Button>
                ) : null}
              </CardContent>
            </Card>
          ))}
        </TabsContent>

        <TabsContent value="outreach" className="space-y-3">
          {cOut.length === 0 && <Empty>営業履歴なし</Empty>}
          {cOut.map((o) => (
            <Card key={o.id}>
              <CardContent className="p-4 space-y-2">
                <div className="flex items-center justify-between text-xs">
                  <div className="flex items-center gap-2">
                    <Badge
                      variant="outline"
                      className="rounded-sm text-[10px]"
                    >
                      {o.direction === "outbound" ? "送信" : "受信"}
                    </Badge>
                    <Badge
                      variant="outline"
                      className="rounded-sm text-[10px]"
                    >
                      {o.kind}
                    </Badge>
                    <span className="text-muted-foreground">
                      {o.occurredAt}
                    </span>
                  </div>
                  <Badge variant="outline" className="rounded-sm text-[10px]">
                    {o.outcome}
                  </Badge>
                </div>
                <div className="text-sm font-medium">{o.subject}</div>
                <p className="text-xs text-muted-foreground leading-relaxed">
                  {o.body}
                </p>
              </CardContent>
            </Card>
          ))}
        </TabsContent>

        <TabsContent value="meetings" className="space-y-3">
          {cMtg.length === 0 && <Empty>商談なし</Empty>}
          {cMtg.map((m) => (
            <Card key={m.id}>
              <CardContent className="p-4 flex items-center gap-4">
                <div className="text-center w-16 shrink-0">
                  <div className="text-xs text-muted-foreground">
                    {new Date(m.scheduledAt).toLocaleDateString()}
                  </div>
                  <div className="font-mono text-lg font-bold tabular-nums">
                    {new Date(m.scheduledAt).toLocaleTimeString("ja", {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </div>
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium">{m.title}</div>
                  <div className="text-xs text-muted-foreground">
                    {m.mode === "online" ? "オンライン" : "対面"} ·{" "}
                    {m.durationMinutes}分
                  </div>
                </div>
                <Badge variant="outline" className="rounded-sm text-[10px]">
                  {m.status === "upcoming" ? "予定" : m.status === "done" ? "完了" : "中止"}
                </Badge>
              </CardContent>
            </Card>
          ))}
        </TabsContent>

        <TabsContent value="contracts" className="space-y-3">
          {cCon.length === 0 && <Empty>契約なし</Empty>}
          {cCon.map((c) => (
            <Card key={c.id}>
              <CardContent className="p-5 space-y-3">
                <div className="flex items-start justify-between gap-3">
                  <h3 className="font-medium text-sm">{c.title}</h3>
                  <Badge variant="outline" className="rounded-sm text-[10px]">
                    {c.status}
                  </Badge>
                </div>
                <div className="grid grid-cols-2 gap-3 text-xs">
                  <div>
                    <div className="text-muted-foreground">月額</div>
                    <div className="font-mono text-base font-bold tabular-nums">
                      ¥{c.mrr.toLocaleString()}
                    </div>
                  </div>
                  {c.oneTime && (
                    <div>
                      <div className="text-muted-foreground">初期費用</div>
                      <div className="font-mono text-base tabular-nums">
                        ¥{c.oneTime.toLocaleString()}
                      </div>
                    </div>
                  )}
                </div>
                <ul className="text-xs text-muted-foreground space-y-1">
                  {c.scope.map((s) => (
                    <li key={s} className="flex gap-1.5">
                      <CheckCircle2 className="h-3 w-3 text-emerald-500 shrink-0 mt-0.5" />
                      {s}
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          ))}
        </TabsContent>

        <TabsContent value="ops" className="space-y-3">
          {cOps.length === 0 && <Empty>運用タスクなし</Empty>}
          {cOps.map((t) => (
            <Card key={t.id}>
              <CardContent className="p-4 flex items-start gap-3">
                <OpsStatusChip status={t.status} />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium">{t.title}</div>
                  <div className="text-xs text-muted-foreground mt-0.5">
                    {t.detail}
                  </div>
                </div>
                <PriorityBadge priority={t.priority} />
              </CardContent>
            </Card>
          ))}
        </TabsContent>

        <TabsContent value="actions" className="space-y-3">
          {cAct.length === 0 && <Empty>ダンの履歴なし</Empty>}
          {cAct.map((a) => (
            <Card key={a.id}>
              <CardContent className="p-4 space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <div className="text-xs text-muted-foreground font-mono">
                    {a.kind}
                  </div>
                  <ActionStatusBadge status={a.status} />
                </div>
                <div className="text-sm font-medium">{a.title}</div>
                <p className="text-xs text-muted-foreground leading-relaxed">
                  {a.detail}
                </p>
              </CardContent>
            </Card>
          ))}
        </TabsContent>
      </Tabs>
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-center text-xs text-muted-foreground py-8">
      {children}
    </div>
  );
}
