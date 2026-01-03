'use client';

import { Sidebar } from './sidebar';
import { NotificationPanel } from '@/components/notification/notification-panel';

interface MainLayoutProps {
  children: React.ReactNode;
  showNotifications?: boolean;
}

export function MainLayout({ children, showNotifications = true }: MainLayoutProps) {
  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <Sidebar />
      <main className="flex-1 flex flex-col overflow-hidden relative">
        {children}
        {showNotifications && <NotificationPanel />}
      </main>
    </div>
  );
}

