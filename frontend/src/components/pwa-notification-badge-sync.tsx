'use client';

import { useEffect } from 'react';
import { usePathname } from 'next/navigation';

type BadgeNavigator = Navigator & {
  clearAppBadge?: () => Promise<void>;
  setAppBadge?: (contents?: number) => Promise<void>;
};

function normalizePath(url: string) {
  try {
    return new URL(url, window.location.origin).pathname;
  } catch {
    return url;
  }
}

function isSameNotificationTarget(notificationPath: string, currentPath: string) {
  if (notificationPath === currentPath) return true;

  // Dan completion notifications target /chat/:projectId. Treat that chat as read
  // when the user is viewing the exact project page.
  if (notificationPath.startsWith('/chat/') && currentPath.startsWith('/chat/')) {
    return notificationPath.split('?')[0] === currentPath.split('?')[0];
  }

  // Collaboration notifications target /collab/:roomId or /collab/join/:token.
  if (notificationPath.startsWith('/collab/') && currentPath.startsWith('/collab/')) {
    return notificationPath.split('?')[0] === currentPath.split('?')[0];
  }

  return false;
}

async function syncBadgeForPath(pathname: string) {
  if (!('serviceWorker' in navigator)) return;

  try {
    const registration = await navigator.serviceWorker.ready;
    const notifications = await registration.getNotifications();
    let closed = 0;

    notifications.forEach((notification) => {
      const targetPath = normalizePath(notification.data?.url || '/');
      if (isSameNotificationTarget(targetPath, pathname)) {
        notification.close();
        closed += 1;
      }
    });

    if (closed === 0) return;

    const remaining = await registration.getNotifications();
    const nav = navigator as BadgeNavigator;
    if (remaining.length > 0) {
      await nav.setAppBadge?.(remaining.length);
    } else {
      await nav.clearAppBadge?.();
    }
  } catch {
    // Badge and notification APIs are best-effort across Android launchers.
  }
}

export function PwaNotificationBadgeSync() {
  const pathname = usePathname();

  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (!pathname) return;

    const sync = () => void syncBadgeForPath(pathname);
    sync();

    const handleFocus = () => sync();
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') sync();
    };

    window.addEventListener('focus', handleFocus);
    window.addEventListener('pageshow', handleFocus);
    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      window.removeEventListener('focus', handleFocus);
      window.removeEventListener('pageshow', handleFocus);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [pathname]);

  return null;
}
