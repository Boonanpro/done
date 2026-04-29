"use client";

import { Briefcase, TrendingUp, Users, FileText } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useAix } from "../../data/store";

type Props = {
  onOpenClient: (id: string) => void;
};

export function RevenueView({ onOpenClient }: Props) {
  const { contracts, clients } = useAix();

  const active = contracts.filter((c) => c.status === "active");
  const totalMrr = active.reduce((sum, c) => sum + (c.mrr || 0), 0);
  const totalOneTime = active.reduce((sum, c) => sum + (c.oneTime || 0), 0);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          <Briefcase className="h-5 w-5 text-amber-400" />
          収益・契約
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          全クライアントの月次収益（MRR）と契約状況。
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <Kpi
          label="月次収益 (MRR)"
          value={`¥${totalMrr.toLocaleString()}`}
          hint={`${active.length}件の稼働契約`}
          icon={<TrendingUp className="h-3.5 w-3.5" />}
        />
        <Kpi
          label="累計初期費用"
          value={`¥${totalOneTime.toLocaleString()}`}
          hint="今年度の一時収益"
          icon={<FileText className="h-3.5 w-3.5" />}
        />
        <Kpi
          label="契約クライアント"
          value={`${new Set(active.map((c) => c.clientId)).size}`}
          hint={`全${clients.length}社中`}
          icon={<Users className="h-3.5 w-3.5" />}
        />
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium">契約一覧</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {contracts.length === 0 && (
            <div className="text-xs text-muted-foreground text-center py-8">
              契約がありません
            </div>
          )}
          {contracts.map((c) => {
            const client = clients.find((x) => x.id === c.clientId);
            return (
              <button
                key={c.id}
                type="button"
                onClick={() => client && onOpenClient(client.id)}
                className="w-full flex items-center gap-4 rounded-md border border-border p-3 hover:bg-accent/30 transition-colors text-left"
              >
                <Briefcase className="h-4 w-4 text-muted-foreground shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium truncate">{c.title}</div>
                  <div className="text-xs text-muted-foreground truncate">
                    {client?.name ?? "—"}
                  </div>
                </div>
                <div className="text-right">
                  <div className="font-mono text-sm tabular-nums">
                    ¥{c.mrr.toLocaleString()}/月
                  </div>
                  {c.oneTime ? (
                    <div className="text-xs text-muted-foreground font-mono tabular-nums">
                      初期 ¥{c.oneTime.toLocaleString()}
                    </div>
                  ) : null}
                </div>
                <Badge variant="outline" className="rounded-sm text-[10px]">
                  {c.status === "active" ? "契約中" : c.status === "ended" ? "終了" : "交渉中"}
                </Badge>
              </button>
            );
          })}
        </CardContent>
      </Card>
    </div>
  );
}

function Kpi({
  label,
  value,
  hint,
  icon,
}: {
  label: string;
  value: string;
  hint: string;
  icon?: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-1.5">
        {icon}
        {label}
      </div>
      <div className="text-2xl font-semibold tabular-nums">{value}</div>
      <div className="text-[11px] text-muted-foreground mt-0.5">{hint}</div>
    </div>
  );
}
