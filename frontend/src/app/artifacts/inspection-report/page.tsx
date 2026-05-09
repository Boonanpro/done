"use client";

import { useState } from "react";
import {
  Home,
  Building2,
  Cpu,
  Wrench,
  Sliders,
  FileText,
  Settings,
  Plus,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

import { useInspectionStore } from "./store";
import { HomeView } from "./components/home-view";
import { ClientsView } from "./components/clients-view";
import { ClientDetailView } from "./components/client-detail-view";
import { EquipmentMasterView } from "./components/equipment-master-view";
import { InstrumentMasterView } from "./components/instrument-master-view";
import { GenerateView } from "./components/generate-view";
import { ConfirmView } from "./components/confirm-view";
import { SettingsView } from "./components/settings-view";

type View =
  | { kind: "home" }
  | { kind: "clients" }
  | { kind: "client_detail"; id: string }
  | { kind: "equipments" }
  | { kind: "instruments" }
  | { kind: "generate" }
  | { kind: "confirm" }
  | { kind: "settings" };

const navItems = [
  { key: "home", label: "ホーム", icon: Home },
  { key: "clients", label: "クライアント", icon: Building2 },
  { key: "equipments", label: "機器マスタ", icon: Cpu },
  { key: "instruments", label: "計測器", icon: Wrench },
  { key: "generate", label: "報告書を作る", icon: FileText, primary: true },
  { key: "settings", label: "設定", icon: Settings },
];

export default function InspectionReportPage() {
  const [view, setView] = useState<View>({ kind: "home" });
  const clients = useInspectionStore((s) => s.clients);
  const equipments = useInspectionStore((s) => s.equipments);
  const instruments = useInspectionStore((s) => s.instruments);

  return (
    <div className="flex h-screen bg-background text-foreground">
      {/* サイドバー */}
      <aside className="w-60 border-r border-border h-screen p-4 overflow-y-auto flex-shrink-0">
          <div className="mb-6">
            <h1 className="text-lg font-semibold">点検報告書</h1>
            <p className="text-xs text-muted-foreground mt-1">本田電気管理事務所</p>
          </div>
          <nav className="space-y-1">
            {navItems.map((item) => {
              const Icon = item.icon;
              const active =
                (item.key === "home" && view.kind === "home") ||
                (item.key === "clients" && (view.kind === "clients" || view.kind === "client_detail")) ||
                (item.key === "equipments" && view.kind === "equipments") ||
                (item.key === "instruments" && view.kind === "instruments") ||
                (item.key === "generate" && (view.kind === "generate" || view.kind === "confirm")) ||
                (item.key === "settings" && view.kind === "settings");
              return (
                <button
                  key={item.key}
                  onClick={() => setView({ kind: item.key as View["kind"] } as View)}
                  className={`w-full flex items-center gap-3 px-3 py-2 rounded-md text-sm transition ${
                    active
                      ? "bg-secondary text-foreground"
                      : item.primary
                        ? "bg-primary/10 text-primary hover:bg-primary/15"
                        : "text-muted-foreground hover:bg-secondary/50"
                  }`}
                >
                  <Icon className="h-4 w-4" />
                  <span className="flex-1 text-left">{item.label}</span>
                  {item.key === "clients" && (
                    <Badge variant="secondary" className="text-xs">{clients.length}</Badge>
                  )}
                  {item.key === "equipments" && (
                    <Badge variant="secondary" className="text-xs">{equipments.length}</Badge>
                  )}
                  {item.key === "instruments" && (
                    <Badge variant="secondary" className="text-xs">{instruments.length}</Badge>
                  )}
                </button>
              );
            })}
          </nav>

          <div className="mt-8 pt-6 border-t border-border">
            <p className="text-xs text-muted-foreground mb-2">プロトタイプ</p>
            <p className="text-xs text-muted-foreground">
              データはブラウザに保存されます（このPCのChrome内）
            </p>
          </div>
      </aside>

      {/* メイン */}
      <main className="flex-1 overflow-y-auto">
        <div className={`p-8 ${view.kind === "confirm" ? "max-w-none" : "max-w-6xl"}`}>
          {view.kind === "home" && <HomeView onNavigate={(v) => setView(v)} />}
          {view.kind === "clients" && (
            <ClientsView onSelect={(id) => setView({ kind: "client_detail", id })} />
          )}
          {view.kind === "client_detail" && (
            <ClientDetailView clientId={view.id} onBack={() => setView({ kind: "clients" })} />
          )}
          {view.kind === "equipments" && <EquipmentMasterView />}
          {view.kind === "instruments" && <InstrumentMasterView />}
          {view.kind === "generate" && (
            <GenerateView onGenerated={() => setView({ kind: "confirm" })} />
          )}
          {view.kind === "confirm" && (
            <ConfirmView
              onBack={() => setView({ kind: "generate" })}
              onComplete={() => setView({ kind: "home" })}
            />
          )}
          {view.kind === "settings" && <SettingsView />}
        </div>
      </main>
    </div>
  );
}
