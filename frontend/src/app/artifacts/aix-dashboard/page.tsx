"use client";

import { useState } from "react";
import { AixProvider } from "./data/store";
import { AixSidebar, type AixView } from "./components/sidebar";
import { HomeView } from "./components/views/home-view";
import { ClientsView } from "./components/views/clients-view";
import { ClientDetailView } from "./components/views/client-detail-view";
import {
  HypothesesView,
  ProposalsView,
  PrototypesView,
  OutreachView,
  MeetingsView,
  OpsView,
  ActionsView,
} from "./components/views/simple-views";
import { useAix } from "./data/store";

type ViewState =
  | { kind: AixView }
  | { kind: "client-detail"; clientId: string };

export default function AixDashboardPage() {
  return (
    <AixProvider>
      <Shell />
    </AixProvider>
  );
}

function Shell() {
  const [view, setView] = useState<ViewState>({ kind: "home" });
  const { danActions } = useAix();
  const pendingActions = danActions.filter((a) => a.status === "pending_review").length;

  const openClient = (clientId: string) =>
    setView({ kind: "client-detail", clientId });

  const activeNav: AixView =
    view.kind === "client-detail" ? "clients" : (view.kind as AixView);

  const renderView = () => {
    switch (view.kind) {
      case "home":
        return (
          <HomeView
            onNavigate={(v) => setView({ kind: v })}
            onOpenClient={openClient}
          />
        );
      case "clients":
        return <ClientsView onOpen={openClient} />;
      case "client-detail":
        return (
          <ClientDetailView
            clientId={view.clientId}
            onBack={() => setView({ kind: "clients" })}
          />
        );
      case "hypotheses":
        return <HypothesesView />;
      case "proposals":
        return <ProposalsView onOpenClient={openClient} />;
      case "prototypes":
        return <PrototypesView onOpenClient={openClient} />;
      case "outreach":
        return <OutreachView onOpenClient={openClient} />;
      case "meetings":
        return <MeetingsView onOpenClient={openClient} />;
      case "ops":
        return <OpsView onOpenClient={openClient} />;
      case "actions":
        return <ActionsView onOpenClient={openClient} />;
      default:
        return null;
    }
  };

  return (
    <div className="flex h-screen bg-background text-foreground">
      <AixSidebar
        active={activeNav}
        onNavigate={(v) => setView({ kind: v })}
        pendingActions={pendingActions}
      />
      <main className="flex-1 overflow-auto">
        <div className="mx-auto max-w-7xl px-6 py-8">{renderView()}</div>
      </main>
    </div>
  );
}
