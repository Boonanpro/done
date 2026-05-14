'use client';

import { useEffect, useState, useCallback } from 'react';

const API_URL = '';

export function usePushNotification(roomId: string, senderType: string) {
  const [permission, setPermission] = useState<NotificationPermission>('default');
  const [subscribed, setSubscribed] = useState(false);

  useEffect(() => {
    if (typeof window !== 'undefined' && 'Notification' in window) {
      setPermission(Notification.permission);
    }
  }, []);

  const subscribe = useCallback(async () => {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
      console.warn('Push not supported');
      return false;
    }

    try {
      // Request permission
      const perm = await Notification.requestPermission();
      setPermission(perm);
      if (perm !== 'granted') return false;

      // Register service worker
      const reg = await navigator.serviceWorker.register('/sw.js');
      await navigator.serviceWorker.ready;

      // Get VAPID key
      const vapidRes = await fetch(`${API_URL}/api/v1/push/vapid-key`);
      const { publicKey } = await vapidRes.json();
      if (!publicKey) return false;

      // Convert VAPID key
      const applicationServerKey = urlBase64ToUint8Array(publicKey) as any;

      const existingSubscription = await reg.pushManager.getSubscription();
      if (existingSubscription) {
        await existingSubscription.unsubscribe();
      }

      // Subscribe
      const subscription = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey,
      });

      // Save to backend
      await fetch(`${API_URL}/api/v1/push/subscribe`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          room_id: roomId,
          sender_type: senderType,
          subscription: subscription.toJSON(),
        }),
      });

      setSubscribed(true);
      return true;
    } catch (e) {
      console.error('Push subscription error:', e);
      return false;
    }
  }, [roomId, senderType]);

  const sendTest = useCallback(async (): Promise<{ ok: boolean; message?: string }> => {
    const token = localStorage.getItem('done-token');

    try {
      const headers: HeadersInit = {};
      if (token) headers.Authorization = `Bearer ${token}`;
      const res = await fetch(`${API_URL}/api/v1/push/test`, {
        method: 'POST',
        headers,
        credentials: 'include',
      });
      if (res.ok) return { ok: true };
      const data = await res.json().catch(() => null);
      const detail = data?.detail;
      if (detail?.attempted === 0) {
        return { ok: false, message: 'この端末の通知購読がまだ保存されていません' };
      }
      if (detail?.failed) {
        return { ok: false, message: '通知サービスへの送信に失敗しました' };
      }
      return { ok: false };
    } catch (e) {
      console.error('Push test error:', e);
      return { ok: false };
    }
  }, []);

  // Auto-subscribe if permission already granted
  useEffect(() => {
    if (permission === 'granted' && roomId && senderType && !subscribed) {
      subscribe();
    }
  }, [permission, roomId, senderType, subscribed, subscribe]);

  return { permission, subscribed, subscribe, sendTest };
}

function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const rawData = atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}
