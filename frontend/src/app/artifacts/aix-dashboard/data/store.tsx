"use client";

import * as React from "react";
import {
  type Client,
  type ClientStage,
  type Priority,
  type Hypothesis,
  type Proposal,
  type Outreach,
  type Meeting,
  type Contract,
  type OpsTask,
  type DanAction,
  type Prototype,
} from "./mock";

/**
 * AIX ダッシュボード state ストア（実DB版）。
 *
 * 起動時に GET /api/v1/aix/snapshot で全データを取得して mock 互換型へ変換、
 * View 側は従来通り mock の型を使うので変更不要。
 *
 * 各更新メソッドは API を叩いた後にローカル state を反映（楽観更新）。
 * APIエラー時はサイレント（次回 refresh で同期）。
 */

const API_BASE = "/api/v1/aix";

type AixState = {
  clients: Client[];
  hypotheses: Hypothesis[];
  proposals: Proposal[];
  prototypes: Prototype[]; // engagements を表示用に流用
  outreach: Outreach[];
  meetings: Meeting[];
  contracts: Contract[];
  opsTasks: OpsTask[];
  danActions: DanAction[];
  loaded: boolean;
};

const EMPTY_STATE: AixState = {
  clients: [],
  hypotheses: [],
  proposals: [],
  prototypes: [],
  outreach: [],
  meetings: [],
  contracts: [],
  opsTasks: [],
  danActions: [],
  loaded: false,
};

/* ─────────────── DB row → mock型 アダプタ ─────────────── */

function priorityFromHealth(score: number | null | undefined): Priority {
  if ((score ?? 50) >= 75) return "high";
  if ((score ?? 50) >= 50) return "mid";
  return "low";
}

function healthFromPriority(p: Priority | undefined): number {
  return p === "high" ? 80 : p === "low" ? 30 : 55;
}

function stageFromDb(s?: string): ClientStage {
  switch (s) {
    case "research": return "prospect";
    case "proposal": return "proposed";
    case "negotiation": return "meeting";
    case "contracted": return "contracted";
    case "live": return "running";
    case "paused": return "paused";
    case "lost": return "paused";
    default: return "prospect";
  }
}

function stageToDb(s: ClientStage): string {
  switch (s) {
    case "prospect": return "research";
    case "proposed": return "proposal";
    case "meeting": return "negotiation";
    case "contracted": return "contracted";
    case "running": return "live";
    case "paused": return "paused";
  }
}

function impactFromConfidence(c: number | null | undefined): "high" | "mid" | "low" {
  if ((c ?? 50) >= 70) return "high";
  if ((c ?? 50) >= 40) return "mid";
  return "low";
}

function hypothesisStatusFromDb(s?: string): Hypothesis["status"] {
  switch (s) {
    case "validated": return "validated";
    case "rejected":
    case "on_hold":
      return "archived";
    default: return "draft";
  }
}

function proposalStatusFromDb(s?: string): Proposal["status"] {
  switch (s) {
    case "draft": return "drafting";
    case "ready": return "ready";
    case "sent": return "sent";
    case "viewed":
    case "replied":
      return "responded";
    case "won": return "won";
    case "lost": return "lost";
    default: return "drafting";
  }
}

function adaptClient(row: Record<string, unknown>): Client {
  const tags = Array.isArray(row.tags) ? (row.tags as string[]) : [];
  return {
    id: String(row.id),
    name: String(row.name ?? ""),
    industry: String(row.industry ?? ""),
    size: String(row.size ?? ""),
    location: String(row.region ?? ""),
    website: row.website ? String(row.website) : undefined,
    contactName: String(row.contact_name ?? "—"),
    contactRole: String(row.contact_role ?? "—"),
    contactEmail: row.contact_email ? String(row.contact_email) : undefined,
    contactPhone: row.contact_phone ? String(row.contact_phone) : undefined,
    stage: stageFromDb(row.stage as string),
    priority: priorityFromHealth(row.health_score as number | null),
    assignedAt: String(row.created_at ?? "").slice(0, 10),
    summary: String(row.notes ?? ""),
    tags,
    kpiNote: row.estimated_value ? `想定収益 ¥${(row.estimated_value as number).toLocaleString()}` : undefined,
  };
}

function adaptHypothesis(row: Record<string, unknown>): Hypothesis {
  const conf = (row.confidence as number) ?? 50;
  return {
    id: String(row.id),
    clientId: String(row.client_id),
    title: String(row.title ?? ""),
    problem: String(row.pain_point ?? ""),
    solution: String(row.proposed_solution ?? ""),
    impact: impactFromConfidence(conf),
    confidence: conf >= 70 ? "high" : conf >= 40 ? "mid" : "low",
    status: hypothesisStatusFromDb(row.status as string),
    createdAt: String(row.created_at ?? "").slice(0, 10),
  };
}

function adaptProposal(row: Record<string, unknown>): Proposal {
  return {
    id: String(row.id),
    clientId: String(row.client_id),
    hypothesisId: row.hypothesis_id ? String(row.hypothesis_id) : "",
    title: String(row.title ?? ""),
    status: proposalStatusFromDb(row.status as string),
    videoUrl: row.proposal_video_path ? String(row.proposal_video_path) : undefined,
    prototypeUrl: row.prototype_url ? String(row.prototype_url) : undefined,
    sentAt: row.sent_at ? String(row.sent_at).slice(0, 10) : undefined,
    summary: String(row.summary ?? ""),
  };
}

function adaptEngagementToProto(row: Record<string, unknown>): Prototype {
  const features = Array.isArray(row.kpis)
    ? []
    : Object.entries((row.kpis as Record<string, unknown>) ?? {}).map(([k, v]) => `${k}: ${v}`);
  return {
    id: String(row.id),
    clientId: String(row.client_id),
    proposalId: undefined,
    name: String(row.deliverable_name ?? ""),
    description: String(row.notes ?? ""),
    url: String(row.deliverable_url ?? "#"),
    status: row.status === "live" ? "live" : row.status === "building" ? "building" : "retired",
    coreFeatures: features,
    lastUpdated: String(row.updated_at ?? "").slice(0, 10),
  };
}

function adaptActivityToOutreach(row: Record<string, unknown>): Outreach | null {
  const t = String(row.activity_type);
  if (!["email_sent", "email_received", "call"].includes(t)) return null;
  return {
    id: String(row.id),
    clientId: String(row.client_id),
    kind: t === "call" ? "phone" : "email",
    direction: t === "email_received" ? "inbound" : "outbound",
    subject: String(row.subject ?? ""),
    body: String(row.body ?? ""),
    occurredAt: String(row.occurred_at ?? "").slice(0, 10),
    outcome: "sent",
  };
}

function adaptActivityToMeeting(row: Record<string, unknown>): Meeting | null {
  if (row.activity_type !== "meeting") return null;
  return {
    id: String(row.id),
    clientId: String(row.client_id),
    title: String(row.subject ?? ""),
    mode: "online",
    scheduledAt: String(row.occurred_at ?? new Date().toISOString()),
    durationMinutes: 45,
    status: new Date(row.occurred_at as string) > new Date() ? "upcoming" : "done",
    summary: row.body ? String(row.body) : undefined,
    nextActions: row.next_action ? [String(row.next_action)] : undefined,
  };
}

function adaptContract(row: Record<string, unknown>): Contract {
  return {
    id: String(row.id),
    clientId: String(row.client_id),
    title: String(row.title ?? ""),
    mrr: Number(row.monthly_value ?? 0),
    oneTime: row.initial_value ? Number(row.initial_value) : undefined,
    status: row.status === "active" ? "active" : row.status === "completed" ? "ended" : "negotiation",
    startDate: row.start_date ? String(row.start_date) : undefined,
    endDate: row.end_date ? String(row.end_date) : undefined,
    scope: row.notes ? String(row.notes).split("\n") : [],
  };
}

function adaptTaskToOps(row: Record<string, unknown>): OpsTask | null {
  if (row.zone !== "green") return null;
  if (row.status === "awaiting_approval") return null; // ダンの提案扱いに回す
  const statusMap: Record<string, OpsTask["status"]> = {
    todo: "todo",
    in_progress: "doing",
    awaiting_approval: "review",
    done: "done",
    cancelled: "done",
  };
  return {
    id: String(row.id),
    clientId: String(row.client_id ?? ""),
    title: String(row.title ?? ""),
    detail: String(row.description ?? ""),
    status: statusMap[String(row.status)] || "todo",
    priority: row.priority === "high" || row.priority === "urgent" ? "high" : row.priority === "low" ? "low" : "mid",
    dueDate: row.due_at ? String(row.due_at).slice(0, 10) : undefined,
    assignee: "both",
  };
}

function adaptTaskToDanAction(row: Record<string, unknown>): DanAction | null {
  // zone=yellow/red もしくは status=awaiting_approval → ダンアクション扱い
  const isApproval = row.zone === "yellow" || row.zone === "red" || row.status === "awaiting_approval";
  if (!isApproval && row.status !== "done") return null;
  const status: DanAction["status"] =
    row.status === "done" ? "executed" :
    row.status === "cancelled" ? "rejected" : "pending_review";
  const risk: DanAction["riskLevel"] =
    row.zone === "red" ? "red" : row.zone === "yellow" ? "yellow" : "green";
  return {
    id: String(row.id),
    clientId: row.client_id ? String(row.client_id) : undefined,
    kind: "draft_outreach",
    title: String(row.title ?? ""),
    detail: String(row.description ?? row.requested_action ?? ""),
    status,
    proposedAt: String(row.created_at ?? new Date().toISOString()),
    executedAt: row.completed_at ? String(row.completed_at) : undefined,
    artifactUrl: Array.isArray(row.artifact_urls) && row.artifact_urls.length > 0
      ? String((row.artifact_urls as string[])[0])
      : undefined,
    riskLevel: risk,
  };
}

/* ─────────────── API helpers ─────────────── */

async function api<T = unknown>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    throw new Error(`${res.status} ${await res.text()}`);
  }
  return res.json() as Promise<T>;
}

/* ─────────────── Context ─────────────── */

type Ctx = AixState & {
  refresh(): Promise<void>;
  addClient(input: {
    name: string;
    industry?: string;
    location?: string;
    contactName?: string;
    contactRole?: string;
    contactPhone?: string;
    contactEmail?: string;
    summary?: string;
    tags?: string[];
    stage?: ClientStage;
    priority?: Priority;
  }): Promise<void>;
  updateClient(id: string, patch: Partial<Client>): Promise<void>;
  deleteClient(id: string): Promise<void>;

  addHypothesis(input: {
    clientId: string;
    title: string;
    problem?: string;
    solution?: string;
    confidence?: number;
    status?: "draft" | "validated";
  }): Promise<void>;

  addOpsTask(input: {
    clientId?: string;
    title: string;
    detail?: string;
    priority?: "high" | "mid" | "low";
    dueDate?: string;
  }): Promise<void>;
  moveOpsTask(id: string, status: OpsTask["status"]): Promise<void>;

  approveDanAction(id: string): Promise<void>;
  rejectDanAction(id: string): Promise<void>;
};

const AixContext = React.createContext<Ctx | null>(null);

export function AixProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = React.useState<AixState>(EMPTY_STATE);

  const refresh = React.useCallback(async () => {
    try {
      const snap = await api<Record<string, Record<string, unknown>[]>>("/snapshot");

      const clients = (snap.clients || []).map(adaptClient);
      const hypotheses = (snap.hypotheses || []).map(adaptHypothesis);
      const proposals = (snap.proposals || []).map(adaptProposal);
      const prototypes = (snap.engagements || []).map(adaptEngagementToProto);

      const outreach: Outreach[] = [];
      const meetings: Meeting[] = [];
      for (const a of snap.activities || []) {
        const o = adaptActivityToOutreach(a);
        if (o) outreach.push(o);
        const m = adaptActivityToMeeting(a);
        if (m) meetings.push(m);
      }

      const contracts = (snap.contracts || []).map(adaptContract);

      const opsTasks: OpsTask[] = [];
      const danActions: DanAction[] = [];
      for (const t of snap.tasks || []) {
        const op = adaptTaskToOps(t);
        if (op) opsTasks.push(op);
        const da = adaptTaskToDanAction(t);
        if (da) danActions.push(da);
      }

      setState({
        clients, hypotheses, proposals, prototypes,
        outreach, meetings, contracts, opsTasks, danActions,
        loaded: true,
      });
    } catch (e) {
      console.warn("aix snapshot fetch failed:", e);
      setState((s) => ({ ...s, loaded: true }));
    }
  }, []);

  React.useEffect(() => {
    refresh();
  }, [refresh]);

  const value = React.useMemo<Ctx>(() => ({
    ...state,
    refresh,

    async addClient(input) {
      const payload = {
        name: input.name,
        industry: input.industry,
        region: input.location,
        contact_name: input.contactName,
        contact_role: input.contactRole,
        contact_phone: input.contactPhone,
        contact_email: input.contactEmail,
        notes: input.summary,
        tags: input.tags,
        stage: input.stage ? stageToDb(input.stage) : "research",
        health_score: healthFromPriority(input.priority),
      };
      await api("/clients", { method: "POST", body: JSON.stringify(payload) });
      await refresh();
    },

    async updateClient(id, patch) {
      const payload: Record<string, unknown> = {};
      if (patch.name !== undefined) payload.name = patch.name;
      if (patch.industry !== undefined) payload.industry = patch.industry;
      if (patch.location !== undefined) payload.region = patch.location;
      if (patch.contactName !== undefined) payload.contact_name = patch.contactName;
      if (patch.contactPhone !== undefined) payload.contact_phone = patch.contactPhone;
      if (patch.summary !== undefined) payload.notes = patch.summary;
      if (patch.tags !== undefined) payload.tags = patch.tags;
      if (patch.stage !== undefined) payload.stage = stageToDb(patch.stage);
      if (patch.priority !== undefined) payload.health_score = healthFromPriority(patch.priority);
      await api(`/clients/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
      await refresh();
    },

    async deleteClient(id) {
      await api(`/clients/${id}`, { method: "DELETE" });
      await refresh();
    },

    async addHypothesis(input) {
      const payload = {
        client_id: input.clientId,
        title: input.title,
        pain_point: input.problem,
        proposed_solution: input.solution,
        confidence: input.confidence ?? 50,
        status: input.status ?? "draft",
      };
      await api("/hypotheses", { method: "POST", body: JSON.stringify(payload) });
      await refresh();
    },

    async addOpsTask(input) {
      const payload = {
        client_id: input.clientId,
        title: input.title,
        description: input.detail,
        priority: input.priority === "mid" ? "normal" : input.priority,
        due_at: input.dueDate ? `${input.dueDate}T17:00:00+09:00` : undefined,
        zone: "green",
        status: "todo",
      };
      await api("/tasks", { method: "POST", body: JSON.stringify(payload) });
      await refresh();
    },

    async moveOpsTask(id, status) {
      const dbStatus = ({
        todo: "todo",
        doing: "in_progress",
        review: "awaiting_approval",
        done: "done",
      } as const)[status];
      const patch: Record<string, unknown> = { status: dbStatus };
      if (status === "done") patch.completed_at = new Date().toISOString();
      await api(`/tasks/${id}`, { method: "PATCH", body: JSON.stringify(patch) });
      await refresh();
    },

    async approveDanAction(id) {
      await api(`/tasks/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: "done", completed_at: new Date().toISOString() }),
      });
      await refresh();
    },

    async rejectDanAction(id) {
      await api(`/tasks/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: "cancelled" }),
      });
      await refresh();
    },
  }), [state, refresh]);

  return <AixContext.Provider value={value}>{children}</AixContext.Provider>;
}

export function useAix() {
  const ctx = React.useContext(AixContext);
  if (!ctx) throw new Error("useAix must be used within AixProvider");
  return ctx;
}
