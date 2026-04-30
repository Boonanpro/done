"use client";

import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import type { Client, Equipment, MeasuringInstrument, ReportData } from "./types";
import { initialClients, initialEquipments, initialInstruments } from "./mock-data";

type State = {
  clients: Client[];
  equipments: Equipment[];
  instruments: MeasuringInstrument[];

  saveDirHandle: FileSystemDirectoryHandle | null;
  saveDirName: string;

  // ドラフト中の生成データ
  currentReport: ReportData | null;
  currentClientId: string | null;

  upsertClient: (c: Client) => void;
  removeClient: (id: string) => void;

  upsertEquipment: (e: Equipment) => void;
  removeEquipment: (id: string) => void;

  upsertInstrument: (m: MeasuringInstrument) => void;
  removeInstrument: (id: string) => void;

  setCurrentReport: (r: ReportData | null, clientId: string | null) => void;
  updateReport: (patch: Partial<ReportData>) => void;

  setSaveDir: (h: FileSystemDirectoryHandle | null, name: string) => void;

  reset: () => void;
};

export const useInspectionStore = create<State>()(
  persist(
    (set) => ({
      clients: initialClients,
      equipments: initialEquipments,
      instruments: initialInstruments,
      saveDirHandle: null,
      saveDirName: "",
      currentReport: null,
      currentClientId: null,

      upsertClient: (c) =>
        set((s) => {
          const idx = s.clients.findIndex((x) => x.id === c.id);
          if (idx >= 0) {
            const next = [...s.clients];
            next[idx] = c;
            return { clients: next };
          }
          return { clients: [...s.clients, c] };
        }),

      removeClient: (id) =>
        set((s) => ({ clients: s.clients.filter((c) => c.id !== id) })),

      upsertEquipment: (e) =>
        set((s) => {
          const idx = s.equipments.findIndex((x) => x.id === e.id);
          if (idx >= 0) {
            const next = [...s.equipments];
            next[idx] = e;
            return { equipments: next };
          }
          return { equipments: [...s.equipments, e] };
        }),

      removeEquipment: (id) =>
        set((s) => ({ equipments: s.equipments.filter((e) => e.id !== id) })),

      upsertInstrument: (m) =>
        set((s) => {
          const idx = s.instruments.findIndex((x) => x.id === m.id);
          if (idx >= 0) {
            const next = [...s.instruments];
            next[idx] = m;
            return { instruments: next };
          }
          return { instruments: [...s.instruments, m] };
        }),

      removeInstrument: (id) =>
        set((s) => ({ instruments: s.instruments.filter((m) => m.id !== id) })),

      setCurrentReport: (r, clientId) => set({ currentReport: r, currentClientId: clientId }),

      updateReport: (patch) =>
        set((s) => (s.currentReport ? { currentReport: { ...s.currentReport, ...patch } } : {})),

      setSaveDir: (h, name) => set({ saveDirHandle: h, saveDirName: name }),

      reset: () =>
        set({
          clients: initialClients,
          equipments: initialEquipments,
          instruments: initialInstruments,
          currentReport: null,
          currentClientId: null,
        }),
    }),
    {
      name: "inspection-report-store",
      storage: createJSONStorage(() => localStorage),
      partialize: (s) => ({
        clients: s.clients,
        equipments: s.equipments,
        instruments: s.instruments,
        saveDirName: s.saveDirName,
      }),
    },
  ),
);
