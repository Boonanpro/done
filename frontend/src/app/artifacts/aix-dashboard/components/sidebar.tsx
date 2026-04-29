"use client";

import * as React from "react";
import {
  Home,
  Building2,
  Rocket,
  Briefcase,
  Sparkles,
  CheckCircle2,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";

export type AixView =
  | "home"
  | "clients"
  | "deliverables"
  | "revenue";

export const NAV: {
  key: AixView;
  label: string;
  description: string;
  icon: LucideIcon;
}[] = [
  { key: "home", label: "ホーム", description: "今日のやり取り・承認待ち", icon: Home },
  { key: "clients", label: "クライアント", description: "ダンと話しながら成果物を作る", icon: Building2 },
  { key: "deliverables", label: "成果物", description: "稼働中のHPやツール一覧", icon: Rocket },
  { key: "revenue", label: "収益・契約", description: "MRR・契約状況", icon: Briefcase },
];

type SidebarProps = {
  active: AixView;
  onNavigate: (v: AixView) => void;
  pendingActions: number;
};

export function AixSidebar({ active, onNavigate, pendingActions }: SidebarProps) {
  return (
    <aside className="w-64 shrink-0 border-r border-border bg-card flex flex-col">
      <div className="px-5 py-5 border-b border-border">
        <div className="flex items-center gap-3">
          <div className="h-9 w-9 rounded-lg bg-gradient-to-br from-primary to-blue-500 flex items-center justify-center">
            <Sparkles className="h-5 w-5 text-primary-foreground" />
          </div>
          <div>
            <div className="text-sm font-semibold">AIX Cockpit</div>
            <div className="text-[10px] text-muted-foreground tracking-widest uppercase">
              Dan-driven DX
            </div>
          </div>
        </div>
      </div>

      <nav className="flex-1 py-4 px-2 space-y-1 overflow-y-auto">
        {NAV.map((item) => {
          const Icon = item.icon;
          const isActive = active === item.key;
          const showBadge = item.key === "home" && pendingActions > 0;
          return (
            <button
              key={item.key}
              type="button"
              onClick={() => onNavigate(item.key)}
              className={cn(
                "w-full flex items-start gap-3 rounded-md px-3 py-2.5 text-left transition-colors",
                isActive
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground hover:bg-accent/50 hover:text-foreground",
              )}
            >
              <Icon className="h-4 w-4 shrink-0 mt-0.5" />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">{item.label}</span>
                  {showBadge && (
                    <Badge className="bg-amber-500/20 text-amber-400 hover:bg-amber-500/20 border-0 rounded-sm text-[10px] font-mono px-1.5">
                      {pendingActions}
                    </Badge>
                  )}
                </div>
                <div className="text-[10px] text-muted-foreground/70 mt-0.5 truncate">
                  {item.description}
                </div>
              </div>
            </button>
          );
        })}
      </nav>

      <div className="border-t border-border p-4 text-xs text-muted-foreground">
        <div className="flex items-center gap-2">
          <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
          <span>本田 樹（みき）さん</span>
        </div>
        <div className="mt-1 text-[10px]">ダンがあなたの代わりに動きます</div>
      </div>
    </aside>
  );
}
