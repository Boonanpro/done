'use client';

import { useState } from 'react';
import { ProjectListPanel } from './project-list-panel';
import { ProjectChatPanel } from './project-chat-panel';
import { NotificationPanel } from '@/components/notification/notification-panel';
import { useProjectStore } from '@/stores/project-store';

interface MainLayoutProps {
  children: React.ReactNode;
  showNotifications?: boolean;
}

export function MainLayout({
  children,
  showNotifications = true,
}: MainLayoutProps) {
  const [isCollapsed, setIsCollapsed] = useState(false);
  const selectedProjectId = useProjectStore((s) => s.selectedProjectId);

  const gridCols = selectedProjectId
    ? isCollapsed
      ? '64px 400px 1fr'
      : '280px 400px 1fr'
    : isCollapsed
      ? '64px 0px 1fr'
      : '280px 0px 1fr';

  return (
    <div
      className="grid h-dvh overflow-hidden bg-background transition-[grid-template-columns] duration-300 ease-in-out"
      style={{ gridTemplateColumns: gridCols }}
    >
      <ProjectListPanel
        isCollapsed={isCollapsed}
        onToggleCollapse={() => setIsCollapsed(!isCollapsed)}
      />
      <div className="overflow-hidden">
        {selectedProjectId && (
          <ProjectChatPanel projectId={selectedProjectId} />
        )}
      </div>
      <main className="flex flex-col overflow-hidden relative">
        {children}
        {showNotifications && <NotificationPanel />}
      </main>
    </div>
  );
}
