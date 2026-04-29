"use client";

import { Rocket, ExternalLink, Building2 } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useAix } from "../../data/store";

type Props = {
  onOpenClient: (id: string) => void;
};

export function DeliverablesView({ onOpenClient }: Props) {
  const { prototypes, clients } = useAix();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          <Rocket className="h-5 w-5 text-purple-400" />
          成果物
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          全クライアントの稼働中HP・ツールを横断して確認できます。
        </p>
      </div>

      {prototypes.length === 0 && (
        <div className="text-sm text-muted-foreground text-center py-12">
          まだ成果物はありません。クライアント詳細でダンと話しながら作ってみてください。
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {prototypes.map((p) => {
          const c = clients.find((x) => x.id === p.clientId);
          return (
            <Card key={p.id} className="overflow-hidden">
              <CardContent className="p-5 space-y-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="space-y-1 min-w-0">
                    <div className="font-medium text-sm truncate">{p.name}</div>
                    <button
                      type="button"
                      onClick={() => c && onOpenClient(c.id)}
                      className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
                    >
                      <Building2 className="h-3 w-3" />
                      {c?.name ?? "—"}
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

                <p className="text-xs text-muted-foreground leading-relaxed line-clamp-2">
                  {p.description || "—"}
                </p>

                <div className="flex items-center justify-between text-[11px] pt-2 border-t border-border">
                  <span className="text-muted-foreground">最終更新 {p.lastUpdated}</span>
                  {p.url && (p.url.startsWith("/") || p.url.startsWith("http")) && (
                    <a
                      href={p.url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 text-xs text-foreground hover:text-primary"
                    >
                      <ExternalLink className="h-3 w-3" />
                      開く
                    </a>
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
