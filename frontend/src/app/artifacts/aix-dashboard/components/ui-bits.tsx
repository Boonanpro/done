"use client";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type {
  ClientStage,
  Priority,
  DanAction,
  Proposal,
  OpsTask,
} from "../data/mock";

const STAGE_STYLES: Record<ClientStage, { label: string; cls: string }> = {
  prospect: {
    label: "見込み",
    cls: "text-slate-300 border-slate-500/30 bg-slate-500/10",
  },
  proposed: {
    label: "提案中",
    cls: "text-blue-400 border-blue-500/30 bg-blue-500/10",
  },
  meeting: {
    label: "商談中",
    cls: "text-purple-400 border-purple-500/30 bg-purple-500/10",
  },
  contracted: {
    label: "契約済",
    cls: "text-amber-400 border-amber-500/30 bg-amber-500/10",
  },
  running: {
    label: "運用中",
    cls: "text-emerald-400 border-emerald-500/30 bg-emerald-500/10",
  },
  paused: {
    label: "一時停止",
    cls: "text-rose-400 border-rose-500/30 bg-rose-500/10",
  },
};

export function StageBadge({ stage }: { stage: ClientStage }) {
  const s = STAGE_STYLES[stage];
  return (
    <Badge
      variant="outline"
      className={cn("rounded-sm text-[10px] font-medium", s.cls)}
    >
      {s.label}
    </Badge>
  );
}

export function PriorityBadge({ priority }: { priority: Priority }) {
  const map = {
    high: { label: "高", cls: "text-rose-400 border-rose-500/30 bg-rose-500/10" },
    mid: { label: "中", cls: "text-amber-400 border-amber-500/30 bg-amber-500/10" },
    low: { label: "低", cls: "text-slate-400 border-slate-500/30 bg-slate-500/10" },
  } as const;
  const s = map[priority];
  return (
    <Badge variant="outline" className={cn("rounded-sm text-[10px]", s.cls)}>
      {s.label}
    </Badge>
  );
}

export function ActionStatusBadge({ status }: { status: DanAction["status"] }) {
  const map: Record<DanAction["status"], { label: string; cls: string }> = {
    pending_review: {
      label: "承認待ち",
      cls: "text-amber-400 border-amber-500/30 bg-amber-500/10",
    },
    approved: {
      label: "承認済",
      cls: "text-blue-400 border-blue-500/30 bg-blue-500/10",
    },
    rejected: {
      label: "却下",
      cls: "text-rose-400 border-rose-500/30 bg-rose-500/10",
    },
    executed: {
      label: "実行済",
      cls: "text-emerald-400 border-emerald-500/30 bg-emerald-500/10",
    },
    rolled_back: {
      label: "ロールバック",
      cls: "text-slate-400 border-slate-500/30 bg-slate-500/10",
    },
  };
  const s = map[status];
  return (
    <Badge variant="outline" className={cn("rounded-sm text-[10px]", s.cls)}>
      {s.label}
    </Badge>
  );
}

export function ProposalStatusBadge({ status }: { status: Proposal["status"] }) {
  const map: Record<Proposal["status"], { label: string; cls: string }> = {
    drafting: {
      label: "作成中",
      cls: "text-slate-400 border-slate-500/30 bg-slate-500/10",
    },
    ready: {
      label: "準備完了",
      cls: "text-blue-400 border-blue-500/30 bg-blue-500/10",
    },
    sent: {
      label: "送付済",
      cls: "text-purple-400 border-purple-500/30 bg-purple-500/10",
    },
    responded: {
      label: "反応あり",
      cls: "text-amber-400 border-amber-500/30 bg-amber-500/10",
    },
    won: {
      label: "受注",
      cls: "text-emerald-400 border-emerald-500/30 bg-emerald-500/10",
    },
    lost: {
      label: "失注",
      cls: "text-rose-400 border-rose-500/30 bg-rose-500/10",
    },
  };
  const s = map[status];
  return (
    <Badge variant="outline" className={cn("rounded-sm text-[10px]", s.cls)}>
      {s.label}
    </Badge>
  );
}

export function OpsStatusChip({ status }: { status: OpsTask["status"] }) {
  const map: Record<OpsTask["status"], { label: string; cls: string }> = {
    todo: {
      label: "未着手",
      cls: "text-slate-400 border-slate-500/30 bg-slate-500/10",
    },
    doing: {
      label: "進行中",
      cls: "text-blue-400 border-blue-500/30 bg-blue-500/10",
    },
    review: {
      label: "レビュー",
      cls: "text-amber-400 border-amber-500/30 bg-amber-500/10",
    },
    done: {
      label: "完了",
      cls: "text-emerald-400 border-emerald-500/30 bg-emerald-500/10",
    },
  };
  const s = map[status];
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-sm border px-1.5 py-0.5 text-[10px]",
        s.cls,
      )}
    >
      {s.label}
    </span>
  );
}
