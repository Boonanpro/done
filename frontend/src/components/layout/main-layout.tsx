'use client';

import { useState, useEffect, useCallback } from 'react';
import { Menu, FolderOpen } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Sidebar } from './sidebar';
import { ProjectChatPanel } from './project-chat-panel';
import { NotificationPanel } from '@/components/notification/notification-panel';
import { useProjectStore } from '@/stores/project-store';
import { useIsMobile } from '@/hooks/useIsMobile';

interface MainLayoutProps {
  children?: React.ReactNode;
  showNotifications?: boolean;
}

export function MainLayout({
  children,
  showNotifications = true,
}: MainLayoutProps) {
  const isMobile = useIsMobile();
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(280);
  const [isResizing, setIsResizing] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [hasOpenedMobileSidebar, setHasOpenedMobileSidebar] = useState(false);
  const selectedProjectId = useProjectStore((s) => s.selectedProjectId);

  const handleResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    const startX = e.clientX;
    const startWidth = sidebarWidth;
    setIsResizing(true);
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';

    const handleMouseMove = (e: MouseEvent) => {
      setSidebarWidth(Math.max(180, Math.min(600, startWidth + e.clientX - startX)));
    };
    const handleMouseUp = () => {
      setIsResizing(false);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
  }, [sidebarWidth]);

  // When switching from desktop to mobile, reset sidebar state once.
  useEffect(() => {
    if (isMobile) setSidebarOpen(false);
  }, [isMobile]);

  const hasChildren = !!children;
  useEffect(() => {
    if (isMobile && !hasOpenedMobileSidebar && !hasChildren) {
      setSidebarOpen(true);
      setHasOpenedMobileSidebar(true);
    }
  }, [isMobile, hasOpenedMobileSidebar, hasChildren]);

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
              <Sidebar
                isCollapsed={false}
                onToggleCollapse={() => setSidebarOpen(false)}
                showNotifications={showNotifications}
              />
            </div>
          </>
        )}

        {/* Content: children, project chat, or empty state */}
        {children ? (
          <div className="h-full">{children}</div>
        ) : selectedProjectId ? (
          <div className="h-full">
            <ProjectChatPanel projectId={selectedProjectId} />
          </div>
        ) : (
          <div className="h-full flex flex-col items-center justify-center text-muted-foreground gap-3 px-6">
            <FolderOpen className="h-12 w-12 opacity-40" />
            <p className="text-center text-sm">左のメニューからプロジェクトを選択してください</p>
          </div>
        )}
      </div>
    );
  }

  // ===== Desktop Layout =====
  const effectiveWidth = isCollapsed ? 64 : sidebarWidth;

  return (
    <div className="relative flex h-dvh overflow-hidden bg-background">
      {/* Sidebar */}
      <div
        className={cn(
          'relative shrink-0 overflow-hidden',
          !isResizing && 'transition-[width] duration-300 ease-in-out'
        )}
        style={{ width: effectiveWidth }}
      >
        <Sidebar
          isCollapsed={isCollapsed}
          onToggleCollapse={() => setIsCollapsed(!isCollapsed)}
        />
      </div>
      {/* Resize handle */}
      {!isCollapsed && (
        <div
          className="absolute top-0 h-full z-10 w-3 -translate-x-1/2 cursor-col-resize group"
          style={{ left: effectiveWidth }}
          onMouseDown={handleResizeStart}
        >
          <div className="absolute inset-y-0 left-1/2 w-0.5 -translate-x-1/2 group-hover:bg-primary/40 transition-colors" />
        </div>
      )}
      <main className="flex flex-1 flex-col overflow-hidden relative min-w-0">
        {children ? (
          children
        ) : selectedProjectId ? (
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
