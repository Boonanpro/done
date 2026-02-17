'use client';

import { useState, useRef, useCallback, useEffect } from 'react';
import { ProjectListPanel } from './project-list-panel';
import { ProjectChatPanel } from './project-chat-panel';
import { NotificationPanel } from '@/components/notification/notification-panel';
import { useProjectStore } from '@/stores/project-store';

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
  const [isCollapsed, setIsCollapsed] = useState(false);
  const selectedProjectId = useProjectStore((s) => s.selectedProjectId);

  const [projectChatWidth, setProjectChatWidth] = useState(DEFAULT_PROJECT_CHAT_WIDTH);
  const [isDragging, setIsDragging] = useState(false);
  const dragStartX = useRef(0);
  const dragStartWidth = useRef(0);

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      setIsDragging(true);
      dragStartX.current = e.clientX;
      dragStartWidth.current = projectChatWidth;
    },
    [projectChatWidth]
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
