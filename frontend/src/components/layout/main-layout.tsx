'use client';

import { useState, useEffect } from 'react';
import { Menu, FolderOpen } from 'lucide-react';
import { ProjectListPanel } from './project-list-panel';
import { ProjectChatPanel } from './project-chat-panel';
import { NotificationPanel } from '@/components/notification/notification-panel';
import { useProjectStore } from '@/stores/project-store';
import { useIsMobile } from '@/hooks/useIsMobile';

interface MainLayoutProps {
  children?: React.ReactNode;
  showNotifications?: boolean;
}

export function MainLayout({
  children: _children,
  showNotifications = true,
}: MainLayoutProps) {
  const isMobile = useIsMobile();
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [hasOpenedMobileSidebar, setHasOpenedMobileSidebar] = useState(false);
  const selectedProjectId = useProjectStore((s) => s.selectedProjectId);

  // When switching from desktop to mobile, reset sidebar state once.
  useEffect(() => {
    if (isMobile) setSidebarOpen(false);
  }, [isMobile]);

  useEffect(() => {
    if (isMobile && !hasOpenedMobileSidebar) {
      setSidebarOpen(true);
      setHasOpenedMobileSidebar(true);
    }
  }, [isMobile, hasOpenedMobileSidebar]);

  // ===== Mobile Layout =====
  if (isMobile) {
    return (
      <div className="relative h-dvh overflow-hidden bg-background">
        {/* Hamburger button */}
        <button
          onClick={() => setSidebarOpen(true)}
          className="fixed top-3 left-3 z-40 h-9 w-9 flex items-center justify-center rounded-lg bg-background/80 backdrop-blur border border-border"
        >
          <Menu className="h-5 w-5" />
        </button>

        {/* Sidebar overlay */}
        {sidebarOpen && (
          <>
            <div
              className="fixed inset-0 z-40 bg-black/50"
              onClick={() => setSidebarOpen(false)}
            />
            <div className="fixed inset-y-0 left-0 z-50 w-[280px] animate-in slide-in-from-left duration-200">
              <ProjectListPanel
                isCollapsed={false}
                onToggleCollapse={() => setSidebarOpen(false)}
              />
            </div>
          </>
        )}

        {/* Content: project chat or empty state */}
        {selectedProjectId ? (
          <div className="h-full">
            <ProjectChatPanel projectId={selectedProjectId} />
          </div>
        ) : (
          <div className="h-full flex flex-col items-center justify-center text-muted-foreground gap-3 px-6">
            <FolderOpen className="h-12 w-12 opacity-40" />
            <p className="text-center text-sm">左のメニューからプロジェクトを選択してください</p>
          </div>
        )}
        {showNotifications && <NotificationPanel />}
      </div>
    );
  }

  // ===== Desktop Layout =====
  const sidebarWidth = isCollapsed ? '64px' : '280px';

  return (
    <div
      className="grid h-dvh overflow-hidden bg-background transition-[grid-template-columns] duration-300 ease-in-out"
      style={{
        gridTemplateColumns: `${sidebarWidth} 1fr`,
      }}
    >
      <ProjectListPanel
        isCollapsed={isCollapsed}
        onToggleCollapse={() => setIsCollapsed(!isCollapsed)}
      />
      <main className="flex flex-col overflow-hidden relative">
        {selectedProjectId ? (
          <ProjectChatPanel projectId={selectedProjectId} />
        ) : (
          <div className="h-full flex flex-col items-center justify-center text-muted-foreground gap-3">
            <FolderOpen className="h-16 w-16 opacity-30" />
            <p className="text-sm">プロジェクトを選択してください</p>
          </div>
        )}
        {showNotifications && <NotificationPanel />}
      </main>
    </div>
  );
}
