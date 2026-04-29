"use client";

import * as React from "react";
import {
  ArrowLeft,
  ExternalLink,
  Sparkles,
  Rocket,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAix } from "../../data/store";
import { StageBadge } from "../ui-bits";
import { ClientChat } from "../client-chat";

type Props = {
  clientId: string;
  onBack: () => void;
};

export function ClientDetailView({ clientId, onBack }: Props) {
  const { clients, prototypes } = useAix();
  const client = clients.find((c) => c.id === clientId);
  const cProto = prototypes.filter((p) => p.clientId === clientId);
  const liveProtos = cProto.filter(
    (p) => p.status === "live" && (p.url.startsWith("/") || p.url.startsWith("http")),
  );
  const [selectedProto, setSelectedProto] = React.useState<string | null>(
    liveProtos[0]?.id ?? null,
  );
  React.useEffect(() => {
    if (!selectedProto && liveProtos.length > 0) setSelectedProto(liveProtos[0].id);
  }, [selectedProto, liveProtos]);

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

  const activeProto = liveProtos.find((p) => p.id === selectedProto);

  return (
    <div className="flex flex-col h-[calc(100vh-64px)] gap-3">
      {/* 最小ヘッダー */}
      <div className="flex items-center gap-3">
        <Button
          variant="ghost"
          size="sm"
          onClick={onBack}
          className="h-7 -ml-2 text-muted-foreground"
        >
          <ArrowLeft className="h-3.5 w-3.5 mr-1" />
          一覧
        </Button>
        <h1 className="text-lg font-semibold tracking-tight truncate">{client.name}</h1>
        <StageBadge stage={client.stage} />
      </div>

      {/* メイン: 左チャット + 右成果物（このページ以外なし） */}
      <div className="flex-1 min-h-0 grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-3">
        {/* 左: チャット */}
        <div className="min-h-[480px]">
          <ClientChat clientId={clientId} clientName={client.name} />
        </div>

        {/* 右: 成果物プレビュー */}
        <div className="min-h-[480px] border border-border rounded-lg bg-card overflow-hidden flex flex-col">
          <div className="px-4 py-3 border-b border-border bg-accent/20 flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 min-w-0">
              <Rocket className="h-4 w-4 text-purple-400 shrink-0" />
              <div className="text-sm font-medium truncate">
                {activeProto ? activeProto.name : "成果物"}
              </div>
            </div>
            {liveProtos.length > 1 && (
              <select
                value={selectedProto ?? ""}
                onChange={(e) => setSelectedProto(e.target.value)}
                className="h-7 text-xs rounded-sm border border-input bg-transparent px-2"
              >
                {liveProtos.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            )}
            {activeProto && (
              <a
                href={activeProto.url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-xs text-foreground hover:text-primary"
              >
                <ExternalLink className="h-3 w-3" />
                別タブ
              </a>
            )}
          </div>
          <div className="flex-1 bg-white">
            {activeProto ? (
              <iframe
                key={activeProto.id}
                src={activeProto.url}
                className="w-full h-full border-0"
                title={activeProto.name}
              />
            ) : (
              <div className="h-full flex flex-col items-center justify-center gap-3 text-center p-6 text-muted-foreground">
                <Sparkles className="h-8 w-8 text-amber-400/60" />
                <div className="text-sm">まだ成果物がありません</div>
                <div className="text-xs">
                  左のチャットで「HPを作って」「ツールを作って」と話してみてください
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
