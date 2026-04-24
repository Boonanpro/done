"use client";

import * as React from "react";
import {
  SEED_CLIENTS,
  SEED_HYPOTHESES,
  SEED_PROPOSALS,
  SEED_PROTOTYPES,
  SEED_OUTREACH,
  SEED_MEETINGS,
  SEED_CONTRACTS,
  SEED_OPS_TASKS,
  SEED_DAN_ACTIONS,
  type Client,
  type Hypothesis,
  type Proposal,
  type Prototype,
  type Outreach,
  type Meeting,
  type Contract,
  type OpsTask,
  type DanAction,
} from "./mock";

const LS_KEY = "aix-dashboard-v1";

type AixState = {
  clients: Client[];
  hypotheses: Hypothesis[];
  proposals: Proposal[];
  prototypes: Prototype[];
  outreach: Outreach[];
  meetings: Meeting[];
  contracts: Contract[];
  opsTasks: OpsTask[];
  danActions: DanAction[];
};

function seed(): AixState {
  return {
    clients: SEED_CLIENTS,
    hypotheses: SEED_HYPOTHESES,
    proposals: SEED_PROPOSALS,
    prototypes: SEED_PROTOTYPES,
    outreach: SEED_OUTREACH,
    meetings: SEED_MEETINGS,
    contracts: SEED_CONTRACTS,
    opsTasks: SEED_OPS_TASKS,
    danActions: SEED_DAN_ACTIONS,
  };
}

function load(): AixState {
  if (typeof window === "undefined") return seed();
  try {
    const raw = window.localStorage.getItem(LS_KEY);
    if (!raw) return seed();
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return seed();
    // 新しいシードフィールドがあってもマージ
    return { ...seed(), ...parsed };
  } catch {
    return seed();
  }
}

function save(state: AixState) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(LS_KEY, JSON.stringify(state));
  } catch {
    /* ignore */
  }
}

type Ctx = AixState & {
  /* --- Clients --- */
  addClient(client: Omit<Client, "id" | "assignedAt">): Client;
  updateClient(id: string, patch: Partial<Client>): void;
  /* --- Hypotheses --- */
  addHypothesis(h: Omit<Hypothesis, "id" | "createdAt">): Hypothesis;
  updateHypothesis(id: string, patch: Partial<Hypothesis>): void;
  /* --- Proposals --- */
  updateProposal(id: string, patch: Partial<Proposal>): void;
  /* --- OpsTasks --- */
  moveOpsTask(id: string, status: OpsTask["status"]): void;
  addOpsTask(t: Omit<OpsTask, "id">): OpsTask;
  /* --- DanActions --- */
  approveDanAction(id: string): void;
  rejectDanAction(id: string): void;
  /* misc */
  reset(): void;
};

const AixContext = React.createContext<Ctx | null>(null);

export function AixProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = React.useState<AixState>(() => seed());

  React.useEffect(() => {
    setState(load());
  }, []);

  React.useEffect(() => {
    save(state);
  }, [state]);

  const value = React.useMemo<Ctx>(() => {
    function patch<K extends keyof AixState>(
      key: K,
      mutator: (prev: AixState[K]) => AixState[K],
    ) {
      setState((prev) => ({ ...prev, [key]: mutator(prev[key]) }));
    }

    const nextId = (prefix: string) =>
      `${prefix}_${Math.random().toString(36).slice(2, 8)}`;

    return {
      ...state,
      addClient(client) {
        const next: Client = {
          ...client,
          id: nextId("cli"),
          assignedAt: new Date().toISOString().slice(0, 10),
        };
        patch("clients", (list) => [next, ...list]);
        return next;
      },
      updateClient(id, p) {
        patch("clients", (list) =>
          list.map((c) => (c.id === id ? { ...c, ...p } : c)),
        );
      },
      addHypothesis(h) {
        const next: Hypothesis = {
          ...h,
          id: nextId("hyp"),
          createdAt: new Date().toISOString().slice(0, 10),
        };
        patch("hypotheses", (list) => [next, ...list]);
        return next;
      },
      updateHypothesis(id, p) {
        patch("hypotheses", (list) =>
          list.map((h) => (h.id === id ? { ...h, ...p } : h)),
        );
      },
      updateProposal(id, p) {
        patch("proposals", (list) =>
          list.map((pr) => (pr.id === id ? { ...pr, ...p } : pr)),
        );
      },
      moveOpsTask(id, status) {
        patch("opsTasks", (list) =>
          list.map((t) => (t.id === id ? { ...t, status } : t)),
        );
      },
      addOpsTask(t) {
        const next: OpsTask = { ...t, id: nextId("op") };
        patch("opsTasks", (list) => [next, ...list]);
        return next;
      },
      approveDanAction(id) {
        patch("danActions", (list) =>
          list.map((a) =>
            a.id === id
              ? {
                  ...a,
                  status: "executed",
                  executedAt: new Date().toISOString(),
                }
              : a,
          ),
        );
      },
      rejectDanAction(id) {
        patch("danActions", (list) =>
          list.map((a) => (a.id === id ? { ...a, status: "rejected" } : a)),
        );
      },
      reset() {
        setState(seed());
      },
    };
  }, [state]);

  return <AixContext.Provider value={value}>{children}</AixContext.Provider>;
}

export function useAix() {
  const ctx = React.useContext(AixContext);
  if (!ctx) throw new Error("useAix must be used within AixProvider");
  return ctx;
}
