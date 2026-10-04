'use client';

import { useState, useEffect, useRef } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { Menu, FolderOpen } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Sidebar } from './sidebar';
import { ProjectChatPanel } from './project-chat-panel';
import { useProjectStore } from '@/stores/project-store';
import { usePreviewStore } from '@/stores/preview-store';
import { useIsMobile } from '@/hooks/useIsMobile';
import { useCollabNotifications } from '@/hooks/useCollabNotifications';

interface MainLayoutProps {
  children?: React.ReactNode;
  showNotifications?: boolean;
  hideHamburger?: boolean;
}

export function MainLayout({
  children,
  showNotifications = true,
  hideHamburger = false,
}: MainLayoutProps) {
  const isMobile = useIsMobile();
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(280);
  const [isResizing, setIsResizing] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [hasOpenedMobileSidebar, setHasOpenedMobileSidebar] = useState(false);
  const resizeOrigin = useRef<{ x: number; width: number } | null>(null);
  const [maxSidebarWidth, setMaxSidebarWidth] = useState(480);
  const selectedProjectId = useProjectStore((s) => s.selectedProjectId);
  const previewIsOpen = usePreviewStore((s) => s.isOpen);

  // プレビュー表示中、ダンが demo ファイルを書き換えた時に親ページ全体に
  // 出てしまう Next.js dev overlay を抑制する（一過性のコンパイルエラーは
  // iframe 側の auto-reload で解消されるため、overlay が邪魔）
  useEffect(() => {
    if (!previewIsOpen) return;
    const style = document.createElement('style');
    style.id = 'dan-hide-nextjs-overlay';
    style.textContent = `
      nextjs-portal,
      [data-nextjs-dialog-overlay],
      [data-nextjs-dialog],
      #__next-build-watcher {
        display: none !important;
      }
    `;
    document.head.appendChild(style);
    return () => {
      document.getElementById('dan-hide-nextjs-overlay')?.remove();
    };
  }, [previewIsOpen]);

  // Show toast notifications for new collab messages
  useCollabNotifications();

  useEffect(() => {
    const fitSidebar = () => {
      const max = Math.max(220, Math.min(480, window.innerWidth - 360));
      setMaxSidebarWidth(max);
      setSidebarWidth((width) => Math.max(220, Math.min(max, width)));
    };
    fitSidebar();
    window.addEventListener('resize', fitSidebar);
    return () => window.removeEventListener('resize', fitSidebar);
  }, []);

  const finishResize = () => {
    resizeOrigin.current = null;
    setIsResizing(false);
  };

  // A newly selected conversation should be visible immediately behind the drawer.
  useEffect(() => { setSidebarOpen(false); }, [selectedProjectId, isMobile, previewIsOpen]);

  const hasChildren = !!children;
  useEffect(() => {
    if (isMobile && !hasOpenedMobileSidebar && !hasChildren && !selectedProjectId) {
      setSidebarOpen(true);
      setHasOpenedMobileSidebar(true);
    }
  }, [isMobile, hasOpenedMobileSidebar, hasChildren, selectedProjectId]);

  const navigationDrawer = (
    <Dialog.Root open={sidebarOpen} onOpenChange={setSidebarOpen}>
      {(!isMobile || !hideHamburger) && (
        <Dialog.Trigger asChild>
          <button
            type="button"
            aria-label="メニューを開く"
            title="メニューを開く"
            className={cn(
              'flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border border-border bg-background text-foreground shadow-sm hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary',
              isMobile ? 'fixed top-3 left-3 z-40' : 'm-2'
            )}
          >
            <Menu className="h-5 w-5" aria-hidden="true" />
          </button>
        </Dialog.Trigger>
      )}
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/50" />
        <Dialog.Content
          aria-describedby={undefined}
          className="fixed inset-y-0 left-0 z-50 w-[min(320px,calc(100vw-48px))] overflow-hidden border-r border-border bg-background shadow-xl outline-none"
        >
          <Dialog.Title className="sr-only">ダンのメニュー</Dialog.Title>
          <div className="flex h-full flex-col">
            <div className="flex shrink-0 items-center justify-between border-b border-border px-4 py-2">
              <span className="text-sm font-medium">メニュー</span>
              <Dialog.Close className="min-h-12 rounded-lg px-3 text-sm text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:outline-2 focus-visible:outline-primary">閉じる</Dialog.Close>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto" onClick={(event) => {
              if ((event.target as HTMLElement).closest('a[href]')) setSidebarOpen(false);
            }}>
              <Sidebar isCollapsed={false} onToggleCollapse={() => setSidebarOpen(false)} showNotifications={showNotifications} />
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );

  // ===== Mobile Layout =====
  if (isMobile) {
    return (
      <div className="relative h-dvh overflow-hidden bg-background">
        {navigationDrawer}


        {/* Content: children, project chat, or empty state */}
        {children ? (
          <div className="h-full">{children}</div>
        ) : selectedProjectId ? (
          <div className="h-full">
            <ProjectChatPanel key={selectedProjectId} projectId={selectedProjectId} />
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
      {previewIsOpen ? <div className="shrink-0 border-r border-border bg-sidebar">{navigationDrawer}</div> : <div
        id="dan-sidebar"
        className="relative shrink-0 overflow-hidden border-r border-border"
        style={{ width: effectiveWidth }}
      >
        <Sidebar
          isCollapsed={isCollapsed}
          onToggleCollapse={() => setIsCollapsed(!isCollapsed)}
        />
      </div>}
      {/* Resize handle (only when sidebar is permanent) */}
      {!isCollapsed && !previewIsOpen && (
        <div
          className="absolute top-0 h-full z-10 w-3 -translate-x-1/2 cursor-col-resize group"
          role="separator"
          tabIndex={0}
          aria-label="メニューの幅"
          aria-controls="dan-sidebar"
          aria-orientation="vertical"
          aria-valuemin={220}
          aria-valuemax={maxSidebarWidth}
          aria-valuenow={sidebarWidth}
          aria-valuetext={`${sidebarWidth}px`}
          title="ドラッグまたは左右キーで幅を変更。Homeで最小、Endで最大、ダブルクリックで標準幅。"
          style={{ left: effectiveWidth, touchAction: 'none' }}
          onDoubleClick={() => setSidebarWidth(Math.min(280, maxSidebarWidth))}
          onKeyDown={(event) => {
            const delta = event.shiftKey ? 40 : 16;
            const next = event.key === 'ArrowLeft' ? sidebarWidth - delta : event.key === 'ArrowRight' ? sidebarWidth + delta : event.key === 'Home' ? 220 : event.key === 'End' ? maxSidebarWidth : null;
            if (next !== null) {
              event.preventDefault();
              setSidebarWidth(Math.max(220, Math.min(maxSidebarWidth, next)));
            }
          }}
          onPointerDown={(event) => {
            if (event.button !== 0) return;
            event.preventDefault();
            event.currentTarget.focus();
            event.currentTarget.setPointerCapture(event.pointerId);
            resizeOrigin.current = { x: event.clientX, width: sidebarWidth };
            setIsResizing(true);
          }}
          onPointerMove={(event) => {
            const origin = resizeOrigin.current;
            if (origin) setSidebarWidth(Math.max(220, Math.min(maxSidebarWidth, origin.width + event.clientX - origin.x)));
          }}
          onPointerUp={finishResize}
          onPointerCancel={finishResize}
          onLostPointerCapture={finishResize}
        >
          <div className={cn('absolute inset-y-0 left-1/2 w-0.5 -translate-x-1/2 group-hover:bg-primary/40 group-focus-visible:bg-primary', isResizing && 'bg-primary')} />
        </div>
      )}
      <main className="flex flex-1 flex-col overflow-hidden relative min-w-0">
        {children ? (
          children
        ) : selectedProjectId ? (
          <ProjectChatPanel key={selectedProjectId} projectId={selectedProjectId} />
        ) : (
          <div className="h-full flex flex-col items-center justify-center text-muted-foreground gap-3">
            <FolderOpen className="h-16 w-16 opacity-30" />
            <p className="text-sm">プロジェクトを選択してください</p>
          </div>
        )}
        {/* No notification bell (2026-10-01): what reaches the user from outside is said by Dan in chat (app/services/inbox.py). */}
      </main>
    </div>
  );
}
