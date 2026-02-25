'use client';

import { useState, useRef, useCallback, useEffect } from 'react';
import { Menu } from 'lucide-react';
import { ProjectListPanel } from './project-list-panel';
import { ProjectChatPanel } from './project-chat-panel';
import { NotificationPanel } from '@/components/notification/notification-panel';
import { useProjectStore } from '@/stores/project-store';
import { useIsMobile } from '@/hooks/useIsMobile';

interface MainLayoutProps {
  children: React.ReactNode;
  showNotifications?: boolean;
}

const DEFAULT_PROJECT_CHAT_WIDTH = 520;
const MIN_PROJECT_CHAT_WIDTH = 320;
const MAX_PROJECT_CHAT_WIDTH = 900;

export function MainLayout({
  children,
  showNotifications = true,
}: MainLayoutProps) {
  const isMobile = useIsMobile();
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [hasOpenedMobileSidebar, setHasOpenedMobileSidebar] = useState(false);
  const selectedProjectId = useProjectStore((s) => s.selectedProjectId);

  const [projectChatWidth, setProjectChatWidth] = useState(DEFAULT_PROJECT_CHAT_WIDTH);
  const [isDragging, setIsDragging] = useState(false);
  const dragStartX = useRef(0);
  const dragStartWidth = useRef(0);

  // Close sidebar when selecting a project on mobile
  useEffect(() => {
    if (isMobile) setSidebarOpen(false);
  }, [selectedProjectId, isMobile]);

  useEffect(() => {
    if (isMobile && !hasOpenedMobileSidebar) {
      setSidebarOpen(true);
      setHasOpenedMobileSidebar(true);
    }
  }, [isMobile, hasOpenedMobileSidebar]);

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      if (isMobile) return;
      e.preventDefault();
      setIsDragging(true);
      dragStartX.current = e.clientX;
      dragStartWidth.current = projectChatWidth;
    },
    [projectChatWidth, isMobile]
  );

  useEffect(() => {
    if (!isDragging) return;

    const handleMouseMove = (e: MouseEvent) => {
      const delta = e.clientX - dragStartX.current;
      const newWidth = Math.min(
        MAX_PROJECT_CHAT_WIDTH,
        Math.max(MIN_PROJECT_CHAT_WIDTH, dragStartWidth.current + delta)
      );
      setProjectChatWidth(newWidth);
    };

    const handleMouseUp = () => {
      setIsDragging(false);
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging]);

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

        {/* Content: either project chat (full screen) or main chat */}
        {selectedProjectId ? (
          <div className="h-full">
            <ProjectChatPanel projectId={selectedProjectId} />
          </div>
        ) : (
          <main className="flex flex-col h-full overflow-hidden">
            {children}
            {showNotifications && <NotificationPanel />}
          </main>
        )}
      </div>
    );
  }

  // ===== Desktop Layout (unchanged) =====
  const sidebarWidth = isCollapsed ? '64px' : '280px';
  const gridCols = selectedProjectId
    ? `${sidebarWidth} ${projectChatWidth}px 4px 1fr`
    : `${sidebarWidth} 0px 0px 1fr`;

  return (
    <div
      className={`grid h-dvh overflow-hidden bg-background ${
        isDragging ? '' : 'transition-[grid-template-columns] duration-300 ease-in-out'
      }`}
      style={{
        gridTemplateColumns: gridCols,
        cursor: isDragging ? 'col-resize' : undefined,
      }}
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
      {selectedProjectId && (
        <div
          onMouseDown={handleMouseDown}
          className="group flex items-center justify-center cursor-col-resize hover:bg-primary/10 active:bg-primary/20 transition-colors"
        >
          <div className="w-[2px] h-8 rounded-full bg-border group-hover:bg-primary/40 group-active:bg-primary/60 transition-colors" />
        </div>
      )}
      {!selectedProjectId && <div />}
      <main className="flex flex-col overflow-hidden relative">
        {children}
        {showNotifications && <NotificationPanel />}
      </main>
    </div>
  );
}
