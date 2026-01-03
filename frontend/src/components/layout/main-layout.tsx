'use client';

import { Sidebar } from './sidebar';
import { NotificationPanel } from '@/components/notification/notification-panel';
import { ProcessMonitor } from '@/components/process/process-monitor';

interface MainLayoutProps {
  children: React.ReactNode;
  showNotifications?: boolean;
  showProcessMonitor?: boolean;
}

export function MainLayout({
  children,
  showNotifications = true,
  showProcessMonitor = true,
}: MainLayoutProps) {
  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <Sidebar />
      <main className="flex-1 flex flex-col overflow-hidden relative">
        {children}
        {showProcessMonitor && <ProcessMonitor />}
        {showNotifications && <NotificationPanel />}
      </main>
    </div>
  );
}

