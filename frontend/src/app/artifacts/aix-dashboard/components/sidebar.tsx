"use client";

import * as React from "react";
import {
  Home,
  Building2,
  Lightbulb,
  Film,
  Rocket,
  Send,
  Calendar,
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
  | "hypotheses"
  | "proposals"
  | "prototypes"
  | "outreach"
  | "meetings"
  | "ops"
  | "actions";

export const NAV: {
  key: AixView;
  label: string;
  icon: LucideIcon;
  group: "main" | "pipeline" | "ops" | "ai";
}[] = [
  { key: "home", label: "ホーム", icon: Home, group: "main" },
  { key: "clients", label: "クライアント", icon: Building2, group: "main" },
  { key: "hypotheses", label: "課題仮説", icon: Lightbulb, group: "pipeline" },
  { key: "proposals", label: "提案工房", icon: Film, group: "pipeline" },
  { key: "prototypes", label: "プロトタイプ", icon: Rocket, group: "pipeline" },
  { key: "outreach", label: "営業活動", icon: Send, group: "ops" },
  { key: "meetings", label: "商談", icon: Calendar, group: "ops" },
  { key: "ops", label: "契約・運用", icon: Briefcase, group: "ops" },
  { key: "actions", label: "ダンの承認待ち", icon: Sparkles, group: "ai" },
];

const GROUP_LABEL: Record<string, string> = {
  main: "Main",
  pipeline: "Pipeline",
  ops: "Operations",
  ai: "AI Cockpit",
};

type SidebarProps = {
  active: AixView;
  onNavigate: (v: AixView) => void;
  pendingActions: number;
};

export function AixSidebar({ active, onNavigate, pendingActions }: SidebarProps) {
  const grouped = React.useMemo(() => {
    const m: Record<string, typeof NAV> = {};
    for (const item of NAV) {
      m[item.group] = m[item.group] || [];
      m[item.group].push(item);
    }
    return m;
  }, []);

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

      <nav className="flex-1 py-4 px-2 space-y-4 overflow-y-auto">
        {Object.entries(grouped).map(([group, items]) => (
          <div key={group} className="space-y-0.5">
            <div className="text-[10px] text-muted-foreground px-3 py-1.5 tracking-widest uppercase">
              {GROUP_LABEL[group]}
            </div>
            {items.map((item) => {
              const Icon = item.icon;
              const isActive = active === item.key;
              const showBadge = item.key === "actions" && pendingActions > 0;
              return (
                <button
                  key={item.key}
                  type="button"
                  onClick={() => onNavigate(item.key)}
                  className={cn(
                    "w-full flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors",
                    isActive
                      ? "bg-accent text-accent-foreground"
                      : "text-muted-foreground hover:bg-accent/50 hover:text-foreground",
                  )}
                >
                  <Icon className="h-4 w-4 shrink-0" />
                  <span className="flex-1 text-left">{item.label}</span>
                  {showBadge && (
                    <Badge className="bg-amber-500/20 text-amber-400 hover:bg-amber-500/20 border-0 rounded-sm text-[10px] font-mono px-1.5">
                      {pendingActions}
                    </Badge>
                  )}
                </button>
              );
            })}
          </div>
        ))}
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
